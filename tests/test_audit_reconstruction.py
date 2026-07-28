from __future__ import annotations

import json

import pytest

from agentic_governance import (
    CANONICAL_AUDIT_SOURCE,
    load_failure_records,
    reconstruct_claim_audit,
    verify_audit_chain,
)
from agentic_governance.adapters.jsonl_audit import (
    JsonlAuditSink,
    build_custom_audit_event,
    build_failure_audit_event,
)
from agentic_governance.core.disposition import auto_execute
from agentic_governance.core.envelope import build_envelope


@pytest.mark.asyncio
async def test_verify_audit_chain_detects_tampering(tmp_path):
    sink = JsonlAuditSink(tmp_path / "audit")
    envelope = build_envelope(
        server_url="http://db",
        tool_name="insertClaim",
        arguments={"amount": 42},
        employee_id="emp-1",
        extracted_receipt=None,
        session_claim_id="CLAIM-300",
        node_identity="intake",
    )
    await sink.append(envelope, auto_execute(reasons=("tool-allowed",)))
    await sink.append(envelope, auto_execute(reasons=("tool-allowed",)))

    lines = sink.path.read_text().splitlines()
    second = json.loads(lines[1])
    second["result"] = "tampered"
    lines[1] = json.dumps(second, sort_keys=True)
    sink.path.write_text("\n".join(lines) + "\n")

    result = verify_audit_chain(sink.path)
    assert result.ok is False
    assert result.event_count == 2
    assert any(issue.code == "entry-hash-mismatch" for issue in result.issues)


@pytest.mark.asyncio
async def test_reconstruct_claim_audit_returns_deterministic_claim_timeline(tmp_path):
    sink = JsonlAuditSink(tmp_path / "audit")
    envelope = build_envelope(
        server_url="http://db",
        tool_name="insertClaim",
        arguments={"amount": 42},
        employee_id="emp-1",
        extracted_receipt=None,
        session_claim_id="CLAIM-301",
        node_identity="intake",
    )
    await sink.append(envelope, auto_execute(reasons=("tool-allowed",)))
    oversight = build_custom_audit_event(
        event_type="oversight_governance",
        control_group="C",
        actor_type="governance",
        decision="require_human_review",
        result="escalated",
        reasons=["advisor-requested-review"],
        correlation_id="CLAIM-301",
        claim_id="CLAIM-301",
        db_claim_id=301,
        policy_version="0.14.0",
        agent_identity="governance_group_c",
        control_id="C",
        details={"contractId": "ESC-301"},
    )
    await sink.append_custom(oversight)
    other = build_custom_audit_event(
        event_type="reviewer_decision",
        control_group="C",
        actor_type="reviewer",
        decision="approve",
        result="approved",
        reasons=["approve"],
        correlation_id="CLAIM-999",
        claim_id="CLAIM-999",
        db_claim_id=999,
        policy_version="0.14.0",
        reviewer_identity={"employeeId": "EMP-9"},
    )
    await sink.append_custom(other)

    reconstruction = reconstruct_claim_audit(sink.path, claim_id="CLAIM-301")
    assert reconstruction.source_of_truth == CANONICAL_AUDIT_SOURCE
    assert reconstruction.claim_id == "CLAIM-301"
    assert reconstruction.event_count == 2
    assert [record.entry["eventType"] for record in reconstruction.events] == [
        "action_governance",
        "oversight_governance",
    ]


@pytest.mark.asyncio
async def test_failure_sidecar_records_are_loadable(tmp_path):
    sink = JsonlAuditSink(tmp_path / "audit")
    sink.record_failure_event(
        build_failure_audit_event(
            claim_id="CLAIM-302",
            correlation_id="CLAIM-302",
            db_claim_id=302,
            component="content_audit_append",
            error="disk full",
            policy_version="0.14.0",
        )
    )

    failures = load_failure_records(sink.path)
    assert len(failures) == 1
    assert failures[0].entry["eventType"] == "system_failure"
    assert failures[0].entry["details"]["component"] == "content_audit_append"

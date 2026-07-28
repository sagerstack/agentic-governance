from __future__ import annotations

import json

import pytest

from agentic_governance.adapters.jsonl_audit import (
    JsonlAuditSink,
    build_custom_audit_event,
)
from agentic_governance.core.disposition import auto_execute
from agentic_governance.core.envelope import build_envelope


@pytest.mark.asyncio
async def test_action_audit_entries_are_hash_chained(tmp_path):
    sink = JsonlAuditSink(tmp_path / "audit")
    envelope = build_envelope(
        server_url="http://db",
        tool_name="insertClaim",
        arguments={"amount": 42},
        employee_id="emp-1",
        extracted_receipt=None,
        session_claim_id="claim-1",
        node_identity="intake",
    )

    await sink.append(envelope, auto_execute(reasons=("tool-allowed",)))
    await sink.append(envelope, auto_execute(reasons=("tool-allowed",)))

    events = [json.loads(line) for line in sink.path.read_text().splitlines()]
    assert events[0]["eventType"] == "action_governance"
    assert events[0]["entryHash"]
    assert events[1]["prevEntryHash"] == events[0]["entryHash"]
    assert events[1]["entryHash"]


@pytest.mark.asyncio
async def test_custom_reviewer_event_is_hash_chained(tmp_path):
    sink = JsonlAuditSink(tmp_path / "audit")
    event = build_custom_audit_event(
        event_type="reviewer_decision",
        control_group="C",
        actor_type="reviewer",
        decision="approve",
        result="manually_approved",
        reasons=["approve"],
        correlation_id="CLAIM-200",
        claim_id="CLAIM-200",
        db_claim_id=200,
        policy_version="0.13.0",
        reviewer_identity={"employeeId": "EMP-1"},
        details={"contractId": "ESC-1"},
    )

    written = await sink.append_custom(event)
    assert written["eventType"] == "reviewer_decision"
    assert written["controlGroup"] == "C"
    assert written["reviewerIdentity"]["employeeId"] == "EMP-1"
    assert written["entryHash"]

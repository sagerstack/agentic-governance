from __future__ import annotations

import json
import re

import pytest

from agentic_governance.adapters.jsonl_audit import JsonlAuditSink
from agentic_governance.core.disposition import auto_execute
from agentic_governance.core.envelope import build_envelope


@pytest.mark.asyncio
async def test_separate_sink_initializations_write_to_distinct_run_files(tmp_path):
    audit_dir = tmp_path / "audit"
    first_sink = JsonlAuditSink(audit_dir)
    second_sink = JsonlAuditSink(audit_dir)
    envelope = build_envelope(
        server_url="http://db",
        tool_name="insertClaim",
        arguments={"amount": 42},
        employee_id="emp-1",
        extracted_receipt=None,
        session_claim_id="claim-1",
        node_identity="intake",
    )
    disposition = auto_execute(reasons=("tool-allowed",))

    await first_sink.append(envelope, disposition)
    await second_sink.append(envelope, disposition)
    await second_sink.append(envelope, disposition)

    filename_pattern = re.compile(r"audit-\d{8}T\d{6}Z-[0-9a-f]{6}\.jsonl")
    assert first_sink.path.parent == audit_dir
    assert second_sink.path.parent == audit_dir
    assert first_sink.path != second_sink.path
    assert filename_pattern.fullmatch(first_sink.path.name)
    assert filename_pattern.fullmatch(second_sink.path.name)
    assert set(audit_dir.glob("audit-*.jsonl")) == {first_sink.path, second_sink.path}

    first_events = [json.loads(line) for line in first_sink.path.read_text().splitlines()]
    second_events = [json.loads(line) for line in second_sink.path.read_text().splitlines()]
    assert len(first_events) == 1
    assert len(second_events) == 2
    assert first_events[0]["envelopeId"] == envelope.envelope_id
    assert all(event["envelopeId"] == envelope.envelope_id for event in second_events)


@pytest.mark.asyncio
async def test_explicit_jsonl_path_remains_an_exact_override(tmp_path):
    explicit_path = tmp_path / "custom-audit.jsonl"
    sink = JsonlAuditSink(explicit_path)
    envelope = build_envelope(
        server_url="http://db",
        tool_name="executeQuery",
        arguments={},
        employee_id=None,
        extracted_receipt=None,
        session_claim_id="claim-2",
        node_identity="fraud",
    )

    await sink.append(envelope, auto_execute())

    assert sink.path == explicit_path
    assert explicit_path.is_file()

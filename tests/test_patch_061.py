from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from agentic_governance.adapters.jsonl_audit import build_audit_entry
from agentic_governance.integrations.langgraph_mcp.governed_mcp_call import install


class MemoryAuditSink:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    async def append(self, envelope, disposition) -> None:
        self.entries.append(build_audit_entry(envelope, disposition))


@pytest.fixture
def policy_environment(monkeypatch):
    monkeypatch.setenv("RAG_MCP_URL", "http://rag")
    monkeypatch.setenv("DB_MCP_URL", "http://db")
    monkeypatch.setenv("CURRENCY_MCP_URL", "http://currency")


@pytest.mark.asyncio
async def test_audit_persists_only_opaque_reference_for_nested_declared_payload(
    policy_environment,
):
    nested_payload = {
        "employeeId": "employee-987",
        "status": "draft",
        "totalAmount": 0,
        "currency": "SGD",
        "merchant": "Contoso",
        "receiptDate": "2026-07-22",
        "receiptTotalAmount": 12.34,
        "lineItems": [
            {"description": "SurfacePen", "amount": 12.34, "taxable": True},
            {"description": "Cable", "amount": 0, "discounted": False},
            None,
        ],
        "intakeFindings": {
            "claimantName": "Ada Lovelace",
            "approved": True,
            "optional": None,
        },
    }
    audit = MemoryAuditSink()
    real = AsyncMock(return_value={"ok": True})
    governed = install(
        real_mcp_call_tool=real,
        employee_id_provider=lambda: "employee-987",
        extracted_receipt_provider=lambda: None,
        session_claim_id_provider=lambda: "session-private",
        node_identity_provider=lambda: "application",
        audit_sink=audit,
    )

    result = await governed("http://db", "insertClaim", nested_payload)

    assert result == {"ok": True}  # controls still use raw values in memory
    params_ref = audit.entries[0]["envelope"]["paramsRef"]
    assert params_ref == audit.entries[0]["evidenceRefs"]["paramsRef"]
    assert set(params_ref) == {"payloadSha256"}
    assert len(params_ref["payloadSha256"]) == 64
    serialized_ref = json.dumps(params_ref, sort_keys=True)
    for raw_value in (
        "employee-987",
        "draft",
        "SGD",
        "Contoso",
        "2026-07-22",
        "12.34",
        "SurfacePen",
        "Cable",
        "Ada Lovelace",
        "true",
        "false",
        "null",
    ):
        assert raw_value not in serialized_ref


@pytest.mark.asyncio
async def test_escalation_handle_preserves_all_ordered_disposition_reasons(
    policy_environment,
):
    receipt = {
        "fields": {
            "merchant": "Cafe",
            "date": "2026-07-22",
            "totalAmount": 600,
            "currency": "SGD",
        },
        "confidence": {
            "merchant": 0.5,
            "date": 0.5,
            "totalAmount": 0.5,
            "currency": 0.5,
        },
    }
    audit = MemoryAuditSink()
    real = AsyncMock()
    governed = install(
        real_mcp_call_tool=real,
        employee_id_provider=lambda: "emp-123",
        extracted_receipt_provider=lambda: receipt,
        session_claim_id_provider=lambda: "session-456",
        node_identity_provider=lambda: "intake",
        audit_sink=audit,
    )

    result = await governed(
        "http://db",
        "insertClaim",
        {"employeeId": "emp-123", "status": "pending", "totalAmount": 600},
    )

    expected_reasons = ["exposure-exceeded", "evidence-insufficient"]
    assert result["error"] == "exposure-exceeded"
    assert result["decision"] == "Escalate"
    assert result["reason"] == "exposure-exceeded"
    assert result["escalation"] == {
        "source": "governance",
        "reason": "exposure-exceeded",
    }
    assert result["reasons"] == expected_reasons
    assert audit.entries[0]["disposition"]["reasons"] == expected_reasons
    real.assert_not_awaited()


@pytest.mark.asyncio
async def test_opaque_payload_reference_is_canonical_and_change_sensitive(
    policy_environment,
):
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=AsyncMock(return_value={"ok": True}),
        employee_id_provider=lambda: "emp-123",
        extracted_receipt_provider=lambda: None,
        session_claim_id_provider=lambda: "session-456",
        node_identity_provider=lambda: "application",
        audit_sink=audit,
    )
    first = {
        "employeeId": "emp-123",
        "status": "draft",
        "totalAmount": 0,
        "currency": "SGD",
        "intakeFindings": {"b": [2, 1], "a": "same"},
    }
    reordered = {
        "intakeFindings": {"a": "same", "b": [2, 1]},
        "currency": "SGD",
        "totalAmount": 0,
        "status": "draft",
        "employeeId": "emp-123",
    }
    changed = {
        **first,
        "intakeFindings": {"b": [2, 1], "a": "changed"},
    }

    for payload in (first, reordered, changed):
        assert await governed("http://db", "insertClaim", payload) == {"ok": True}

    refs = [entry["envelope"]["paramsRef"]["payloadSha256"] for entry in audit.entries]
    assert refs[0] == refs[1]
    assert refs[2] != refs[0]


@pytest.mark.asyncio
async def test_trusted_receipt_content_is_referenced_but_never_persisted_raw(
    policy_environment,
):
    trusted_receipt = {
        "fields": {
            "merchant": "Private Medical Clinic",
            "patientName": "Grace Hopper",
            "totalAmount": 9182.73,
            "currency": "SGD",
        },
        "confidence": {"merchant": 0.99},
    }
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=AsyncMock(return_value={"ok": True}),
        employee_id_provider=lambda: "emp-123",
        extracted_receipt_provider=lambda: trusted_receipt,
        session_claim_id_provider=lambda: "session-456",
        node_identity_provider=lambda: "application",
        audit_sink=audit,
    )

    result = await governed(
        "http://db",
        "insertClaim",
        {
            "employeeId": "emp-123",
            "status": "draft",
            "totalAmount": 0,
            "currency": "SGD",
        },
    )

    assert result == {"ok": True}
    serialized = json.dumps(audit.entries[0], sort_keys=True)
    assert "Private Medical Clinic" not in serialized
    assert "Grace Hopper" not in serialized
    assert "9182.73" not in serialized
    assert audit.entries[0]["envelope"]["contextMetadata"]["extractedReceiptRef"]


@pytest.mark.asyncio
async def test_a2_integrity_decision_is_unchanged_with_opaque_audit_payload(
    policy_environment,
):
    audit = MemoryAuditSink()
    real = AsyncMock()
    governed = install(
        real_mcp_call_tool=real,
        employee_id_provider=lambda: "trusted-employee",
        extracted_receipt_provider=lambda: None,
        session_claim_id_provider=lambda: "session-456",
        node_identity_provider=lambda: "intake",
        audit_sink=audit,
    )

    result = await governed(
        "http://db",
        "insertClaim",
        {
            "employeeId": "tampered-employee",
            "status": "pending",
            "totalAmount": 100,
        },
    )

    assert result == {"error": "integrity-mismatch", "decision": "Deny"}
    assert set(audit.entries[0]["envelope"]["paramsRef"]) == {"payloadSha256"}
    real.assert_not_awaited()


@pytest.mark.asyncio
async def test_a7_keeps_threshold_and_outcome_but_not_raw_monetary_value(
    policy_environment,
):
    receipt = {
        "fields": {
            "merchant": "Cafe",
            "date": "2026-07-22",
            "totalAmount": 612.34,
            "currency": "SGD",
        },
        "confidence": {
            "merchant": 0.9,
            "date": 0.9,
            "totalAmount": 0.9,
            "currency": 0.9,
        },
    }
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=AsyncMock(),
        employee_id_provider=lambda: "emp-123",
        extracted_receipt_provider=lambda: receipt,
        session_claim_id_provider=lambda: "session-456",
        node_identity_provider=lambda: "intake",
        audit_sink=audit,
    )

    result = await governed(
        "http://db",
        "insertClaim",
        {"employeeId": "emp-123", "status": "pending", "totalAmount": 612.34},
    )

    assert result["decision"] == "Escalate"
    a7 = next(
        control
        for control in audit.entries[0]["disposition"]["firedControls"]
        if control["controlId"] == "A7"
    )
    assert a7["threshold"] == "500.00"
    assert a7["observedValue"] == "per-action-ceiling-exceeded"
    assert "612.34" not in json.dumps(audit.entries[0], sort_keys=True)


@pytest.mark.asyncio
async def test_a9_keeps_threshold_and_outcome_but_not_raw_confidence(
    policy_environment,
):
    raw_confidence = 0.612345
    receipt = {
        "fields": {
            "merchant": "Cafe",
            "date": "2026-07-22",
            "totalAmount": 100,
            "currency": "SGD",
        },
        "confidence": {
            "merchant": raw_confidence,
            "date": raw_confidence,
            "totalAmount": raw_confidence,
            "currency": raw_confidence,
        },
    }
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=AsyncMock(),
        employee_id_provider=lambda: "emp-123",
        extracted_receipt_provider=lambda: receipt,
        session_claim_id_provider=lambda: "session-456",
        node_identity_provider=lambda: "intake",
        audit_sink=audit,
    )

    result = await governed(
        "http://db",
        "insertClaim",
        {"employeeId": "emp-123", "status": "pending", "totalAmount": 100},
    )

    assert result["decision"] == "Escalate"
    assert result["reason"] == "evidence-insufficient"
    a9 = next(
        control
        for control in audit.entries[0]["disposition"]["firedControls"]
        if control["controlId"] == "A9"
    )
    assert a9["threshold"] == "0.70"
    assert a9["observedValue"] == "confidence-below-threshold"
    assert str(raw_confidence) not in json.dumps(audit.entries[0], sort_keys=True)


@pytest.mark.asyncio
async def test_single_reason_escalation_keeps_legacy_fields_and_canonical_list(
    policy_environment,
):
    receipt = {
        "fields": {
            "merchant": "Cafe",
            "date": "2026-07-22",
            "totalAmount": 600,
            "currency": "SGD",
        },
        "confidence": {
            "merchant": 0.9,
            "date": 0.9,
            "totalAmount": 0.9,
            "currency": 0.9,
        },
    }
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=AsyncMock(),
        employee_id_provider=lambda: "emp-123",
        extracted_receipt_provider=lambda: receipt,
        session_claim_id_provider=lambda: "session-456",
        node_identity_provider=lambda: "intake",
        audit_sink=audit,
    )

    handle = await governed(
        "http://db",
        "insertClaim",
        {"employeeId": "emp-123", "status": "pending", "totalAmount": 600},
    )

    assert handle["error"] == handle["reason"] == "exposure-exceeded"
    assert handle["decision"] == "Escalate"
    assert handle["escalation"] == {
        "source": "governance",
        "reason": "exposure-exceeded",
    }
    assert handle["reasons"] == ["exposure-exceeded"]
    assert handle["reasons"] == audit.entries[0]["disposition"]["reasons"]

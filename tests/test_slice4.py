from __future__ import annotations

import asyncio
from importlib.resources import files
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


def _receipt(score=0.9):
    return {
        "fields": {
            "merchant": "Cafe",
            "date": "2026-07-22",
            "totalAmount": 100,
            "currency": "SGD",
        },
        "confidence": {
            "merchant": score,
            "date": score,
            "totalAmount": score,
            "currency": score,
        },
    }


def _providers(*, identity="intake", employee="emp-123", session="session-456", receipt=None):
    return {
        "employee_id_provider": lambda: employee,
        "extracted_receipt_provider": lambda: _receipt() if receipt is None else receipt,
        "session_claim_id_provider": lambda: session,
        "node_identity_provider": lambda: identity,
        "db_claim_id_provider": lambda: None,
    }


def _claim(amount):
    return {"employeeId": "emp-123", "status": "pending", "totalAmount": amount}


def _escalation(reason):
    return {
        "error": reason,
        "decision": "Escalate",
        "reason": reason,
        "reasons": [reason],
        "escalation": {"source": "governance", "reason": reason},
    }


def _override_policy(tmp_path, mutate):
    default_path = files("agentic_governance.policy").joinpath("default_policy.json")
    document = json.loads(default_path.read_text(encoding="utf-8"))
    mutate(document)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_below_all_thresholds_auto_executes(policy_environment):
    real = AsyncMock(return_value={"ok": True})
    audit = MemoryAuditSink()
    governed = install(real_mcp_call_tool=real, audit_sink=audit, **_providers())

    result = await governed("http://db", "insertClaim", _claim(100))

    assert result == {"ok": True}
    real.assert_awaited_once()
    disposition = audit.entries[0]["disposition"]
    assert disposition["decision"] == "Auto-Execute"
    results = {control["controlId"]: control["result"] for control in disposition["firedControls"]}
    assert results["A7"] == results["A8"] == results["A9"] == "allowed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("amount", "decision", "outcome"),
    [
        (500.01, "Escalate", "per-action-ceiling-exceeded"),
        (5000.01, "Deny", "hard-cap-exceeded"),
        (None, "Deny", "missing-or-invalid-value"),
    ],
)
async def test_per_action_exposure_dispositions(
    policy_environment, monkeypatch, amount, decision, outcome
):
    if amount is None:
        monkeypatch.setenv("AGENTIC_GOV_ENABLE_SCHEMA", "off")
    real = AsyncMock()
    audit = MemoryAuditSink()
    governed = install(real_mcp_call_tool=real, audit_sink=audit, **_providers())
    arguments = {"employeeId": "emp-123", "status": "pending"}
    if amount is not None:
        arguments["totalAmount"] = amount

    result = await governed("http://db", "insertClaim", arguments)

    assert result == (
        _escalation("exposure-exceeded")
        if decision == "Escalate"
        else {"error": "exposure-exceeded", "decision": "Deny"}
    )
    real.assert_not_awaited()
    state = next(s for s in audit.entries[0]["disposition"]["controlStates"] if s["controlId"] == "A7")
    assert state["outcome"] == outcome


@pytest.mark.asyncio
async def test_aggregate_exposure_escalates_and_does_not_reserve_blocked_action(
    policy_environment, monkeypatch
):
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_RATE", "off")
    real = AsyncMock(return_value={"ok": True})
    audit = MemoryAuditSink()
    governed = install(real_mcp_call_tool=real, audit_sink=audit, **_providers())

    results = [
        await governed("http://db", "insertClaim", _claim(450))
        for _ in range(6)
    ]

    assert results[:4] == [{"ok": True}] * 4
    assert results[4:] == [
        _escalation("exposure-exceeded"),
        _escalation("exposure-exceeded"),
    ]
    assert real.await_count == 4
    aggregate_states = [
        next(s for s in entry["disposition"]["controlStates"] if s["controlId"] == "A7")
        for entry in audit.entries
    ]
    assert aggregate_states[-1]["outcome"] == "aggregate-limit-exceeded"


@pytest.mark.asyncio
async def test_sixth_attempt_is_rate_denied(policy_environment):
    real = AsyncMock(return_value={"ok": True})
    audit = MemoryAuditSink()
    governed = install(real_mcp_call_tool=real, audit_sink=audit, **_providers())

    results = [await governed("http://db", "insertClaim", _claim(1)) for _ in range(6)]

    assert results[:5] == [{"ok": True}] * 5
    assert results[5] == {"error": "rate-exceeded", "decision": "Deny"}
    assert real.await_count == 5
    state = next(s for s in audit.entries[-1]["disposition"]["controlStates"] if s["controlId"] == "A8")
    assert state["outcome"] == "rate-limit-exceeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt", [_receipt(0.69), {}, {"fields": {}, "confidence": {}}])
async def test_weak_or_missing_evidence_escalates(policy_environment, receipt):
    real = AsyncMock()
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=audit,
        **_providers(receipt=receipt),
    )

    result = await governed("http://db", "insertClaim", _claim(100))

    assert result == _escalation("evidence-insufficient")
    real.assert_not_awaited()
    state = next(s for s in audit.entries[0]["disposition"]["controlStates"] if s["controlId"] == "A9")
    assert state["outcome"] in {"missing-evidence", "confidence-below-threshold"}


@pytest.mark.asyncio
async def test_application_draft_is_excluded_from_quantitative_controls(policy_environment):
    real = AsyncMock(return_value={"draft": True})
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=audit,
        **_providers(identity="application", receipt={}),
    )
    arguments = {
        "employeeId": "emp-123",
        "status": "draft",
        "totalAmount": 0,
        "currency": "SGD",
    }

    assert await governed("http://db", "insertClaim", arguments) == {"draft": True}
    states = {s["controlId"]: s["outcome"] for s in audit.entries[0]["disposition"]["controlStates"]}
    assert states["A7"] == states["A8"] == states["A9"] == "not-applicable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("control", "mode", "arguments", "receipt"),
    [
        ("EXPOSURE", "observe", _claim(600), _receipt()),
        ("EXPOSURE", "off", _claim(600), _receipt()),
        ("EVIDENCE", "observe", _claim(10), {}),
        ("EVIDENCE", "off", _claim(10), {}),
    ],
)
async def test_exposure_and_evidence_non_enforcing_modes_dispatch(
    policy_environment, monkeypatch, control, mode, arguments, receipt
):
    monkeypatch.setenv(f"AGENTIC_GOV_ENABLE_{control}", mode)
    real = AsyncMock(return_value={"ok": True})
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=audit,
        **_providers(receipt=receipt),
    )

    assert await governed("http://db", "insertClaim", arguments) == {"ok": True}
    state = next(
        s
        for s in audit.entries[0]["disposition"]["controlStates"]
        if s["controlId"] == ("A7" if control == "EXPOSURE" else "A9")
    )
    assert state["mode"] == mode
    assert state["outcome"] == "skipped-disabled" if mode == "off" else state["outcome"].startswith("would-")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["observe", "off"])
async def test_rate_non_enforcing_modes_allow_burst(policy_environment, monkeypatch, mode):
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_RATE", mode)
    real = AsyncMock(return_value={"ok": True})
    audit = MemoryAuditSink()
    governed = install(real_mcp_call_tool=real, audit_sink=audit, **_providers())

    results = [await governed("http://db", "insertClaim", _claim(1)) for _ in range(6)]

    assert results == [{"ok": True}] * 6
    last_state = next(s for s in audit.entries[-1]["disposition"]["controlStates"] if s["controlId"] == "A8")
    assert last_state["mode"] == mode
    assert last_state["outcome"] == "skipped-disabled" if mode == "off" else last_state["outcome"] == "would-deny:rate-exceeded"


@pytest.mark.asyncio
async def test_exposure_threshold_and_disposition_are_configurable(
    policy_environment, monkeypatch, tmp_path
):
    def mutate(document):
        document["exposure"][0]["perAction"]["escalateAbove"] = "50"
        document["exposure"][0]["perAction"]["ceilingDisposition"] = "Deny"

    monkeypatch.setenv("AGENTIC_GOV_POLICY_FILE", str(_override_policy(tmp_path, mutate)))
    governed = install(
        real_mcp_call_tool=AsyncMock(),
        audit_sink=MemoryAuditSink(),
        **_providers(),
    )

    assert await governed("http://db", "insertClaim", _claim(60)) == {
        "error": "exposure-exceeded",
        "decision": "Deny",
    }


@pytest.mark.asyncio
async def test_evidence_threshold_is_configurable(
    policy_environment, monkeypatch, tmp_path
):
    def mutate(document):
        document["evidence"][0]["minimumConfidence"] = "0.95"

    monkeypatch.setenv("AGENTIC_GOV_POLICY_FILE", str(_override_policy(tmp_path, mutate)))
    governed = install(
        real_mcp_call_tool=AsyncMock(),
        audit_sink=MemoryAuditSink(),
        **_providers(receipt=_receipt(0.90)),
    )

    assert await governed("http://db", "insertClaim", _claim(10)) == _escalation(
        "evidence-insufficient"
    )


@pytest.mark.asyncio
async def test_rate_disposition_is_configurable_to_escalate(
    policy_environment, monkeypatch, tmp_path
):
    def mutate(document):
        document["rate"][0]["maxAttempts"] = 1
        document["rate"][0]["exceededDisposition"] = "Escalate"

    monkeypatch.setenv("AGENTIC_GOV_POLICY_FILE", str(_override_policy(tmp_path, mutate)))
    real = AsyncMock(return_value={"ok": True})
    governed = install(real_mcp_call_tool=real, audit_sink=MemoryAuditSink(), **_providers())

    assert await governed("http://db", "insertClaim", _claim(1)) == {"ok": True}
    assert await governed("http://db", "insertClaim", _claim(1)) == _escalation(
        "rate-exceeded"
    )
    assert real.await_count == 1


@pytest.mark.asyncio
async def test_aggregate_exposure_reservation_is_atomic_under_concurrency(
    policy_environment, monkeypatch, tmp_path
):
    def mutate(document):
        document["exposure"][0]["aggregate"]["limit"] = "100"

    monkeypatch.setenv("AGENTIC_GOV_POLICY_FILE", str(_override_policy(tmp_path, mutate)))
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_RATE", "off")
    real = AsyncMock(return_value={"ok": True})
    governed = install(real_mcp_call_tool=real, audit_sink=MemoryAuditSink(), **_providers())

    results = await asyncio.gather(
        *(governed("http://db", "insertClaim", _claim(30)) for _ in range(5))
    )

    assert sum(result == {"ok": True} for result in results) == 3
    assert sum(
        result == _escalation("exposure-exceeded")
        for result in results
    ) == 2
    assert real.await_count == 3


@pytest.mark.asyncio
async def test_rate_counter_is_atomic_under_concurrency(policy_environment):
    real = AsyncMock(return_value={"ok": True})
    governed = install(real_mcp_call_tool=real, audit_sink=MemoryAuditSink(), **_providers())

    results = await asyncio.gather(
        *(governed("http://db", "insertClaim", _claim(1)) for _ in range(10))
    )

    assert sum(result == {"ok": True} for result in results) == 5
    assert sum(result == {"error": "rate-exceeded", "decision": "Deny"} for result in results) == 5
    assert real.await_count == 5

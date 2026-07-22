from __future__ import annotations

from importlib.resources import files
import json
from unittest.mock import AsyncMock

import pytest

from agentic_governance.adapters.jsonl_audit import build_audit_entry
from agentic_governance.adapters.policy_loader import PolicyConfigError
from agentic_governance.integrations.langgraph_mcp.governed_mcp_call import install


class MemoryAuditSink:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    async def append(self, envelope, disposition) -> None:
        self.entries.append(build_audit_entry(envelope, disposition))


class RaisingIdentityRegistry:
    async def verify(self, identity):
        raise RuntimeError("registry unavailable")


def _set_servers(monkeypatch):
    monkeypatch.setenv("RAG_MCP_URL", "http://rag")
    monkeypatch.setenv("DB_MCP_URL", "http://db")
    monkeypatch.setenv("CURRENCY_MCP_URL", "http://currency")


def _providers(identity, *, employee_id="emp-123", db_claim_id=None):
    return {
        "employee_id_provider": lambda: employee_id,
        "extracted_receipt_provider": lambda: {"fields": {"merchant": "Cafe"}},
        "session_claim_id_provider": lambda: "session-456",
        "node_identity_provider": lambda: identity,
        "db_claim_id_provider": lambda: db_claim_id,
    }


def _draft(**overrides):
    arguments = {
        "employeeId": "emp-123",
        "status": "draft",
        "totalAmount": 0,
        "currency": "SGD",
    }
    arguments.update(overrides)
    return arguments


@pytest.mark.asyncio
async def test_matching_draft_and_final_insert_integrity_execute(monkeypatch):
    _set_servers(monkeypatch)
    for identity, arguments in (
        ("application", _draft()),
        ("intake", {"employeeId": "emp-123", "totalAmount": 999}),
    ):
        real = AsyncMock(return_value={"ok": True})
        audit = MemoryAuditSink()
        governed = install(real_mcp_call_tool=real, audit_sink=audit, **_providers(identity))

        assert await governed("http://db", "insertClaim", arguments) == {"ok": True}
        real.assert_awaited_once()
        disposition = audit.entries[0]["disposition"]
        assert disposition["decision"] == "Auto-Execute"
        assert {c["controlId"]: c["result"] for c in disposition["firedControls"]}["A2"] == "allowed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        _draft(employeeId="other"),
        _draft(status="pending"),
        _draft(totalAmount="0.01"),
        _draft(currency="USD"),
        {"status": "draft", "totalAmount": 0, "currency": "SGD"},
    ],
)
async def test_draft_integrity_mismatch_denies(monkeypatch, arguments):
    _set_servers(monkeypatch)
    real = AsyncMock()
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=audit,
        **_providers("application"),
    )

    result = await governed("http://db", "insertClaim", arguments)

    assert result == {"error": "integrity-mismatch", "decision": "Deny"}
    real.assert_not_awaited()
    disposition = audit.entries[0]["disposition"]
    assert disposition["reasons"] == ["integrity-mismatch"]
    assert {c["controlId"]: c["result"] for c in disposition["firedControls"]}["A2"] == "denied"


@pytest.mark.asyncio
async def test_intake_employee_mismatch_denies(monkeypatch):
    _set_servers(monkeypatch)
    real = AsyncMock()
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=MemoryAuditSink(),
        **_providers("intake"),
    )

    result = await governed("http://db", "insertClaim", {"employeeId": "attacker"})

    assert result == {"error": "integrity-mismatch", "decision": "Deny"}
    real.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("declared", "trusted", "allowed"),
    [(17, 17, True), ("17", 17, True), (17.5, 17, False), (18, 17, False), (17, None, False)],
)
async def test_update_status_binds_integer_db_claim_id(monkeypatch, declared, trusted, allowed):
    _set_servers(monkeypatch)
    real = AsyncMock(return_value={"ok": True})
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=MemoryAuditSink(),
        **_providers("advisor", db_claim_id=trusted),
    )

    result = await governed("http://db", "updateClaimStatus", {"claimId": declared})

    if allowed:
        assert result == {"ok": True}
        real.assert_awaited_once()
    else:
        assert result == {"error": "integrity-mismatch", "decision": "Deny"}
        real.assert_not_awaited()


@pytest.mark.asyncio
async def test_simulate_tamper_forces_configured_check_to_mismatch(monkeypatch):
    _set_servers(monkeypatch)
    monkeypatch.setenv("AGENTIC_GOV_SIMULATE_TAMPER", " insertClaim:employeeId ")
    real = AsyncMock()
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=MemoryAuditSink(),
        **_providers("intake"),
    )

    result = await governed("http://db", "insertClaim", {"employeeId": "emp-123"})

    assert result == {"error": "integrity-mismatch", "decision": "Deny"}
    real.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["off", "observe"])
async def test_integrity_non_enforcing_modes_do_not_block(monkeypatch, mode):
    _set_servers(monkeypatch)
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_INTEGRITY", mode)
    real = AsyncMock(return_value={"ok": True})
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=audit,
        **_providers("application"),
    )

    result = await governed("http://db", "insertClaim", _draft(employeeId="wrong"))

    assert result == {"ok": True}
    real.assert_awaited_once()
    disposition = audit.entries[0]["disposition"]
    state = next(s for s in disposition["controlStates"] if s["controlId"] == "A2")
    assert state["mode"] == mode
    assert state["outcome"] == (
        "skipped-disabled" if mode == "off" else "would-deny:integrity-mismatch"
    )
    if mode == "observe":
        assert "would-deny:integrity-mismatch" in disposition["reasons"]


@pytest.mark.asyncio
async def test_allowlist_observe_and_off_continue_to_other_controls(monkeypatch):
    _set_servers(monkeypatch)
    monkeypatch.setenv("AGENTIC_GOV_DENY_TOOLS", "insertClaim")
    for mode in ("observe", "off"):
        monkeypatch.setenv("AGENTIC_GOV_ENABLE_ALLOWLIST", mode)
        real = AsyncMock(return_value={"ok": mode})
        audit = MemoryAuditSink()
        governed = install(
            real_mcp_call_tool=real,
            audit_sink=audit,
            **_providers("intake"),
        )

        assert await governed("http://db", "insertClaim", {"employeeId": "emp-123"}) == {"ok": mode}
        state = next(s for s in audit.entries[0]["disposition"]["controlStates"] if s["controlId"] == "A5")
        assert state["mode"] == mode
        assert any(s["controlId"] == "A4" and s["outcome"] == "allowed" for s in audit.entries[0]["disposition"]["controlStates"])


@pytest.mark.asyncio
async def test_identity_and_mandate_can_be_disabled_independently(monkeypatch):
    _set_servers(monkeypatch)
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_IDENTITY", "off")
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_MANDATE", "off")
    real = AsyncMock(return_value={"ok": True})
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=audit,
        **_providers("attacker"),
    )

    assert await governed("http://db", "executeQuery", {}) == {"ok": True}
    states = {s["controlId"]: s for s in audit.entries[0]["disposition"]["controlStates"]}
    assert states["A3"]["outcome"] == "skipped-disabled"
    assert states["A4"]["outcome"] == "skipped-disabled"


@pytest.mark.asyncio
async def test_identity_observe_records_shadow_without_blocking(monkeypatch):
    _set_servers(monkeypatch)
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_IDENTITY", "observe")
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_MANDATE", "off")
    real = AsyncMock(return_value={"ok": True})
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=audit,
        **_providers("attacker"),
    )

    assert await governed("http://db", "executeQuery", {}) == {"ok": True}
    assert "would-deny:unverified-identity" in audit.entries[0]["disposition"]["reasons"]
    state = next(s for s in audit.entries[0]["disposition"]["controlStates"] if s["controlId"] == "A3")
    assert state == {
        "controlId": "A3",
        "mode": "observe",
        "outcome": "would-deny:unverified-identity",
    }


@pytest.mark.asyncio
async def test_mandate_observe_retains_shadow_finding_and_dispatches(monkeypatch):
    _set_servers(monkeypatch)
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_MANDATE", "observe")
    real = AsyncMock(return_value={"ok": True})
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=audit,
        **_providers("advisor"),
    )

    assert await governed("http://db", "insertClaim", {"employeeId": "emp-123"}) == {"ok": True}
    assert "would-deny:mandate-violation" in audit.entries[0]["disposition"]["reasons"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["observe", "off"])
async def test_fail_closed_floor_non_enforcing_mode_dispatches_high_impact(monkeypatch, mode):
    _set_servers(monkeypatch)
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_FAIL_CLOSED", mode)
    real = AsyncMock(return_value={"ok": True})
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=audit,
        identity_registry=RaisingIdentityRegistry(),
        **_providers("intake"),
    )

    assert await governed("http://db", "insertClaim", {"employeeId": "emp-123"}) == {"ok": True}
    state = audit.entries[0]["disposition"]["controlStates"][0]
    assert state == {
        "controlId": "A12",
        "mode": mode,
        "outcome": (
            "would-deny:governance-unavailable"
            if mode == "observe"
            else "skipped-disabled"
        ),
    }


@pytest.mark.asyncio
async def test_invalid_control_mode_warns_and_defaults_to_enforce(monkeypatch, caplog):
    _set_servers(monkeypatch)
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_INTEGRITY", "invalid-value")
    governed = install(
        real_mcp_call_tool=AsyncMock(),
        audit_sink=MemoryAuditSink(),
        **_providers("application"),
    )

    result = await governed("http://db", "insertClaim", _draft(employeeId="wrong"))

    assert result == {"error": "integrity-mismatch", "decision": "Deny"}
    assert "defaulting safely to enforce" in caplog.text


@pytest.mark.asyncio
async def test_raw_integrity_context_is_never_serialized_to_audit(monkeypatch):
    _set_servers(monkeypatch)
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=AsyncMock(return_value={"ok": True}),
        audit_sink=audit,
        employee_id_provider=lambda: "employee-sensitive-123",
        extracted_receipt_provider=lambda: {"fields": {"merchant": "Secret Merchant"}},
        session_claim_id_provider=lambda: "session-sensitive-456",
        node_identity_provider=lambda: "intake",
    )

    await governed(
        "http://db",
        "insertClaim",
        {"employeeId": "employee-sensitive-123"},
    )

    serialized = json.dumps(audit.entries[0])
    assert "declared_params" not in serialized
    assert "trusted_context" not in serialized
    assert "employee-sensitive-123" not in serialized
    assert "Secret Merchant" not in serialized


@pytest.mark.asyncio
async def test_full_policy_file_override_changes_behavior(monkeypatch, tmp_path):
    _set_servers(monkeypatch)
    default_path = files("agentic_governance.policy").joinpath("default_policy.json")
    document = json.loads(default_path.read_text(encoding="utf-8"))
    document["allowlist"][1]["tools"].append("customRead")
    document["mandates"]["application"][0]["tools"].append("customRead")
    override = tmp_path / "policy.json"
    override.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setenv("AGENTIC_GOV_POLICY_FILE", str(override))
    real = AsyncMock(return_value={"custom": True})
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=MemoryAuditSink(),
        **_providers("application"),
    )

    assert await governed("http://db", "customRead", {}) == {"custom": True}
    real.assert_awaited_once()


def test_malformed_policy_override_fails_initialization(monkeypatch, tmp_path):
    _set_servers(monkeypatch)
    override = tmp_path / "bad.json"
    override.write_text('{"schemaVersion": 1}', encoding="utf-8")
    monkeypatch.setenv("AGENTIC_GOV_POLICY_FILE", str(override))

    with pytest.raises(PolicyConfigError):
        install(real_mcp_call_tool=AsyncMock(), **_providers("application"))

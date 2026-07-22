from __future__ import annotations

from importlib.resources import files
import inspect
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import agentic_governance.core as core_package
from agentic_governance.adapters.jsonl_audit import build_audit_entry
from agentic_governance.core.schema_validation import SchemaValidator
from agentic_governance.integrations.langgraph_mcp.governed_mcp_call import install


class MemoryAuditSink:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    async def append(self, envelope, disposition) -> None:
        self.entries.append(build_audit_entry(envelope, disposition))


class RaisingIdentityRegistry:
    async def verify(self, identity):
        raise RuntimeError("registry unavailable")


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


def _providers(*, identity="application", receipt=None, db_claim_id=None):
    return {
        "employee_id_provider": lambda: "emp-123",
        "extracted_receipt_provider": lambda: _receipt() if receipt is None else receipt,
        "session_claim_id_provider": lambda: "session-456",
        "node_identity_provider": lambda: identity,
        "db_claim_id_provider": lambda: db_claim_id,
    }


def _escalation(reason):
    return {
        "error": reason,
        "decision": "Escalate",
        "reason": reason,
        "escalation": {"source": "governance", "reason": reason},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("server", ["http://rogue", "http://email"])
async def test_unregistered_server_is_denied_before_other_controls(
    policy_environment, server
):
    real = AsyncMock()
    audit = MemoryAuditSink()
    governed = install(real_mcp_call_tool=real, audit_sink=audit, **_providers())

    result = await governed(server, "executeQuery", {"query": "SELECT 1"})

    assert result == {"error": "untrusted-server", "decision": "Deny"}
    real.assert_not_awaited()
    disposition = audit.entries[0]["disposition"]
    assert disposition["reasons"] == ["untrusted-server"]
    assert disposition["controlStates"] == [
        {"controlId": "A10", "mode": "enforce", "outcome": "untrusted-server"}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("server", "tool", "arguments"),
    [
        ("http://rag", "searchPolicies", {}),
        ("http://rag", "searchPolicies", {"query": "meals", "limit": True}),
        ("http://currency", "convertCurrency", {"amount": "10", "fromCurrency": "USD"}),
        ("http://db", "getClaimSchema", {"extra": 1}),
        ("http://db", "executeQuery", {"query": 123}),
        ("http://db", "insertAuditLog", {"claimId": True, "action": "x", "newValue": "{}", "actor": "a"}),
        ("http://db", "updateClaimStatus", {"claimId": 1, "newStatus": "escalated"}),
        ("http://db", "insertClaim", {"employeeId": "emp-123", "status": "pending"}),
        ("http://db", "insertClaim", {"employeeId": "emp-123", "status": "pending", "totalAmount": 1, "extra": 2}),
    ],
)
async def test_malformed_known_tool_arguments_are_schema_denied(
    policy_environment, server, tool, arguments
):
    real = AsyncMock()
    audit = MemoryAuditSink()
    governed = install(real_mcp_call_tool=real, audit_sink=audit, **_providers())

    result = await governed(server, tool, arguments)

    assert result == {"error": "schema-invalid", "decision": "Deny"}
    real.assert_not_awaited()
    state = audit.entries[0]["disposition"]["controlStates"][0]
    assert state == {"controlId": "A10", "mode": "enforce", "outcome": "schema-invalid"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("identity", "server", "tool", "arguments", "db_claim_id"),
    [
        ("compliance", "http://rag", "searchPolicies", {"query": "meal", "limit": 8}, None),
        ("intake", "http://currency", "convertCurrency", {"amount": 10.0, "fromCurrency": "USD", "toCurrency": "SGD"}, None),
        ("intake", "http://db", "getClaimSchema", {}, None),
        ("application", "http://db", "executeQuery", {"query": "SELECT 1"}, None),
        ("application", "http://db", "insertAuditLog", {"claimId": 1, "action": "x", "newValue": "{}", "actor": "app"}, None),
        ("advisor", "http://db", "updateClaimStatus", {"claimId": 7, "newStatus": "escalated", "actor": "advisor", "advisorFindings": {}}, 7),
        ("application", "http://db", "insertClaim", {"employeeId": "emp-123", "status": "draft", "totalAmount": 0, "currency": "SGD"}, None),
    ],
)
async def test_every_configured_wire_schema_accepts_legitimate_shape(
    policy_environment, identity, server, tool, arguments, db_claim_id
):
    real = AsyncMock(return_value={"ok": True})
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=audit,
        **_providers(identity=identity, db_claim_id=db_claim_id),
    )

    assert await governed(server, tool, arguments) == {"ok": True}
    real.assert_awaited_once()
    a10 = next(s for s in audit.entries[0]["disposition"]["controlStates"] if s["controlId"] == "A10")
    assert a10 == {"controlId": "A10", "mode": "enforce", "outcome": "allowed"}


@pytest.mark.asyncio
async def test_unknown_tool_on_trusted_server_defers_to_a5(policy_environment):
    real = AsyncMock()
    audit = MemoryAuditSink()
    governed = install(real_mcp_call_tool=real, audit_sink=audit, **_providers())

    result = await governed("http://db", "fabricatedTool", {})

    assert result == {"error": "tool-not-allowed", "decision": "Deny"}
    states = audit.entries[0]["disposition"]["controlStates"]
    assert states[0] == {"controlId": "A10", "mode": "enforce", "outcome": "not-applicable"}
    assert states[1] == {"controlId": "A5", "mode": "enforce", "outcome": "denied"}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["observe", "off"])
async def test_schema_non_enforcing_modes_allow_malformed_payload(
    policy_environment, monkeypatch, mode
):
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_SCHEMA", mode)
    real = AsyncMock(return_value={"ok": True})
    audit = MemoryAuditSink()
    governed = install(real_mcp_call_tool=real, audit_sink=audit, **_providers())

    result = await governed("http://db", "executeQuery", {"query": 123})

    assert result == {"ok": True}
    real.assert_awaited_once()
    state = audit.entries[0]["disposition"]["controlStates"][0]
    assert state["mode"] == mode
    assert state["outcome"] == (
        "would-deny:schema-invalid" if mode == "observe" else "skipped-disabled"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["observe", "off"])
async def test_trusted_server_non_enforcing_modes_allow_rogue_endpoint(
    policy_environment, monkeypatch, mode
):
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_SCHEMA", mode)
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_ALLOWLIST", "off")
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_MANDATE", "off")
    real = AsyncMock(return_value={"ok": True})
    audit = MemoryAuditSink()
    governed = install(real_mcp_call_tool=real, audit_sink=audit, **_providers())

    assert await governed(
        "http://rogue", "executeQuery", {"query": "SELECT 1"}
    ) == {"ok": True}
    real.assert_awaited_once()
    state = audit.entries[0]["disposition"]["controlStates"][0]
    assert state["outcome"] == (
        "would-deny:untrusted-server" if mode == "observe" else "skipped-disabled"
    )


@pytest.mark.asyncio
async def test_schema_override_changes_validation_without_code(
    policy_environment, monkeypatch, tmp_path
):
    default = files("agentic_governance.policy").joinpath("default_policy.json")
    document = json.loads(default.read_text(encoding="utf-8"))
    execute_schema = next(item for item in document["schemas"] if item["tool"] == "executeQuery")
    execute_schema["schema"]["properties"]["trace"] = {"type": "string"}
    override = tmp_path / "policy.json"
    override.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setenv("AGENTIC_GOV_POLICY_FILE", str(override))
    real = AsyncMock(return_value={"ok": True})
    governed = install(real_mcp_call_tool=real, audit_sink=MemoryAuditSink(), **_providers())

    assert await governed(
        "http://db", "executeQuery", {"query": "SELECT 1", "trace": "demo"}
    ) == {"ok": True}


@pytest.mark.asyncio
async def test_escalation_handle_carries_stable_governance_source_and_reason(
    policy_environment
):
    real = AsyncMock()
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=audit,
        **_providers(identity="intake"),
    )

    result = await governed(
        "http://db",
        "insertClaim",
        {"employeeId": "emp-123", "status": "pending", "totalAmount": 600},
    )

    assert result == _escalation("exposure-exceeded")
    assert audit.entries[0]["disposition"]["escalation"] == {
        "source": "governance",
        "reason": "exposure-exceeded",
    }
    real.assert_not_awaited()


@pytest.mark.asyncio
async def test_a6_suite_exercises_all_four_dispositions(policy_environment):
    decisions = set()

    # Auto-Execute
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=AsyncMock(return_value={"ok": True}),
        audit_sink=audit,
        **_providers(),
    )
    await governed("http://db", "executeQuery", {"query": "SELECT 1"})
    decisions.add(audit.entries[-1]["disposition"]["decision"])

    # Deny
    audit = MemoryAuditSink()
    governed = install(real_mcp_call_tool=AsyncMock(), audit_sink=audit, **_providers())
    await governed("http://rogue", "executeQuery", {"query": "SELECT 1"})
    decisions.add(audit.entries[-1]["disposition"]["decision"])

    # Escalate
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=AsyncMock(),
        audit_sink=audit,
        **_providers(identity="intake"),
    )
    await governed(
        "http://db",
        "insertClaim",
        {"employeeId": "emp-123", "status": "pending", "totalAmount": 600},
    )
    decisions.add(audit.entries[-1]["disposition"]["decision"])

    # Observe — governance unavailable on a non-high-impact call.
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=AsyncMock(return_value={"ok": True}),
        audit_sink=audit,
        identity_registry=RaisingIdentityRegistry(),
        **_providers(),
    )
    await governed("http://db", "executeQuery", {"query": "SELECT 1"})
    decisions.add(audit.entries[-1]["disposition"]["decision"])

    assert decisions == {"Deny", "Escalate", "Auto-Execute", "Observe"}


@pytest.mark.asyncio
async def test_a12_wrapper_audits_and_fails_closed_by_default(policy_environment):
    real = AsyncMock()
    audit = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real,
        audit_sink=audit,
        identity_registry=RaisingIdentityRegistry(),
        **_providers(),
    )

    result = await governed(
        "http://db",
        "insertClaim",
        {"employeeId": "emp-123", "status": "draft", "totalAmount": 0, "currency": "SGD"},
    )

    assert result == {"error": "governance-unavailable", "decision": "Deny"}
    real.assert_not_awaited()
    assert audit.entries[0]["disposition"]["controlStates"][-1] == {
        "controlId": "A12",
        "mode": "enforce",
        "outcome": "denied",
    }


def test_policy_override_missing_an_allowlisted_schema_fails_closed(
    policy_environment, monkeypatch, tmp_path
):
    default = files("agentic_governance.policy").joinpath("default_policy.json")
    document = json.loads(default.read_text(encoding="utf-8"))
    document["schemas"] = [
        item for item in document["schemas"] if item["tool"] != "executeQuery"
    ]
    override = tmp_path / "incomplete-policy.json"
    override.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setenv("AGENTIC_GOV_POLICY_FILE", str(override))

    from agentic_governance.adapters.policy_loader import PolicyConfigError

    with pytest.raises(PolicyConfigError):
        install(real_mcp_call_tool=AsyncMock(), **_providers())


def test_a11_action_authorization_core_is_standalone_and_model_independent():
    core_dir = Path(inspect.getfile(core_package)).parent
    forbidden = ("agentic_claims", "langchain", "openai", "anthropic", "model_hook")
    for path in core_dir.glob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        assert not any(name in source for name in forbidden), path

    validator = SchemaValidator()
    schema = {
        "type": "object",
        "required": ["value"],
        "additionalProperties": False,
        "properties": {"value": {"type": "integer"}},
    }
    from agentic_governance.core.schema_validation import SchemaRule

    rule = SchemaRule("server", "tool", schema)
    first = validator.evaluate(
        server_url="server",
        tool_name="tool",
        arguments={"value": 1},
        trusted_servers=frozenset({"server"}),
        rules=(rule,),
    )
    second = validator.evaluate(
        server_url="server",
        tool_name="tool",
        arguments={"value": 1},
        trusted_servers=frozenset({"server"}),
        rules=(rule,),
    )
    assert first == second

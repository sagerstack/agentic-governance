from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agentic_governance.adapters.identity_mandates import IdentityMandateConfig
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
    monkeypatch.delenv("AGENTIC_GOV_DENY_TOOLS", raising=False)
    monkeypatch.delenv("AGENTIC_GOV_REVOKE_GRANTS", raising=False)
    monkeypatch.delenv("AGENTIC_GOV_FORCE_IDENTITY", raising=False)


def _providers(identity):
    return {
        "employee_id_provider": lambda: "emp-123",
        "extracted_receipt_provider": lambda: None,
        "session_claim_id_provider": lambda: "claim-456",
        "node_identity_provider": lambda: identity,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("identity", "server", "tool"),
    [
        ("intake", "http://db", "insertClaim"),
        ("application", "http://db", "insertClaim"),
        ("application", "http://db", "executeQuery"),
    ],
)
async def test_permitted_identity_mandates_execute(
    policy_environment, identity, server, tool
):
    real_mcp_call_tool = AsyncMock(return_value={"ok": True})
    audit_sink = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real_mcp_call_tool,
        audit_sink=audit_sink,
        **_providers(identity),
    )

    result = await governed(server, tool, {})

    assert result == {"ok": True}
    real_mcp_call_tool.assert_awaited_once_with(server, tool, {})
    disposition = audit_sink.entries[0]["disposition"]
    assert disposition["decision"] == "Auto-Execute"
    controls = {control["controlId"]: control["result"] for control in disposition["firedControls"]}
    assert controls["A3"] == "verified"
    assert controls["A4"] == "allowed"
    assert controls["A5"] == "allowed"
    assert controls["A6"] == "Auto-Execute"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("identity", "tool"),
    [
        ("advisor", "insertClaim"),
        ("intake", "updateClaimStatus"),
        ("fraud", "updateClaimStatus"),
    ],
)
async def test_out_of_mandate_calls_are_denied(
    policy_environment, identity, tool
):
    real_mcp_call_tool = AsyncMock()
    audit_sink = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real_mcp_call_tool,
        audit_sink=audit_sink,
        **_providers(identity),
    )

    result = await governed("http://db", tool, {})

    assert result == {"error": "mandate-violation", "decision": "Deny"}
    real_mcp_call_tool.assert_not_awaited()
    disposition = audit_sink.entries[0]["disposition"]
    assert disposition["reasons"] == ["mandate-violation"]
    controls = {control["controlId"]: control["result"] for control in disposition["firedControls"]}
    assert controls["A3"] == "verified"
    assert controls["A4"] == "denied"
    assert controls["A5"] == "allowed"
    assert controls["A6"] == "Deny"


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", [None, "unknown-agent"])
async def test_missing_or_unknown_identity_is_denied_fail_closed(
    policy_environment, identity
):
    real_mcp_call_tool = AsyncMock()
    audit_sink = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real_mcp_call_tool,
        audit_sink=audit_sink,
        **_providers(identity),
    )

    result = await governed("http://db", "insertClaim", {})

    assert result == {"error": "unverified-identity", "decision": "Deny"}
    real_mcp_call_tool.assert_not_awaited()
    disposition = audit_sink.entries[0]["disposition"]
    assert disposition["reasons"] == ["unverified-identity"]
    controls = {control["controlId"]: control["result"] for control in disposition["firedControls"]}
    assert controls["A3"] == "denied"
    assert "A4" not in controls
    assert controls["A5"] == "allowed"
    assert controls["A6"] == "Deny"


def test_canonical_identity_mandates_use_only_real_wire_tools(policy_environment):
    config = IdentityMandateConfig.from_environment()
    expected = {
        "intake": {
            ("http://db", "getClaimSchema"),
            ("http://rag", "searchPolicies"),
            ("http://currency", "convertCurrency"),
            ("http://db", "insertClaim"),
            ("http://db", "insertAuditLog"),
        },
        "compliance": {
            ("http://rag", "searchPolicies"),
            ("http://db", "insertAuditLog"),
        },
        "fraud": {
            ("http://db", "executeQuery"),
            ("http://db", "insertAuditLog"),
        },
        "advisor": {
            ("http://rag", "searchPolicies"),
            ("http://db", "updateClaimStatus"),
            ("http://db", "insertAuditLog"),
        },
        "humanEscalation": {("http://db", "updateClaimStatus")},
        "markAiReviewed": {("http://db", "updateClaimStatus")},
        "application": {
            ("http://db", "insertClaim"),
            ("http://db", "executeQuery"),
            ("http://db", "insertAuditLog"),
        },
    }
    assert set(config.identities) == set(expected)
    assert {
        identity: mandate.allowed_pairs for identity, mandate in config.mandates.items()
    } == expected

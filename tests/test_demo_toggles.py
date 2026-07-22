from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agentic_governance.adapters.identity_mandates import IdentityMandateConfig
from agentic_governance.adapters.jsonl_audit import build_audit_entry
from agentic_governance.adapters.tool_allowlist import ToolAllowlistConfig
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


def _providers(identity="intake"):
    return {
        "employee_id_provider": lambda: "emp-123",
        "extracted_receipt_provider": lambda: None,
        "session_claim_id_provider": lambda: "claim-456",
        "node_identity_provider": lambda: identity,
    }


@pytest.mark.asyncio
async def test_revoke_grant_denies_only_the_selected_identity_tool(
    policy_environment, monkeypatch
):
    monkeypatch.setenv("AGENTIC_GOV_REVOKE_GRANTS", " intake:searchPolicies ")
    real_mcp_call_tool = AsyncMock(return_value={"ok": True})
    audit_sink = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real_mcp_call_tool,
        audit_sink=audit_sink,
        **_providers(),
    )

    denied = await governed("http://rag", "searchPolicies", {"query": "meals"})
    allowed = await governed("http://db", "insertClaim", {})

    assert denied == {"error": "mandate-violation", "decision": "Deny"}
    assert allowed == {"ok": True}
    real_mcp_call_tool.assert_awaited_once_with("http://db", "insertClaim", {})
    denied_disposition = audit_sink.entries[0]["disposition"]
    controls = {
        control["controlId"]: control["result"]
        for control in denied_disposition["firedControls"]
    }
    assert denied_disposition["reasons"] == ["mandate-violation"]
    assert controls["A3"] == "verified"
    assert controls["A4"] == "denied"
    assert ToolAllowlistConfig.from_environment().allows(
        "http://rag", "searchPolicies"
    )


def test_revoke_grants_ignores_malformed_and_unknown_entries():
    config = IdentityMandateConfig.from_environment(
        {
            "RAG_MCP_URL": "http://rag",
            "DB_MCP_URL": "http://db",
            "CURRENCY_MCP_URL": "http://currency",
            "AGENTIC_GOV_REVOKE_GRANTS": (
                "malformed,unknown:insertClaim,intake:notARealGrant,"
                "intake:searchPolicies"
            ),
        }
    )

    assert config.revoked_grants == {("intake", "searchPolicies")}
    assert not config.mandates["intake"].allows("http://rag", "searchPolicies")
    assert config.mandates["intake"].allows("http://db", "insertClaim")


@pytest.mark.asyncio
async def test_force_registered_identity_runs_normal_mandate_enforcement(
    policy_environment, monkeypatch
):
    monkeypatch.setenv("AGENTIC_GOV_FORCE_IDENTITY", " fraud ")
    real_mcp_call_tool = AsyncMock()
    audit_sink = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real_mcp_call_tool,
        audit_sink=audit_sink,
        **_providers("intake"),
    )

    result = await governed("http://db", "insertClaim", {})

    assert result == {"error": "mandate-violation", "decision": "Deny"}
    assert audit_sink.entries[0]["agentIdentity"]["id"] == "fraud"
    real_mcp_call_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_force_unknown_identity_is_denied_as_unverified(
    policy_environment, monkeypatch
):
    monkeypatch.setenv("AGENTIC_GOV_FORCE_IDENTITY", "attacker")
    real_mcp_call_tool = AsyncMock()
    audit_sink = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real_mcp_call_tool,
        audit_sink=audit_sink,
        **_providers("intake"),
    )

    result = await governed("http://db", "insertClaim", {})

    assert result == {"error": "unverified-identity", "decision": "Deny"}
    assert audit_sink.entries[0]["agentIdentity"]["id"] == "attacker"
    real_mcp_call_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_demo_toggles_default_off_preserves_trusted_identity(
    policy_environment,
):
    real_mcp_call_tool = AsyncMock(return_value={"ok": True})
    audit_sink = MemoryAuditSink()
    governed = install(
        real_mcp_call_tool=real_mcp_call_tool,
        audit_sink=audit_sink,
        **_providers("intake"),
    )

    result = await governed("http://db", "insertClaim", {})

    assert result == {"ok": True}
    assert audit_sink.entries[0]["agentIdentity"]["id"] == "intake"
    real_mcp_call_tool.assert_awaited_once()

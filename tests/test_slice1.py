from __future__ import annotations

from importlib.metadata import version
import json
from unittest.mock import AsyncMock

import pytest

from agentic_governance.adapters.jsonl_audit import build_audit_entry
from agentic_governance.adapters.tool_allowlist import ToolAllowlistConfig
from agentic_governance.integrations.langgraph_mcp.governed_mcp_call import install


class MemoryAuditSink:
    def __init__(self, order: list[str] | None = None) -> None:
        self.entries: list[dict] = []
        self.order = order

    async def append(self, envelope, disposition) -> None:
        if self.order is not None:
            self.order.append("audit")
        self.entries.append(build_audit_entry(envelope, disposition))


@pytest.fixture
def policy_environment(monkeypatch):
    monkeypatch.setenv("RAG_MCP_URL", "http://rag")
    monkeypatch.setenv("DB_MCP_URL", "http://db")
    monkeypatch.setenv("CURRENCY_MCP_URL", "http://currency")
    monkeypatch.delenv("AGENTIC_GOV_DENY_TOOLS", raising=False)
    monkeypatch.delenv("AGENTIC_GOV_REVOKE_GRANTS", raising=False)
    monkeypatch.delenv("AGENTIC_GOV_FORCE_IDENTITY", raising=False)


@pytest.fixture
def providers():
    return {
        "employee_id_provider": lambda: "emp-123",
        "extracted_receipt_provider": lambda: None,
        "session_claim_id_provider": lambda: "claim-456",
        "node_identity_provider": lambda: "intake",
    }


@pytest.mark.asyncio
async def test_allowlisted_pair_is_auto_executed_and_audited_before_dispatch(
    policy_environment, providers
):
    order: list[str] = []

    async def real_call(*args):
        order.append("execute")
        return {"claimId": "c1"}

    real_mcp_call_tool = AsyncMock(side_effect=real_call)
    audit_sink = MemoryAuditSink(order)
    governed = install(real_mcp_call_tool=real_mcp_call_tool, audit_sink=audit_sink, **providers)

    arguments = {"employeeId": "emp-123", "amount": 42}
    result = await governed("http://db", "insertClaim", arguments)

    assert result == {"claimId": "c1"}
    real_mcp_call_tool.assert_awaited_once_with("http://db", "insertClaim", arguments)
    assert order == ["audit", "execute"]
    entry = audit_sink.entries[0]
    assert entry["disposition"]["decision"] == "Auto-Execute"
    installed_version = version("agentic-governance")
    assert entry["disposition"]["policyVersion"] == installed_version
    assert entry["envelope"]["contextMetadata"]["policyVersion"] == installed_version
    assert entry["controlVersions"]["policyVersion"] == installed_version
    assert "slice-" not in json.dumps(entry)


@pytest.mark.asyncio
async def test_unknown_tool_is_denied_and_never_dispatched(policy_environment, providers):
    real_mcp_call_tool = AsyncMock(return_value={"should": "not run"})
    audit_sink = MemoryAuditSink()
    governed = install(real_mcp_call_tool=real_mcp_call_tool, audit_sink=audit_sink, **providers)

    result = await governed("http://db", "fabricatedTool", {})

    assert result == {"error": "tool-not-allowed", "decision": "Deny"}
    real_mcp_call_tool.assert_not_awaited()
    assert len(audit_sink.entries) == 1
    disposition = audit_sink.entries[0]["disposition"]
    assert disposition["decision"] == "Deny"
    assert disposition["reasons"] == ["tool-not-allowed"]
    assert [control["controlId"] for control in disposition["firedControls"]] == ["A5", "A6"]


@pytest.mark.asyncio
async def test_demo_trigger_removes_a_normally_allowed_tool(
    policy_environment, providers, monkeypatch
):
    monkeypatch.setenv("AGENTIC_GOV_DENY_TOOLS", " convertCurrency ")
    real_mcp_call_tool = AsyncMock()
    audit_sink = MemoryAuditSink()
    governed = install(real_mcp_call_tool=real_mcp_call_tool, audit_sink=audit_sink, **providers)

    result = await governed(
        "http://currency", "convertCurrency", {"amount": 42, "from": "USD", "to": "SGD"}
    )

    assert result == {"error": "tool-not-allowed", "decision": "Deny"}
    real_mcp_call_tool.assert_not_awaited()
    assert audit_sink.entries[0]["disposition"]["decision"] == "Deny"


def test_governance_policy_contains_all_legitimate_wire_tools(policy_environment):
    config = ToolAllowlistConfig.from_environment()
    expected = {
        ("http://db", "insertClaim"),
        ("http://db", "updateClaimStatus"),
        ("http://rag", "searchPolicies"),
        ("http://db", "executeQuery"),
        ("http://db", "getClaimSchema"),
        ("http://currency", "convertCurrency"),
        ("http://db", "insertAuditLog"),
    }
    assert config.allowed_pairs == expected
    assert not config.allows("http://email", "sendClaimNotification")
    assert not config.allows("http://rag", "insertClaim")

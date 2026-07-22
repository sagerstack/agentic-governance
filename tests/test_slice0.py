from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agentic_governance.adapters.jsonl_audit import build_audit_entry
from agentic_governance.adapters.pdp_python import DeterministicPolicyDecisionPoint
from agentic_governance.core.engine import GovernanceEngine
from agentic_governance.integrations.langgraph_mcp.governed_mcp_call import install


class MemoryAuditSink:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.entries: list[dict] = []
        self.fail_first = fail_first
        self.calls = 0

    async def append(self, envelope, disposition) -> None:
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("audit unavailable")
        self.entries.append(build_audit_entry(envelope, disposition))


class RaisingIdentityRegistry:
    async def verify(self, identity):
        raise RuntimeError("registry unavailable")


class RaisingEngine(GovernanceEngine):
    def __init__(self):
        pass

    async def evaluate(self, envelope):
        raise RuntimeError("engine unavailable")


@pytest.fixture
def providers(monkeypatch):
    monkeypatch.setenv("RAG_MCP_URL", "http://rag")
    monkeypatch.setenv("DB_MCP_URL", "http://db")
    monkeypatch.setenv("CURRENCY_MCP_URL", "http://currency")
    monkeypatch.delenv("AGENTIC_GOV_DENY_TOOLS", raising=False)
    monkeypatch.delenv("AGENTIC_GOV_REVOKE_GRANTS", raising=False)
    monkeypatch.delenv("AGENTIC_GOV_FORCE_IDENTITY", raising=False)
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_SCHEMA", "off")
    return {
        "employee_id_provider": lambda: "emp-123",
        "extracted_receipt_provider": lambda: {"merchant": "Cafe", "total": 42, "receipt": "SECRET-RECEIPT-PAYLOAD"},
        "session_claim_id_provider": lambda: "claim-456",
        "node_identity_provider": lambda: "application",
    }


@pytest.mark.asyncio
async def test_every_call_emits_one_audit_event_and_allows_execution(providers):
    real_mcp_call_tool = AsyncMock(return_value={"ok": True})
    audit_sink = MemoryAuditSink()
    governed = install(real_mcp_call_tool=real_mcp_call_tool, audit_sink=audit_sink, **providers)

    result = await governed("http://db", "executeQuery", {"query": "select 1", "receipt": "SECRET-RECEIPT-PAYLOAD"})

    assert result == {"ok": True}
    real_mcp_call_tool.assert_awaited_once_with("http://db", "executeQuery", {"query": "select 1", "receipt": "SECRET-RECEIPT-PAYLOAD"})
    assert len(audit_sink.entries) == 1
    entry = audit_sink.entries[0]
    assert entry["disposition"]["decision"] == "Auto-Execute"
    assert entry["correlationId"] == "claim-456"
    assert entry["envelope"]["toolName"] == "executeQuery"
    assert set(entry["envelope"]["paramsRef"]) == {"payloadSha256"}
    assert len(entry["envelope"]["paramsRef"]["payloadSha256"]) == 64
    assert "SECRET-RECEIPT-PAYLOAD" not in str(entry)
    assert entry["prevEntryHash"] is None


@pytest.mark.asyncio
async def test_normal_mode_does_not_block_high_impact_calls(providers):
    real_mcp_call_tool = AsyncMock(return_value={"claimId": "c1"})
    audit_sink = MemoryAuditSink()
    governed = install(real_mcp_call_tool=real_mcp_call_tool, audit_sink=audit_sink, **providers)

    arguments = {
        "employeeId": "emp-123",
        "status": "draft",
        "totalAmount": 0,
        "currency": "SGD",
    }
    result = await governed("http://db", "insertClaim", arguments)

    assert result == {"claimId": "c1"}
    real_mcp_call_tool.assert_awaited_once()
    assert len(audit_sink.entries) == 1
    assert audit_sink.entries[0]["disposition"]["decision"] == "Auto-Execute"


@pytest.mark.asyncio
@pytest.mark.parametrize("high_impact_tool", ["insertClaim", "updateClaimStatus"])
async def test_fail_closed_denies_high_impact_tools_when_governance_is_unavailable(
    providers, high_impact_tool
):
    real_mcp_call_tool = AsyncMock(return_value={"claimId": "c1"})
    audit_sink = MemoryAuditSink(fail_first=True)
    governed = install(
        real_mcp_call_tool=real_mcp_call_tool,
        audit_sink=audit_sink,
        identity_registry=RaisingIdentityRegistry(),
        **providers,
    )

    result = await governed("http://db", high_impact_tool, {"amount": 42})
    assert result == {"error": "governance-unavailable", "decision": "Deny"}
    real_mcp_call_tool.assert_not_awaited()
    assert audit_sink.entries == []

    recovery_result = await governed("http://db", "executeQuery", {"query": "select 1"})
    assert recovery_result == {"claimId": "c1"}
    assert len(audit_sink.entries) == 2
    assert audit_sink.entries[0]["disposition"]["decision"] == "Deny"
    assert audit_sink.entries[0]["disposition"]["reasons"] == ["governance-unavailable"]
    assert audit_sink.entries[0]["envelope"]["toolName"] == high_impact_tool
    assert audit_sink.entries[1]["disposition"]["decision"] == "Observe"
    assert audit_sink.entries[1]["disposition"]["reasons"] == [
        "governance-unavailable-non-high-impact"
    ]

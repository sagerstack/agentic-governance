"""Governance-owned least-privilege policy configuration.

The application already exposes its MCP endpoints through environment variables, so
this adapter can build exact ``(server URL, wire tool name)`` grants without importing
application code or changing the integration contract.  ``AGENTIC_GOV_DENY_TOOLS`` is
a demo-only, comma-separated subtraction from these grants; it is empty by default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os


RAG_WIRE_TOOLS = frozenset({"searchPolicies", "getPolicyByCategory"})
DB_WIRE_TOOLS = frozenset(
    {
        "insertClaim",
        "updateClaimStatus",
        "executeQuery",
        "getClaimSchema",
        "insertAuditLog",
        "exactDuplicateCheck",
        "recentClaimsByEmployee",
        "claimsByMerchantAndEmployee",
    }
)
CURRENCY_WIRE_TOOLS = frozenset({"convertCurrency"})


@dataclass(frozen=True)
class ToolAllowlistConfig:
    """Exact MCP endpoint/tool grants consumed by the pure-Python PDP."""

    allowed_pairs: frozenset[tuple[str, str]]
    demo_denied_tools: frozenset[str] = frozenset()

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "ToolAllowlistConfig":
        env = os.environ if environ is None else environ
        server_tools = (
            (env.get("RAG_MCP_URL", "http://mcp-rag:8000/mcp/"), RAG_WIRE_TOOLS),
            (env.get("DB_MCP_URL", "http://mcp-db:8000/mcp/"), DB_WIRE_TOOLS),
            (env.get("CURRENCY_MCP_URL", "http://mcp-currency:8000/mcp/"), CURRENCY_WIRE_TOOLS),
        )
        demo_denied = frozenset(
            name.strip()
            for name in env.get("AGENTIC_GOV_DENY_TOOLS", "").split(",")
            if name.strip()
        )
        allowed = frozenset(
            (server_url, tool_name)
            for server_url, tool_names in server_tools
            for tool_name in tool_names
            if tool_name not in demo_denied
        )
        return cls(allowed_pairs=allowed, demo_denied_tools=demo_denied)

    def allows(self, server_url: str, tool_name: str) -> bool:
        return (server_url, tool_name) in self.allowed_pairs

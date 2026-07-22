"""Governance-owned global least-privilege grants loaded from policy data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os

from agentic_governance.adapters.policy_loader import LoadedPolicy, load_policy


@dataclass(frozen=True)
class ToolAllowlistConfig:
    """Exact MCP endpoint/tool grants consumed by the pure-Python PDP."""

    allowed_pairs: frozenset[tuple[str, str]]
    demo_denied_tools: frozenset[str] = frozenset()

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ToolAllowlistConfig":
        env = os.environ if environ is None else environ
        return cls.from_policy(load_policy(env), env)

    @classmethod
    def from_policy(
        cls,
        policy: LoadedPolicy,
        environ: Mapping[str, str] | None = None,
    ) -> "ToolAllowlistConfig":
        env = os.environ if environ is None else environ
        demo_denied = frozenset(
            name.strip()
            for name in env.get("AGENTIC_GOV_DENY_TOOLS", "").split(",")
            if name.strip()
        )
        allowed = frozenset(
            pair for pair in policy.allowed_pairs if pair[1] not in demo_denied
        )
        return cls(allowed_pairs=allowed, demo_denied_tools=demo_denied)

    def allows(self, server_url: str, tool_name: str) -> bool:
        return (server_url, tool_name) in self.allowed_pairs

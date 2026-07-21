from __future__ import annotations

from agentic_governance.adapters.tool_allowlist import ToolAllowlistConfig
from agentic_governance.core.disposition import Disposition, FiredControl, auto_execute, deny
from agentic_governance.core.envelope import GovernanceEnvelope


class DeterministicPolicyDecisionPoint:
    """Deny-by-default evaluator for exact MCP server/wire-tool grants."""

    def __init__(self, allowlist: ToolAllowlistConfig | None = None) -> None:
        self._allowlist = allowlist or ToolAllowlistConfig.from_environment()

    async def evaluate(self, envelope: GovernanceEnvelope) -> Disposition:
        if not self._allowlist.allows(envelope.mcp_server, envelope.tool_name):
            return deny(
                "tool-not-allowed",
                fired_controls=(
                    FiredControl(control_id="A5", name="least-privilege", result="denied"),
                    FiredControl(control_id="A6", name="deterministic-disposition", result="Deny"),
                ),
            )
        return auto_execute(
            reasons=("tool-allowed",),
            fired_controls=(
                FiredControl(control_id="A1", name="governance-envelope", result="observed"),
                FiredControl(control_id="A5", name="least-privilege", result="allowed"),
                FiredControl(control_id="A6", name="deterministic-disposition", result="Auto-Execute"),
            ),
        )

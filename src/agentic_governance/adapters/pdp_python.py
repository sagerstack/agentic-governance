from __future__ import annotations

from agentic_governance.adapters.control_modes import ControlModeConfig
from agentic_governance.adapters.policy_loader import LoadedPolicy, load_policy
from agentic_governance.adapters.tool_allowlist import ToolAllowlistConfig
from agentic_governance.core.disposition import (
    ControlState,
    Disposition,
    FiredControl,
    auto_execute,
    deny,
)
from agentic_governance.core.envelope import GovernanceEnvelope


class DeterministicPolicyDecisionPoint:
    """Deny-by-default evaluator for exact MCP server/wire-tool grants."""

    def __init__(
        self,
        allowlist: ToolAllowlistConfig | None = None,
        *,
        policy: LoadedPolicy | None = None,
        control_modes: ControlModeConfig | None = None,
    ) -> None:
        loaded_policy = policy or load_policy()
        self._allowlist = allowlist or ToolAllowlistConfig.from_policy(loaded_policy)
        self._control_modes = control_modes or ControlModeConfig.from_policy(loaded_policy)

    async def evaluate(self, envelope: GovernanceEnvelope) -> Disposition:
        mode = self._control_modes.mode("A5")
        if mode == "off":
            return auto_execute(
                reasons=("allowlist-disabled",),
                fired_controls=(
                    FiredControl(control_id="A1", name="governance-envelope", result="observed"),
                    FiredControl(control_id="A6", name="deterministic-disposition", result="Auto-Execute"),
                ),
                control_states=(
                    ControlState(control_id="A5", mode="off", outcome="skipped-disabled"),
                ),
            )

        allowed = self._allowlist.allows(envelope.mcp_server, envelope.tool_name)
        if not allowed and mode == "enforce":
            return deny(
                "tool-not-allowed",
                fired_controls=(
                    FiredControl(control_id="A5", name="least-privilege", result="denied"),
                    FiredControl(control_id="A6", name="deterministic-disposition", result="Deny"),
                ),
                control_states=(
                    ControlState(control_id="A5", mode="enforce", outcome="denied"),
                ),
            )
        if not allowed:
            return auto_execute(
                reasons=("would-deny:tool-not-allowed",),
                fired_controls=(
                    FiredControl(control_id="A1", name="governance-envelope", result="observed"),
                    FiredControl(control_id="A5", name="least-privilege", result="would-deny"),
                    FiredControl(control_id="A6", name="deterministic-disposition", result="Auto-Execute"),
                ),
                control_states=(
                    ControlState(
                        control_id="A5",
                        mode="observe",
                        outcome="would-deny:tool-not-allowed",
                    ),
                ),
            )
        return auto_execute(
            reasons=("tool-allowed",),
            fired_controls=(
                FiredControl(control_id="A1", name="governance-envelope", result="observed"),
                FiredControl(control_id="A5", name="least-privilege", result="allowed"),
                FiredControl(control_id="A6", name="deterministic-disposition", result="Auto-Execute"),
            ),
            control_states=(
                ControlState(control_id="A5", mode=mode, outcome="allowed"),
            ),
        )

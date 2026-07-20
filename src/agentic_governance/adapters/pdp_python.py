from __future__ import annotations

from agentic_governance.core.disposition import Disposition, FiredControl, auto_execute
from agentic_governance.core.envelope import GovernanceEnvelope


class DeterministicPolicyDecisionPoint:
    async def evaluate(self, envelope: GovernanceEnvelope) -> Disposition:
        return auto_execute(
            reasons=("slice-0-pass-through",),
            fired_controls=(
                FiredControl(control_id="A1", name="governance-envelope", result="observed"),
                FiredControl(control_id="A6", name="deterministic-disposition", result="Auto-Execute"),
            ),
        )

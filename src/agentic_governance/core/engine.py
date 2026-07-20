from __future__ import annotations

import time

from agentic_governance.core.disposition import Disposition, FiredControl
from agentic_governance.core.envelope import GovernanceEnvelope
from agentic_governance.ports.policy_decision_point import PolicyDecisionPoint


class GovernanceEngine:
    def __init__(self, pdp: PolicyDecisionPoint):
        self._pdp = pdp

    async def evaluate(self, envelope: GovernanceEnvelope) -> Disposition:
        start = time.perf_counter()
        disposition = await self._pdp.evaluate(envelope)
        latency_ms = (time.perf_counter() - start) * 1000
        fired = disposition.fired_controls or (
            FiredControl(control_id="A6", name="deterministic-disposition", result=disposition.decision),
        )
        return Disposition(
            decision=disposition.decision,
            reasons=disposition.reasons,
            fired_controls=fired,
            policy_version=disposition.policy_version,
            latency_ms=latency_ms,
        )

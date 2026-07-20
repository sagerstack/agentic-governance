from __future__ import annotations

from typing import Protocol

from agentic_governance.core.envelope import GovernanceEnvelope
from agentic_governance.core.disposition import Disposition


class PolicyDecisionPoint(Protocol):
    async def evaluate(self, envelope: GovernanceEnvelope) -> Disposition: ...

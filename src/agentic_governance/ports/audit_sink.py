from __future__ import annotations

from typing import Protocol

from agentic_governance.core.envelope import GovernanceEnvelope
from agentic_governance.core.disposition import Disposition


class AuditSink(Protocol):
    async def append(self, envelope: GovernanceEnvelope, disposition: Disposition) -> None: ...

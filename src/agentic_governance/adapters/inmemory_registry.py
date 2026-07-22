from __future__ import annotations

from agentic_governance.adapters.identity_mandates import (
    IdentityMandateConfig,
    IdentityRecord,
    Mandate,
)


class InMemoryIdentityRegistry:
    """Verify trusted context identities against governance-owned records."""

    def __init__(self, config: IdentityMandateConfig | None = None) -> None:
        self._config = config or IdentityMandateConfig.from_environment()

    async def verify(self, identity: str | None) -> IdentityRecord | None:
        if identity is None:
            return None
        return self._config.identities.get(identity)


class InMemoryMandateStore:
    """Retrieve machine-readable exact-pair capabilities by verified identity."""

    def __init__(self, config: IdentityMandateConfig | None = None) -> None:
        self._config = config or IdentityMandateConfig.from_environment()

    async def mandate_for(self, identity: str | None) -> Mandate | None:
        if identity is None:
            return None
        return self._config.mandates.get(identity)

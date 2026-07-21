from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerifiedIdentity:
    id: str | None


class InMemoryIdentityRegistry:
    async def verify(self, identity: str | None) -> VerifiedIdentity:
        return VerifiedIdentity(id=identity)


class InMemoryMandateStore:
    async def mandate_for(self, identity: str | None) -> dict:
        return {"identity": identity, "scope": "global"}

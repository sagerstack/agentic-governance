from __future__ import annotations

from typing import Protocol, Any


class IdentityRegistry(Protocol):
    async def verify(self, identity: str | None) -> Any: ...

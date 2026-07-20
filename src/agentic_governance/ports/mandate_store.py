from __future__ import annotations

from typing import Protocol, Any


class MandateStore(Protocol):
    async def mandate_for(self, identity: str | None) -> Any: ...

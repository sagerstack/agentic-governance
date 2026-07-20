from __future__ import annotations

from typing import Protocol


class CounterStore(Protocol):
    async def increment(self, key: str, amount: int = 1) -> int: ...

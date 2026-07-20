from __future__ import annotations

import asyncio


class InMemoryCounterStore:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def increment(self, key: str, amount: int = 1) -> int:
        async with self._lock:
            self._counts[key] = self._counts.get(key, 0) + amount
            return self._counts[key]

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
import time
from typing import Callable


@dataclass(frozen=True)
class WindowCounterValue:
    value: Decimal
    window_start: float


class InMemoryCounterStore:
    """Async-atomic fixed-window counters; one lock protects every key transition."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._counts: dict[str, int] = {}
        self._windows: dict[str, WindowCounterValue] = {}
        self._lock = asyncio.Lock()
        self._clock = clock

    async def increment(self, key: str, amount: int = 1) -> int:
        async with self._lock:
            self._counts[key] = self._counts.get(key, 0) + amount
            return self._counts[key]

    async def add_window(
        self,
        key: str,
        amount: Decimal,
        window_seconds: int,
    ) -> WindowCounterValue:
        async with self._lock:
            now = self._clock()
            current = self._windows.get(key)
            if current is None or now - current.window_start >= window_seconds:
                current = WindowCounterValue(Decimal("0"), now)
            updated = WindowCounterValue(current.value + amount, current.window_start)
            self._windows[key] = updated
            return updated

    async def rollback_window(
        self,
        key: str,
        amount: Decimal,
        window_start: float,
    ) -> None:
        """Release an exposure reservation if its fixed window is still current."""
        async with self._lock:
            current = self._windows.get(key)
            if current is None or current.window_start != window_start:
                return
            self._windows[key] = WindowCounterValue(
                max(Decimal("0"), current.value - amount),
                current.window_start,
            )

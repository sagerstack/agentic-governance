from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol


class CounterStore(Protocol):
    async def increment(self, key: str, amount: int = 1) -> int: ...

    async def add_window(
        self, key: str, amount: Decimal, window_seconds: int
    ) -> Any: ...

    async def rollback_window(
        self, key: str, amount: Decimal, window_start: float
    ) -> None: ...

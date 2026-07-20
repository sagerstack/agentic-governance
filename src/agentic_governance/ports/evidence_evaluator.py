from __future__ import annotations

from typing import Protocol


class EvidenceEvaluator(Protocol):
    async def evaluate(self, envelope: object) -> dict: ...

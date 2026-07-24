from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JudgeCritique:
    """LLM judge output — observe-only signal. NEVER blocks or denies alone.

    In observe mode (default): audit only, zero flow effect.
    In enforce mode: concerns can contribute to escalation ONLY combined with B3 findings.
    """
    concerns: tuple[str, ...]
    confidence: float | None
    flags: tuple[str, ...]  # "hallucination" | "inconsistency" | "confidence_gap"
    contributed_to_escalation: bool
    latency_ms: float


class LlmJudge:
    """Observe-only LLM critique of model output (B4).

    NEVER the sole blocker. Judge failure NEVER breaks the pipeline.
    Inject llm_client for testability; None = no-op.
    """

    SYSTEM_PROMPT = """You are a governance audit assistant reviewing AI-generated expense claim decisions.
Identify any hallucinations, inconsistencies, missing evidence, or confidence gaps.
Respond in JSON: {"concerns": ["..."], "confidence": 0.0-1.0, "flags": ["hallucination"|"inconsistency"|"confidence_gap"]}
If no concerns, return empty arrays."""

    def __init__(
        self, *, llm_client: Any | None = None,
        model: str = "openai/gpt-4o-mini",
        prompt_template: str | None = None,
    ) -> None:
        self._client = llm_client
        self._model = model
        self._system_prompt = prompt_template or self.SYSTEM_PROMPT

    async def critique(self, model_output: str, context: dict[str, Any]) -> JudgeCritique:
        """Critique model output. NEVER blocks alone. Returns empty critique on failure."""
        if self._client is None:
            return self._empty_critique()

        start = time.perf_counter()
        try:
            import json
            response = await self._client.complete(
                model=self._model,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": f"Model output:\n{model_output}\n\nContext: {context.get('claim_type', 'expense claim')}"},
                ],
            )
            raw = response.choices[0].message.content if hasattr(response, "choices") else str(response)
            data = json.loads(raw)
            latency_ms = (time.perf_counter() - start) * 1000
            return JudgeCritique(
                concerns=tuple(data.get("concerns", [])),
                confidence=float(data["confidence"]) if "confidence" in data else None,
                flags=tuple(data.get("flags", [])),
                contributed_to_escalation=False,
                latency_ms=latency_ms,
            )
        except Exception:
            latency_ms = (time.perf_counter() - start) * 1000
            return self._empty_critique(latency_ms=latency_ms)

    def _empty_critique(self, *, latency_ms: float = 0.0) -> JudgeCritique:
        return JudgeCritique(concerns=(), confidence=None, flags=(), contributed_to_escalation=False, latency_ms=latency_ms)


class StubLlmJudge(LlmJudge):
    """Stub for testing."""
    def __init__(self, *, concerns: tuple[str, ...] = (), confidence: float | None = 0.9, flags: tuple[str, ...] = ()) -> None:
        self._stub_concerns = concerns
        self._stub_confidence = confidence
        self._stub_flags = flags

    async def critique(self, model_output: str, context: dict[str, Any]) -> JudgeCritique:
        return JudgeCritique(concerns=self._stub_concerns, confidence=self._stub_confidence, flags=self._stub_flags, contributed_to_escalation=False, latency_ms=1.0)

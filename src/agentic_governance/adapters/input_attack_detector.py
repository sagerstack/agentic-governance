from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AttackSignal:
    score: float          # 0.0 = definitely safe, 1.0 = definitely injection
    label: str            # "INJECTION" or "SAFE"
    is_injection: bool    # True iff label == "INJECTION" and score >= threshold


class InputAttackDetector:
    """DeBERTa-based prompt injection detector.
    
    Uses protectai/deberta-v3-base-prompt-injection-v2 model.
    ML pipeline is lazily loaded on first use.
    
    For testing: inject pipeline_factory to avoid model download.
    """

    DEFAULT_MODEL = "protectai/deberta-v3-base-prompt-injection-v2"
    DEFAULT_THRESHOLD = 0.80

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL,
        injection_threshold: float = DEFAULT_THRESHOLD,
        pipeline_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._model_name = model_name
        self._threshold = injection_threshold
        self._pipeline_factory = pipeline_factory
        self._pipeline: Any | None = None

    def detect(self, text: str) -> AttackSignal:
        """Run prompt injection detection on text.
        
        Returns an AttackSignal with the injection probability and label.
        The caller (ContentHookRuntime) applies mode logic (enforce/observe/off).
        This detector NEVER makes blocking decisions on its own.
        """
        pipeline = self._get_pipeline()
        results = pipeline(text)
        # Results is a list of dicts: [{"label": "INJECTION", "score": 0.95}, ...]
        # The model returns a list; we take the first result
        if isinstance(results, list) and results:
            result = results[0]
            if isinstance(result, list):
                result = result[0]
        else:
            result = results
        
        label = result.get("label", "SAFE")
        score = float(result.get("score", 0.0))
        is_injection = label == "INJECTION" and score >= self._threshold
        return AttackSignal(score=score, label=label, is_injection=is_injection)

    def _get_pipeline(self) -> Any:
        if self._pipeline is None:
            if self._pipeline_factory is not None:
                self._pipeline = self._pipeline_factory()
            else:
                self._load_pipeline()
        return self._pipeline

    def _load_pipeline(self) -> None:
        try:
            from transformers import pipeline  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "transformers is required for InputAttackDetector. "
                "Install with: pip install 'agentic-governance[content]' "
                "or pip install transformers"
            ) from exc
        self._pipeline = pipeline(
            "text-classification",
            model=self._model_name,
            truncation=True,
            max_length=512,
        )


class StubInputAttackDetector(InputAttackDetector):
    """Stub for testing — returns pre-configured signals without loading any model."""

    def __init__(
        self,
        *,
        is_injection: bool = False,
        score: float = 0.1,
        label: str | None = None,
    ) -> None:
        self._is_injection = is_injection
        self._score = score
        self._label = label or ("INJECTION" if is_injection else "SAFE")

    def detect(self, text: str) -> AttackSignal:
        return AttackSignal(
            score=self._score,
            label=self._label,
            is_injection=self._is_injection,
        )

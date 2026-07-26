from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Callable


def _hash(value: Any) -> str:
    try:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        canonical = repr(value)
    return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PiiResult:
    text: str                        # Anonymized/redacted text (safe to log)
    original_ref: str                # SHA-256 hash of original input (NOT the text itself)
    pii_found: bool
    entity_types: tuple[str, ...]    # Category names only: ("EMAIL_ADDRESS", "PERSON") — NEVER the matched values


class PiiMinimizer:
    """Presidio-based PII detection and anonymization.
    
    Detects and anonymizes PII in text. Supports lazy loading.
    Inject analyzer_factory and anonymizer_factory for testing.
    
    PII safety guarantee: PiiResult.entity_types contains only category
    names (e.g. "EMAIL_ADDRESS"), never the actual matched PII values.
    """

    DEFAULT_ENTITIES = [
        "PERSON",
        "EMAIL_ADDRESS", 
        "PHONE_NUMBER",
        "CREDIT_CARD",
        "IBAN_CODE",
        "US_SSN",
    ]

    def __init__(
        self,
        *,
        entities: list[str] | None = None,
        analyzer_factory: Callable[[], Any] | None = None,
        anonymizer_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._entities = entities or self.DEFAULT_ENTITIES
        self._analyzer_factory = analyzer_factory
        self._anonymizer_factory = anonymizer_factory
        self._analyzer: Any | None = None
        self._anonymizer: Any | None = None

    def anonymize(self, text: str, language: str = "en") -> PiiResult:
        """Detect and redact PII from text.
        
        Returns PiiResult with:
        - text: redacted version (e.g. "Hello <PERSON>")
        - original_ref: hash of original (for audit)
        - pii_found: whether any PII was detected
        - entity_types: tuple of category names found (NOT values)
        """
        analyzer = self._get_analyzer()
        anonymizer = self._get_anonymizer()
        original_ref = _hash(text)

        results = analyzer.analyze(text=text, entities=self._entities, language=language)
        
        if not results:
            return PiiResult(
                text=text,
                original_ref=original_ref,
                pii_found=False,
                entity_types=(),
            )

        # Anonymize: replace PII with <ENTITY_TYPE> placeholders
        try:
            from presidio_anonymizer.entities import OperatorConfig  # type: ignore[import-untyped]
            operators = {
                entity: OperatorConfig("replace", {"new_value": f"<{entity}>"})
                for entity in self._entities
            }
            anonymized = anonymizer.anonymize(text=text, analyzer_results=results, operators=operators)
            anonymized_text = anonymized.text
        except ImportError:
            # Fallback: simple placeholder replacement
            anonymized_text = text
            for result in sorted(results, key=lambda r: r.start, reverse=True):
                anonymized_text = (
                    anonymized_text[: result.start]
                    + f"<{result.entity_type}>"
                    + anonymized_text[result.end :]
                )

        # Entity types: only category names, not values
        entity_types = tuple(sorted({r.entity_type for r in results}))
        return PiiResult(
            text=anonymized_text,
            original_ref=original_ref,
            pii_found=True,
            entity_types=entity_types,
        )

    def is_clear(self, text: str, language: str = "en") -> bool:
        """Return True if no PII detected in text."""
        analyzer = self._get_analyzer()
        results = analyzer.analyze(text=text, entities=self._entities, language=language)
        return len(results) == 0

    def _get_analyzer(self) -> Any:
        if self._analyzer is None:
            if self._analyzer_factory is not None:
                self._analyzer = self._analyzer_factory()
            else:
                self._load_analyzer()
        return self._analyzer

    def _get_anonymizer(self) -> Any:
        if self._anonymizer is None:
            if self._anonymizer_factory is not None:
                self._anonymizer = self._anonymizer_factory()
            else:
                self._load_anonymizer()
        return self._anonymizer

    def _load_analyzer(self) -> None:
        try:
            from presidio_analyzer import AnalyzerEngine  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "presidio-analyzer is required for PiiMinimizer. "
                "Install with: pip install 'agentic-governance[content]' "
                "or pip install presidio-analyzer"
            ) from exc
        self._analyzer = AnalyzerEngine()

    def _load_anonymizer(self) -> None:
        try:
            from presidio_anonymizer import AnonymizerEngine  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "presidio-anonymizer is required for PiiMinimizer. "
                "Install with: pip install 'agentic-governance[content]' "
                "or pip install presidio-anonymizer"
            ) from exc
        self._anonymizer = AnonymizerEngine()


class StubPiiMinimizer(PiiMinimizer):
    """Stub for testing — returns pre-configured results without loading Presidio."""

    def __init__(
        self,
        *,
        has_pii: bool = False,
        entity_types: tuple[str, ...] = (),
        redacted_suffix: str = "_REDACTED",
    ) -> None:
        self._has_pii = has_pii
        self._stub_entity_types = entity_types or (("EMAIL_ADDRESS",) if has_pii else ())
        self._redacted_suffix = redacted_suffix

    def anonymize(self, text: str, language: str = "en") -> PiiResult:
        if not self._has_pii:
            return PiiResult(
                text=text,
                original_ref=_hash(text),
                pii_found=False,
                entity_types=(),
            )
        # Return a clearly-redacted version (but still don't store raw PII)
        redacted = f"[REDACTED{self._redacted_suffix}]"
        return PiiResult(
            text=redacted,
            original_ref=_hash(text),
            pii_found=True,
            entity_types=self._stub_entity_types,
        )

    def is_clear(self, text: str, language: str = "en") -> bool:
        return not self._has_pii

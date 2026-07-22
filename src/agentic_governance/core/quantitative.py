"""Generic config-driven quantitative and evidence checks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


_MISSING = object()


@dataclass(frozen=True)
class ExposureRule:
    server_url: str
    tool_name: str
    identities: frozenset[str]
    value_path: str
    currency: str
    escalate_ceiling: Decimal
    hard_deny_cap: Decimal
    ceiling_disposition: str
    hard_cap_disposition: str
    aggregate_limit: Decimal
    aggregate_window_seconds: int
    aggregate_key_paths: tuple[str, ...]
    aggregate_disposition: str


@dataclass(frozen=True)
class RateRule:
    server_url: str
    tool_name: str
    identities: frozenset[str]
    key_paths: tuple[str, ...]
    max_attempts: int
    window_seconds: int
    exceeded_disposition: str


@dataclass(frozen=True)
class EvidenceRule:
    server_url: str
    tool_name: str
    identities: frozenset[str]
    confidence_path: str
    required_confidence_fields: tuple[str, ...]
    required_evidence_paths: tuple[str, ...]
    minimum_confidence: Decimal
    insufficient_disposition: str


@dataclass(frozen=True)
class ExposureEvaluation:
    applicable: bool
    amount: Decimal | None = None
    disposition: str | None = None
    reason: str | None = None
    outcome: str = "not-applicable"
    aggregate_key: str | None = None


@dataclass(frozen=True)
class RateEvaluation:
    applicable: bool
    keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceEvaluation:
    applicable: bool
    sufficient: bool = True
    minimum_observed: Decimal | None = None
    missing: tuple[str, ...] = ()


class QuantitativeEvaluator:
    def exposure(
        self,
        *,
        server_url: str,
        tool_name: str,
        identity: str | None,
        declared: Mapping[str, Any],
        trusted: Mapping[str, Any],
        rules: tuple[ExposureRule, ...],
    ) -> tuple[ExposureRule | None, ExposureEvaluation]:
        rule = _matching_rule(rules, server_url, tool_name, identity)
        if rule is None:
            return None, ExposureEvaluation(applicable=False)
        raw_amount = _resolve_path(declared, rule.value_path)
        amount = _decimal(raw_amount)
        if amount is None or amount < 0:
            return rule, ExposureEvaluation(
                applicable=True,
                disposition="Deny",
                reason="exposure-exceeded",
                outcome="missing-or-invalid-value",
            )
        aggregate_key = _build_key("exposure", trusted, rule.aggregate_key_paths)
        if aggregate_key is None:
            return rule, ExposureEvaluation(
                applicable=True,
                amount=amount,
                disposition="Deny",
                reason="exposure-exceeded",
                outcome="missing-aggregate-key",
            )
        if amount > rule.hard_deny_cap:
            return rule, ExposureEvaluation(
                applicable=True,
                amount=amount,
                disposition=rule.hard_cap_disposition,
                reason="exposure-exceeded",
                outcome="hard-cap-exceeded",
                aggregate_key=aggregate_key,
            )
        if amount > rule.escalate_ceiling:
            return rule, ExposureEvaluation(
                applicable=True,
                amount=amount,
                disposition=rule.ceiling_disposition,
                reason="exposure-exceeded",
                outcome="per-action-ceiling-exceeded",
                aggregate_key=aggregate_key,
            )
        return rule, ExposureEvaluation(
            applicable=True,
            amount=amount,
            outcome="within-per-action-limit",
            aggregate_key=aggregate_key,
        )

    def rate(
        self,
        *,
        server_url: str,
        tool_name: str,
        identity: str | None,
        trusted: Mapping[str, Any],
        rules: tuple[RateRule, ...],
    ) -> tuple[RateRule, RateEvaluation] | None:
        rule = _matching_rule(rules, server_url, tool_name, identity)
        if rule is None:
            return None
        keys: list[str] = []
        for path in rule.key_paths:
            key = _build_key(f"rate:{path}", trusted, (path,))
            if key is None:
                return rule, RateEvaluation(applicable=True)
            keys.append(key)
        return rule, RateEvaluation(applicable=True, keys=tuple(keys))

    def evidence(
        self,
        *,
        server_url: str,
        tool_name: str,
        identity: str | None,
        trusted: Mapping[str, Any],
        rules: tuple[EvidenceRule, ...],
    ) -> tuple[EvidenceRule | None, EvidenceEvaluation]:
        rule = _matching_rule(rules, server_url, tool_name, identity)
        if rule is None:
            return None, EvidenceEvaluation(applicable=False)
        confidence = _resolve_path(trusted, rule.confidence_path)
        missing: list[str] = []
        scores: list[Decimal] = []
        if not isinstance(confidence, Mapping):
            missing.extend(f"confidence.{field}" for field in rule.required_confidence_fields)
        else:
            for field in rule.required_confidence_fields:
                score = _decimal(confidence.get(field, _MISSING))
                if score is None or score < 0 or score > 1:
                    missing.append(f"confidence.{field}")
                else:
                    scores.append(score)
        for path in rule.required_evidence_paths:
            value = _resolve_path(trusted, path)
            if value is _MISSING or value is None or value == "" or value == []:
                missing.append(path)
        minimum = min(scores) if scores else None
        sufficient = not missing and minimum is not None and minimum >= rule.minimum_confidence
        return rule, EvidenceEvaluation(
            applicable=True,
            sufficient=sufficient,
            minimum_observed=minimum,
            missing=tuple(missing),
        )


def _matching_rule(rules, server_url: str, tool_name: str, identity: str | None):
    return next(
        (
            rule
            for rule in rules
            if rule.server_url == server_url
            and rule.tool_name == tool_name
            and identity in rule.identities
        ),
        None,
    )


def _resolve_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _decimal(value: Any) -> Decimal | None:
    if value is _MISSING or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _build_key(prefix: str, trusted: Mapping[str, Any], paths: tuple[str, ...]) -> str | None:
    values: list[str] = []
    for path in paths:
        value = _resolve_path(trusted, path)
        if value is _MISSING or value is None or value == "":
            return None
        values.append(str(value))
    return f"{prefix}:" + ":".join(values)

"""Generic, deterministic comparisons between declared and trusted action facts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


_MISSING = object()


@dataclass(frozen=True)
class IntegrityCheck:
    declared_path: str
    operator: str
    trusted_path: str | None = None
    constant: Any = _MISSING
    absolute_tolerance: str | None = None
    required: bool = True


@dataclass(frozen=True)
class IntegrityRule:
    server_url: str
    tool_name: str
    identities: frozenset[str]
    checks: tuple[IntegrityCheck, ...]


@dataclass(frozen=True)
class IntegrityEvaluation:
    applicable: bool
    mismatched_fields: tuple[str, ...] = ()


class IntegrityEvaluator:
    """Evaluate config-defined dotted paths without domain-specific field knowledge."""

    def evaluate(
        self,
        *,
        server_url: str,
        tool_name: str,
        identity: str | None,
        declared: Mapping[str, Any],
        trusted: Mapping[str, Any],
        rules: tuple[IntegrityRule, ...],
        simulated_tampers: frozenset[tuple[str, str]] = frozenset(),
    ) -> IntegrityEvaluation:
        applicable_rules = tuple(
            rule
            for rule in rules
            if rule.server_url == server_url
            and rule.tool_name == tool_name
            and identity in rule.identities
        )
        if not applicable_rules:
            return IntegrityEvaluation(applicable=False)

        mismatches: list[str] = []
        for rule in applicable_rules:
            for check in rule.checks:
                if (tool_name, check.declared_path) in simulated_tampers:
                    mismatches.append(check.declared_path)
                    continue
                declared_value = _resolve_path(declared, check.declared_path)
                expected_value = (
                    check.constant
                    if check.constant is not _MISSING
                    else _resolve_path(trusted, check.trusted_path or "")
                )
                if declared_value is _MISSING or expected_value is _MISSING:
                    if check.required:
                        mismatches.append(check.declared_path)
                    continue
                if not _matches(check, declared_value, expected_value):
                    mismatches.append(check.declared_path)
        return IntegrityEvaluation(
            applicable=True,
            mismatched_fields=tuple(dict.fromkeys(mismatches)),
        )


def _resolve_path(value: Any, path: str) -> Any:
    if not path:
        return _MISSING
    current = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _matches(check: IntegrityCheck, declared: Any, expected: Any) -> bool:
    if check.operator == "exact":
        return type(declared) is type(expected) and declared == expected
    if check.operator == "currency":
        return str(declared).strip().upper() == str(expected).strip().upper()
    if check.operator == "integer":
        try:
            if isinstance(declared, bool) or isinstance(expected, bool):
                return False
            declared_integer = Decimal(str(declared))
            expected_integer = Decimal(str(expected))
            if not declared_integer.is_finite() or not expected_integer.is_finite():
                return False
            if declared_integer != declared_integer.to_integral_value():
                return False
            if expected_integer != expected_integer.to_integral_value():
                return False
            return declared_integer == expected_integer
        except (InvalidOperation, TypeError, ValueError):
            return False
    if check.operator == "decimal":
        try:
            declared_decimal = Decimal(str(declared))
            expected_decimal = Decimal(str(expected))
            tolerance = Decimal(check.absolute_tolerance or "0")
        except (InvalidOperation, TypeError, ValueError):
            return False
        if not all(value.is_finite() for value in (declared_decimal, expected_decimal, tolerance)):
            return False
        return abs(declared_decimal - expected_decimal) <= tolerance
    if check.operator == "normalizedText":
        return _normalized_text(declared) == _normalized_text(expected)
    raise ValueError(f"unsupported integrity operator: {check.operator}")


def _normalized_text(value: Any) -> str:
    return " ".join(str(value).strip().split()).casefold()

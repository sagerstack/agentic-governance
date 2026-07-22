"""Generic deterministic validator for the policy's strict JSON-Schema subset."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
from typing import Any


@dataclass(frozen=True)
class SchemaRule:
    server_url: str
    tool_name: str
    schema: Mapping[str, Any]


@dataclass(frozen=True)
class SchemaEvaluation:
    trusted_server: bool
    schema_found: bool
    valid: bool
    errors: tuple[str, ...] = ()


class SchemaValidator:
    def evaluate(
        self,
        *,
        server_url: str,
        tool_name: str,
        arguments: Any,
        trusted_servers: frozenset[str],
        rules: tuple[SchemaRule, ...],
    ) -> SchemaEvaluation:
        if server_url not in trusted_servers:
            return SchemaEvaluation(False, False, False, ("untrusted-server",))
        rule = next(
            (
                item
                for item in rules
                if item.server_url == server_url and item.tool_name == tool_name
            ),
            None,
        )
        if rule is None:
            return SchemaEvaluation(True, False, True)
        errors: list[str] = []
        _validate(arguments, rule.schema, "$", errors)
        return SchemaEvaluation(True, True, not errors, tuple(errors))


def _validate(value: Any, schema: Mapping[str, Any], path: str, errors: list[str]) -> None:
    expected_types = schema.get("type")
    if isinstance(expected_types, str):
        expected_types = [expected_types]
    if not isinstance(expected_types, list) or not expected_types:
        errors.append(f"{path}:schema-type-missing")
        return
    if not any(_is_type(value, expected) for expected in expected_types):
        errors.append(f"{path}:expected-{'|'.join(expected_types)}")
        return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}:not-in-enum")

    if isinstance(value, Mapping) and "object" in expected_types:
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key}:required")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}.{key}:additional-property")
        for key, child in properties.items():
            if key in value:
                _validate(value[key], child, f"{path}.{key}", errors)

    if isinstance(value, list) and "array" in expected_types and "items" in schema:
        for index, item in enumerate(value):
            _validate(item, schema["items"], f"{path}[{index}]", errors)

    if isinstance(value, str) and "string" in expected_types:
        minimum_length = schema.get("minLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            errors.append(f"{path}:minLength")

    if _is_number(value) and ({"number", "integer"} & set(expected_types)):
        numeric = _decimal(value)
        minimum = _decimal(schema.get("minimum")) if "minimum" in schema else None
        maximum = _decimal(schema.get("maximum")) if "maximum" in schema else None
        if minimum is not None and numeric is not None and numeric < minimum:
            errors.append(f"{path}:minimum")
        if maximum is not None and numeric is not None and numeric > maximum:
            errors.append(f"{path}:maximum")


def _is_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return _is_number(value)
    return False


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float, Decimal))
        and not isinstance(value, bool)
        and not (isinstance(value, float) and not math.isfinite(value))
        and (not isinstance(value, Decimal) or value.is_finite())
    )


def _decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None

"""Load and validate the bundled or operator-supplied governance policy table."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from importlib.resources import files
import json
import logging
import os
from pathlib import Path
from typing import Any

from agentic_governance.core.integrity import IntegrityCheck, IntegrityRule
from agentic_governance.core.quantitative import EvidenceRule, ExposureRule, RateRule
from agentic_governance.core.schema_validation import SchemaRule


logger = logging.getLogger(__name__)
_REQUIRED_SECTIONS = {
    "schemaVersion",
    "servers",
    "controls",
    "trustedServers",
    "allowlist",
    "schemas",
    "identities",
    "mandates",
    "integrityRules",
    "exposure",
    "rate",
    "evidence",
    "contentControls",
}
_SUPPORTED_OPERATORS = {"exact", "currency", "integer", "decimal", "normalizedText"}
_REQUIRED_CONTROLS = {"A2", "A3", "A4", "A5", "A7", "A8", "A9", "A10", "A12"}
_REQUIRED_CONTENT_CONTROLS = {"B1", "B2", "B3", "B4", "B5", "B6"}
_VALID_BREACH_DISPOSITIONS = {"Deny", "Escalate"}


class PolicyConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ControlSpec:
    control_id: str
    name: str
    mode_env: str
    default_mode: str


@dataclass(frozen=True)
class LoadedPolicy:
    servers: Mapping[str, str]
    allowed_pairs: frozenset[tuple[str, str]]
    trusted_servers: frozenset[str]
    schema_rules: tuple[SchemaRule, ...]
    identities: tuple[Mapping[str, str], ...]
    mandates: Mapping[str, frozenset[tuple[str, str]]]
    integrity_rules: tuple[IntegrityRule, ...]
    exposure_rules: tuple[ExposureRule, ...]
    rate_rules: tuple[RateRule, ...]
    evidence_rules: tuple[EvidenceRule, ...]
    controls: Mapping[str, ControlSpec]
    content_controls: Mapping[str, ControlSpec]
    simulated_tampers: frozenset[tuple[str, str]]
    source: str


def load_policy(environ: Mapping[str, str] | None = None) -> LoadedPolicy:
    env = os.environ if environ is None else environ
    override = env.get("AGENTIC_GOV_POLICY_FILE", "").strip()
    if override:
        path = Path(override).expanduser()
        source = str(path)
        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PolicyConfigError(f"cannot read policy file {path}: {exc}") from exc
    else:
        resource = files("agentic_governance.policy").joinpath("default_policy.json")
        source = str(resource)
        raw_text = resource.read_text(encoding="utf-8")

    try:
        document = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise PolicyConfigError(f"invalid JSON policy {source}: {exc}") from exc
    if not isinstance(document, dict):
        raise PolicyConfigError("policy root must be an object")
    missing = _REQUIRED_SECTIONS - document.keys()
    if missing:
        raise PolicyConfigError(f"policy missing required sections: {sorted(missing)}")
    if document["schemaVersion"] != 1:
        raise PolicyConfigError("policy schemaVersion must be 1")

    servers = _load_servers(document["servers"], env)
    controls = _load_controls(document["controls"])
    identities = _load_identities(document["identities"])
    identity_ids = {record["id"] for record in identities}
    allowed_pairs = _load_pair_groups(document["allowlist"], servers, "allowlist")
    trusted_servers = _load_trusted_servers(document["trustedServers"], servers)
    schema_rules = _load_schema_rules(document["schemas"], servers, allowed_pairs)
    if any(server_url not in trusted_servers for server_url, _ in allowed_pairs):
        raise PolicyConfigError("every allowlisted server must be listed in trustedServers")
    mandates = _load_mandates(document["mandates"], servers, identity_ids)
    integrity_rules = _load_integrity_rules(
        document["integrityRules"], servers, identity_ids
    )
    exposure_rules = _load_exposure_rules(document["exposure"], servers, identity_ids)
    rate_rules = _load_rate_rules(document["rate"], servers, identity_ids)
    evidence_rules = _load_evidence_rules(document["evidence"], servers, identity_ids)
    content_controls = _load_content_controls(document["contentControls"])
    simulated_tampers = _load_simulated_tampers(env, integrity_rules)
    return LoadedPolicy(
        servers=servers,
        allowed_pairs=allowed_pairs,
        trusted_servers=trusted_servers,
        schema_rules=schema_rules,
        identities=identities,
        mandates=mandates,
        integrity_rules=integrity_rules,
        exposure_rules=exposure_rules,
        rate_rules=rate_rules,
        evidence_rules=evidence_rules,
        controls=controls,
        content_controls=content_controls,
        simulated_tampers=simulated_tampers,
        source=source,
    )


def _load_servers(raw: Any, env: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(raw, dict) or not raw:
        raise PolicyConfigError("servers must be a non-empty object")
    resolved: dict[str, str] = {}
    for symbol, spec in raw.items():
        if not isinstance(symbol, str) or not isinstance(spec, dict):
            raise PolicyConfigError("each server must map a symbol to an object")
        env_name = spec.get("env")
        default = spec.get("default")
        if not isinstance(env_name, str) or not isinstance(default, str) or not default:
            raise PolicyConfigError(f"server {symbol!r} requires string env and default")
        resolved[symbol] = env.get(env_name, default)
    return resolved


def _load_controls(raw: Any) -> dict[str, ControlSpec]:
    if not isinstance(raw, dict):
        raise PolicyConfigError("controls must be an object")
    missing = _REQUIRED_CONTROLS - raw.keys()
    if missing:
        raise PolicyConfigError(f"controls missing required entries: {sorted(missing)}")
    controls: dict[str, ControlSpec] = {}
    for control_id, spec in raw.items():
        if not isinstance(spec, dict):
            raise PolicyConfigError(f"control {control_id} must be an object")
        name, mode_env, default_mode = (
            spec.get("name"),
            spec.get("modeEnv"),
            spec.get("defaultMode"),
        )
        if not all(isinstance(value, str) and value for value in (name, mode_env)):
            raise PolicyConfigError(f"control {control_id} requires name and modeEnv")
        if default_mode not in {"enforce", "observe", "off"}:
            raise PolicyConfigError(f"control {control_id} has invalid defaultMode")
        controls[control_id] = ControlSpec(control_id, name, mode_env, default_mode)
    return controls


def _load_content_controls(raw: Any) -> dict[str, ControlSpec]:
    if not isinstance(raw, dict):
        raise PolicyConfigError("contentControls must be an object")
    missing = _REQUIRED_CONTENT_CONTROLS - raw.keys()
    if missing:
        raise PolicyConfigError(f"contentControls missing required entries: {sorted(missing)}")
    controls: dict[str, ControlSpec] = {}
    for control_id, spec in raw.items():
        if not isinstance(spec, dict):
            raise PolicyConfigError(f"contentControl {control_id} must be an object")
        name, mode_env, default_mode = (
            spec.get("name"),
            spec.get("modeEnv"),
            spec.get("defaultMode"),
        )
        if not all(isinstance(value, str) and value for value in (name, mode_env)):
            raise PolicyConfigError(f"contentControl {control_id} requires name and modeEnv")
        if default_mode not in {"enforce", "observe", "off"}:
            raise PolicyConfigError(f"contentControl {control_id} has invalid defaultMode")
        controls[control_id] = ControlSpec(control_id, name, mode_env, default_mode)
    return controls


def _load_trusted_servers(raw: Any, servers: Mapping[str, str]) -> frozenset[str]:
    if not isinstance(raw, list) or not raw or not all(isinstance(item, str) for item in raw):
        raise PolicyConfigError("trustedServers must be a non-empty string array")
    if len(raw) != len(set(raw)) or not set(raw) <= set(servers):
        raise PolicyConfigError("trustedServers contains duplicates or unknown symbols")
    return frozenset(servers[symbol] for symbol in raw)


def _load_schema_rules(
    raw: Any,
    servers: Mapping[str, str],
    allowed_pairs: frozenset[tuple[str, str]],
) -> tuple[SchemaRule, ...]:
    if not isinstance(raw, list):
        raise PolicyConfigError("schemas must be an array")
    rules: list[SchemaRule] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PolicyConfigError(f"schemas[{index}] must be an object")
        symbol, tool, schema = item.get("server"), item.get("tool"), item.get("schema")
        if symbol not in servers or not isinstance(tool, str) or not tool:
            raise PolicyConfigError(f"schemas[{index}] has invalid server/tool")
        if not isinstance(schema, dict):
            raise PolicyConfigError(f"schemas[{index}].schema must be an object")
        pair = (servers[symbol], tool)
        if pair in seen:
            raise PolicyConfigError(f"duplicate schema for {symbol}:{tool}")
        seen.add(pair)
        _validate_schema_definition(schema, f"schemas[{index}].schema")
        rules.append(SchemaRule(pair[0], pair[1], schema))
    if seen != set(allowed_pairs):
        missing = set(allowed_pairs) - seen
        extra = seen - set(allowed_pairs)
        raise PolicyConfigError(
            f"schemas must exactly cover allowlist pairs; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return tuple(rules)


def _validate_schema_definition(schema: Any, label: str) -> None:
    if not isinstance(schema, dict):
        raise PolicyConfigError(f"{label} must be an object")
    supported_keywords = {
        "type",
        "required",
        "additionalProperties",
        "properties",
        "items",
        "enum",
        "minimum",
        "maximum",
        "minLength",
    }
    unknown = set(schema) - supported_keywords
    if unknown:
        raise PolicyConfigError(f"{label} has unsupported keywords: {sorted(unknown)}")
    raw_types = schema.get("type")
    types = [raw_types] if isinstance(raw_types, str) else raw_types
    supported_types = {"object", "array", "string", "number", "integer", "boolean", "null"}
    if not isinstance(types, list) or not types or not all(item in supported_types for item in types):
        raise PolicyConfigError(f"{label} has invalid type")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if "object" in types:
        if not isinstance(properties, dict) or not all(isinstance(key, str) for key in properties):
            raise PolicyConfigError(f"{label}.properties must be an object")
        if not isinstance(required, list) or not all(isinstance(key, str) for key in required):
            raise PolicyConfigError(f"{label}.required must be a string array")
        if not set(required) <= set(properties):
            raise PolicyConfigError(f"{label}.required references unknown properties")
        if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], bool):
            raise PolicyConfigError(f"{label}.additionalProperties must be boolean")
        for key, child in properties.items():
            _validate_schema_definition(child, f"{label}.properties.{key}")
    if "items" in schema:
        if "array" not in types:
            raise PolicyConfigError(f"{label}.items requires array type")
        _validate_schema_definition(schema["items"], f"{label}.items")
    if "enum" in schema and not isinstance(schema["enum"], list):
        raise PolicyConfigError(f"{label}.enum must be an array")
    if "minLength" in schema and (
        not isinstance(schema["minLength"], int) or schema["minLength"] < 0
    ):
        raise PolicyConfigError(f"{label}.minLength must be a non-negative integer")
    for keyword in ("minimum", "maximum"):
        if keyword in schema:
            _positive_decimal(schema[keyword], f"{label}.{keyword}", allow_zero=True)


def _load_identities(raw: Any) -> tuple[Mapping[str, str], ...]:
    if not isinstance(raw, list) or not raw:
        raise PolicyConfigError("identities must be a non-empty array")
    records: list[Mapping[str, str]] = []
    seen: set[str] = set()
    for record in raw:
        if not isinstance(record, dict):
            raise PolicyConfigError("identity entries must be objects")
        if not all(isinstance(record.get(key), str) and record[key] for key in ("id", "role", "dept")):
            raise PolicyConfigError("each identity requires non-empty id, role, and dept")
        if record["id"] in seen:
            raise PolicyConfigError(f"duplicate identity: {record['id']}")
        seen.add(record["id"])
        records.append({key: record[key] for key in ("id", "role", "dept")})
    return tuple(records)


def _load_pair_groups(raw: Any, servers: Mapping[str, str], section: str) -> frozenset[tuple[str, str]]:
    if not isinstance(raw, list):
        raise PolicyConfigError(f"{section} must be an array")
    pairs: set[tuple[str, str]] = set()
    for group in raw:
        if not isinstance(group, dict):
            raise PolicyConfigError(f"{section} entries must be objects")
        server_symbol, tools = group.get("server"), group.get("tools")
        if server_symbol not in servers:
            raise PolicyConfigError(f"{section} references unknown server {server_symbol!r}")
        if not isinstance(tools, list) or not tools or not all(isinstance(tool, str) and tool for tool in tools):
            raise PolicyConfigError(f"{section} tools must be a non-empty string array")
        pairs.update((servers[server_symbol], tool) for tool in tools)
    return frozenset(pairs)


def _load_mandates(
    raw: Any, servers: Mapping[str, str], identity_ids: set[str]
) -> dict[str, frozenset[tuple[str, str]]]:
    if not isinstance(raw, dict) or set(raw) != identity_ids:
        raise PolicyConfigError("mandates must contain exactly every configured identity")
    return {
        identity_id: _load_pair_groups(groups, servers, f"mandates.{identity_id}")
        for identity_id, groups in raw.items()
    }


def _load_integrity_rules(
    raw: Any, servers: Mapping[str, str], identity_ids: set[str]
) -> tuple[IntegrityRule, ...]:
    if not isinstance(raw, list):
        raise PolicyConfigError("integrityRules must be an array")
    rules: list[IntegrityRule] = []
    for index, raw_rule in enumerate(raw):
        if not isinstance(raw_rule, dict):
            raise PolicyConfigError(f"integrityRules[{index}] must be an object")
        server_symbol = raw_rule.get("server")
        tool_name = raw_rule.get("tool")
        identities = raw_rule.get("identities")
        checks = raw_rule.get("checks")
        if server_symbol not in servers or not isinstance(tool_name, str) or not tool_name:
            raise PolicyConfigError(f"integrityRules[{index}] has invalid server/tool")
        if not isinstance(identities, list) or not identities or not set(identities) <= identity_ids:
            raise PolicyConfigError(f"integrityRules[{index}] has invalid identities")
        if not isinstance(checks, list) or not checks:
            raise PolicyConfigError(f"integrityRules[{index}] requires checks")
        parsed_checks = tuple(_load_integrity_check(check, index) for check in checks)
        rules.append(
            IntegrityRule(
                server_url=servers[server_symbol],
                tool_name=tool_name,
                identities=frozenset(identities),
                checks=parsed_checks,
            )
        )
    return tuple(rules)


def _load_integrity_check(raw: Any, rule_index: int) -> IntegrityCheck:
    if not isinstance(raw, dict):
        raise PolicyConfigError(f"integrityRules[{rule_index}] checks must be objects")
    declared, operator = raw.get("declared"), raw.get("operator")
    if not isinstance(declared, str) or not declared or operator not in _SUPPORTED_OPERATORS:
        raise PolicyConfigError(f"integrityRules[{rule_index}] has invalid check")
    has_trusted, has_constant = "trusted" in raw, "constant" in raw
    if has_trusted == has_constant:
        raise PolicyConfigError("integrity check requires exactly one of trusted or constant")
    required = raw.get("required", True)
    if not isinstance(required, bool):
        raise PolicyConfigError("integrity check required must be boolean")
    absolute_tolerance = raw.get("absoluteTolerance")
    if operator == "decimal":
        try:
            tolerance = Decimal(str(absolute_tolerance or "0"))
        except InvalidOperation as exc:
            raise PolicyConfigError("decimal absoluteTolerance must be numeric") from exc
        if not tolerance.is_finite() or tolerance < 0:
            raise PolicyConfigError("decimal absoluteTolerance must be finite and non-negative")
    elif absolute_tolerance is not None:
        raise PolicyConfigError("absoluteTolerance is valid only for decimal checks")
    kwargs = {
        "declared_path": declared,
        "operator": operator,
        "absolute_tolerance": absolute_tolerance,
        "required": required,
    }
    if has_trusted:
        if not isinstance(raw["trusted"], str) or not raw["trusted"]:
            raise PolicyConfigError("integrity trusted path must be non-empty")
        kwargs["trusted_path"] = raw["trusted"]
    else:
        kwargs["constant"] = raw["constant"]
    return IntegrityCheck(**kwargs)


def _load_exposure_rules(
    raw: Any, servers: Mapping[str, str], identity_ids: set[str]
) -> tuple[ExposureRule, ...]:
    if not isinstance(raw, list):
        raise PolicyConfigError("exposure must be an array")
    rules: list[ExposureRule] = []
    for index, item in enumerate(raw):
        server_url, tool, identities = _load_quantitative_scope(
            item, servers, identity_ids, f"exposure[{index}]"
        )
        per_action = item.get("perAction")
        aggregate = item.get("aggregate")
        if not isinstance(per_action, dict) or not isinstance(aggregate, dict):
            raise PolicyConfigError(f"exposure[{index}] requires perAction and aggregate")
        ceiling = _positive_decimal(per_action.get("escalateAbove"), "escalateAbove")
        hard_cap = _positive_decimal(per_action.get("hardDenyAbove"), "hardDenyAbove")
        aggregate_limit = _positive_decimal(aggregate.get("limit"), "aggregate.limit")
        if hard_cap <= ceiling:
            raise PolicyConfigError("exposure hard cap must exceed escalate ceiling")
        ceiling_disposition = _disposition(per_action.get("ceilingDisposition"))
        hard_disposition = _disposition(per_action.get("hardCapDisposition"))
        aggregate_disposition = _disposition(aggregate.get("exceededDisposition"))
        value_path = item.get("valuePath")
        currency = item.get("currency")
        key_paths = aggregate.get("keyPaths")
        window_seconds = aggregate.get("windowSeconds")
        if not isinstance(value_path, str) or not value_path or not isinstance(currency, str) or not currency:
            raise PolicyConfigError(f"exposure[{index}] requires valuePath and currency")
        _validate_paths_and_window(key_paths, window_seconds, f"exposure[{index}].aggregate")
        rules.append(
            ExposureRule(
                server_url=server_url,
                tool_name=tool,
                identities=frozenset(identities),
                value_path=value_path,
                currency=currency,
                escalate_ceiling=ceiling,
                hard_deny_cap=hard_cap,
                ceiling_disposition=ceiling_disposition,
                hard_cap_disposition=hard_disposition,
                aggregate_limit=aggregate_limit,
                aggregate_window_seconds=window_seconds,
                aggregate_key_paths=tuple(key_paths),
                aggregate_disposition=aggregate_disposition,
            )
        )
    return tuple(rules)


def _load_rate_rules(
    raw: Any, servers: Mapping[str, str], identity_ids: set[str]
) -> tuple[RateRule, ...]:
    if not isinstance(raw, list):
        raise PolicyConfigError("rate must be an array")
    rules: list[RateRule] = []
    for index, item in enumerate(raw):
        server_url, tool, identities = _load_quantitative_scope(
            item, servers, identity_ids, f"rate[{index}]"
        )
        key_paths = item.get("keyPaths")
        window_seconds = item.get("windowSeconds")
        max_attempts = item.get("maxAttempts")
        _validate_paths_and_window(key_paths, window_seconds, f"rate[{index}]")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts <= 0:
            raise PolicyConfigError(f"rate[{index}] maxAttempts must be a positive integer")
        rules.append(
            RateRule(
                server_url=server_url,
                tool_name=tool,
                identities=frozenset(identities),
                key_paths=tuple(key_paths),
                max_attempts=max_attempts,
                window_seconds=window_seconds,
                exceeded_disposition=_disposition(item.get("exceededDisposition")),
            )
        )
    return tuple(rules)


def _load_evidence_rules(
    raw: Any, servers: Mapping[str, str], identity_ids: set[str]
) -> tuple[EvidenceRule, ...]:
    if not isinstance(raw, list):
        raise PolicyConfigError("evidence must be an array")
    rules: list[EvidenceRule] = []
    for index, item in enumerate(raw):
        server_url, tool, identities = _load_quantitative_scope(
            item, servers, identity_ids, f"evidence[{index}]"
        )
        confidence_path = item.get("confidencePath")
        confidence_fields = item.get("requiredConfidenceFields")
        evidence_paths = item.get("requiredEvidencePaths")
        if not isinstance(confidence_path, str) or not confidence_path:
            raise PolicyConfigError(f"evidence[{index}] requires confidencePath")
        for value, name in (
            (confidence_fields, "requiredConfidenceFields"),
            (evidence_paths, "requiredEvidencePaths"),
        ):
            if not isinstance(value, list) or not value or not all(isinstance(path, str) and path for path in value):
                raise PolicyConfigError(f"evidence[{index}] {name} must be a non-empty string array")
        minimum = _positive_decimal(item.get("minimumConfidence"), "minimumConfidence", allow_zero=True)
        if minimum > 1:
            raise PolicyConfigError("minimumConfidence cannot exceed 1")
        rules.append(
            EvidenceRule(
                server_url=server_url,
                tool_name=tool,
                identities=frozenset(identities),
                confidence_path=confidence_path,
                required_confidence_fields=tuple(confidence_fields),
                required_evidence_paths=tuple(evidence_paths),
                minimum_confidence=minimum,
                insufficient_disposition=_disposition(item.get("insufficientDisposition")),
            )
        )
    return tuple(rules)


def _load_quantitative_scope(
    item: Any,
    servers: Mapping[str, str],
    identity_ids: set[str],
    label: str,
) -> tuple[str, str, list[str]]:
    if not isinstance(item, dict):
        raise PolicyConfigError(f"{label} must be an object")
    server_symbol, tool, identities = item.get("server"), item.get("tool"), item.get("identities")
    if server_symbol not in servers or not isinstance(tool, str) or not tool:
        raise PolicyConfigError(f"{label} has invalid server/tool")
    if not isinstance(identities, list) or not identities or not set(identities) <= identity_ids:
        raise PolicyConfigError(f"{label} has invalid identities")
    return servers[server_symbol], tool, identities


def _positive_decimal(value: Any, label: str, *, allow_zero: bool = False) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PolicyConfigError(f"{label} must be numeric") from exc
    if not parsed.is_finite() or parsed < 0 or (not allow_zero and parsed == 0):
        raise PolicyConfigError(f"{label} must be finite and {'non-negative' if allow_zero else 'positive'}")
    return parsed


def _disposition(value: Any) -> str:
    if value not in _VALID_BREACH_DISPOSITIONS:
        raise PolicyConfigError(f"breach disposition must be one of {sorted(_VALID_BREACH_DISPOSITIONS)}")
    return value


def _validate_paths_and_window(paths: Any, window_seconds: Any, label: str) -> None:
    if not isinstance(paths, list) or not paths or not all(isinstance(path, str) and path for path in paths):
        raise PolicyConfigError(f"{label} keyPaths must be a non-empty string array")
    if not isinstance(window_seconds, int) or isinstance(window_seconds, bool) or window_seconds <= 0:
        raise PolicyConfigError(f"{label} windowSeconds must be a positive integer")


def _load_simulated_tampers(
    env: Mapping[str, str], rules: tuple[IntegrityRule, ...]
) -> frozenset[tuple[str, str]]:
    known = {
        (rule.tool_name, check.declared_path)
        for rule in rules
        for check in rule.checks
    }
    selected: set[tuple[str, str]] = set()
    for raw_entry in env.get("AGENTIC_GOV_SIMULATE_TAMPER", "").split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        if entry.count(":") != 1:
            logger.warning("Ignoring malformed AGENTIC_GOV_SIMULATE_TAMPER entry: %r", entry)
            continue
        tool_name, field = (part.strip() for part in entry.split(":", 1))
        pair = (tool_name, field)
        if pair not in known:
            logger.warning("Ignoring unknown AGENTIC_GOV_SIMULATE_TAMPER entry: %r", entry)
            continue
        selected.add(pair)
    return frozenset(selected)

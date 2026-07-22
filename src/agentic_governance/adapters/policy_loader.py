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


logger = logging.getLogger(__name__)
_REQUIRED_SECTIONS = {
    "schemaVersion",
    "servers",
    "controls",
    "allowlist",
    "identities",
    "mandates",
    "integrityRules",
}
_SUPPORTED_OPERATORS = {"exact", "currency", "integer", "decimal", "normalizedText"}
_REQUIRED_CONTROLS = {"A2", "A3", "A4", "A5", "A12"}


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
    identities: tuple[Mapping[str, str], ...]
    mandates: Mapping[str, frozenset[tuple[str, str]]]
    integrity_rules: tuple[IntegrityRule, ...]
    controls: Mapping[str, ControlSpec]
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
    mandates = _load_mandates(document["mandates"], servers, identity_ids)
    integrity_rules = _load_integrity_rules(
        document["integrityRules"], servers, identity_ids
    )
    simulated_tampers = _load_simulated_tampers(env, integrity_rules)
    return LoadedPolicy(
        servers=servers,
        allowed_pairs=allowed_pairs,
        identities=identities,
        mandates=mandates,
        integrity_rules=integrity_rules,
        controls=controls,
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

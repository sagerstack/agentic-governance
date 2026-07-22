"""Governance-owned verified identities and exact MCP capability mandates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging
import os

from agentic_governance.adapters.policy_loader import LoadedPolicy, load_policy


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IdentityRecord:
    id: str
    role: str
    dept: str


@dataclass(frozen=True)
class Mandate:
    identity_id: str
    allowed_pairs: frozenset[tuple[str, str]]

    def allows(self, server_url: str, tool_name: str) -> bool:
        return (server_url, tool_name) in self.allowed_pairs


@dataclass(frozen=True)
class DemoIdentityOverrideConfig:
    """Load-time identity override used only for demos and Level-1 testing."""

    forced_identity: str | None = None

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> "DemoIdentityOverrideConfig":
        env = os.environ if environ is None else environ
        forced_identity = env.get("AGENTIC_GOV_FORCE_IDENTITY", "").strip() or None
        return cls(forced_identity=forced_identity)


@dataclass(frozen=True)
class IdentityMandateConfig:
    identities: Mapping[str, IdentityRecord]
    mandates: Mapping[str, Mandate]
    revoked_grants: frozenset[tuple[str, str]] = frozenset()

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> "IdentityMandateConfig":
        env = os.environ if environ is None else environ
        return cls.from_policy(load_policy(env), env)

    @classmethod
    def from_policy(
        cls,
        policy: LoadedPolicy,
        environ: Mapping[str, str] | None = None,
    ) -> "IdentityMandateConfig":
        env = os.environ if environ is None else environ
        identities = {
            record["id"]: IdentityRecord(record["id"], record["role"], record["dept"])
            for record in policy.identities
        }
        grants = {
            identity_id: set(allowed_pairs)
            for identity_id, allowed_pairs in policy.mandates.items()
        }
        revoked_grants: set[tuple[str, str]] = set()
        for raw_entry in env.get("AGENTIC_GOV_REVOKE_GRANTS", "").split(","):
            entry = raw_entry.strip()
            if not entry:
                continue
            if entry.count(":") != 1:
                logger.warning("Ignoring malformed AGENTIC_GOV_REVOKE_GRANTS entry: %r", entry)
                continue
            identity_id, wire_tool = (part.strip() for part in entry.split(":", 1))
            identity_grants = grants.get(identity_id)
            if not identity_id or not wire_tool or identity_grants is None:
                logger.warning("Ignoring unknown AGENTIC_GOV_REVOKE_GRANTS entry: %r", entry)
                continue
            matching_pairs = {pair for pair in identity_grants if pair[1] == wire_tool}
            if not matching_pairs:
                logger.warning("Ignoring unknown AGENTIC_GOV_REVOKE_GRANTS entry: %r", entry)
                continue
            identity_grants.difference_update(matching_pairs)
            revoked_grants.add((identity_id, wire_tool))

        mandates = {
            identity_id: Mandate(identity_id, frozenset(allowed_pairs))
            for identity_id, allowed_pairs in grants.items()
        }
        return cls(
            identities=identities,
            mandates=mandates,
            revoked_grants=frozenset(revoked_grants),
        )

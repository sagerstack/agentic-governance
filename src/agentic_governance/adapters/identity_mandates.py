"""Governance-owned verified identities and exact MCP capability mandates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging
import os


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
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "IdentityMandateConfig":
        env = os.environ if environ is None else environ
        rag = env.get("RAG_MCP_URL", "http://mcp-rag:8000/mcp/")
        db = env.get("DB_MCP_URL", "http://mcp-db:8000/mcp/")
        currency = env.get("CURRENCY_MCP_URL", "http://mcp-currency:8000/mcp/")

        identity_details = {
            "intake": ("claim-intake-agent", "claims"),
            "compliance": ("policy-compliance-agent", "risk"),
            "fraud": ("fraud-detection-agent", "risk"),
            "advisor": ("claim-advisor-agent", "claims"),
            "humanEscalation": ("human-escalation-workflow", "claims"),
            "markAiReviewed": ("review-status-workflow", "claims"),
            "application": ("web-application", "platform"),
        }
        grants = {
            "intake": {
                (db, "getClaimSchema"),
                (rag, "searchPolicies"),
                (currency, "convertCurrency"),
                (db, "insertClaim"),
                (db, "insertAuditLog"),
            },
            "compliance": {(rag, "searchPolicies"), (db, "insertAuditLog")},
            "fraud": {(db, "executeQuery"), (db, "insertAuditLog")},
            "advisor": {
                (rag, "searchPolicies"),
                (db, "updateClaimStatus"),
                (db, "insertAuditLog"),
            },
            "humanEscalation": {(db, "updateClaimStatus")},
            "markAiReviewed": {(db, "updateClaimStatus")},
            "application": {
                (db, "insertClaim"),
                (db, "executeQuery"),
                (db, "insertAuditLog"),
            },
        }
        identities = {
            identity_id: IdentityRecord(identity_id, role, dept)
            for identity_id, (role, dept) in identity_details.items()
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
            matching_pairs = {
                pair for pair in identity_grants if pair[1] == wire_tool
            }
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

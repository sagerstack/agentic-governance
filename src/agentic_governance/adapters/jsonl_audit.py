from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentic_governance.core.audit_events import finalize_entry, new_entry_id, utc_now_iso
from agentic_governance.core.disposition import Disposition
from agentic_governance.core.envelope import GovernanceEnvelope
from agentic_governance.core.content_envelope import ContentEnvelope, _stable_hash as _content_hash
from agentic_governance.core.content_disposition import ContentDisposition as ContentDisposition_


class JsonlAuditSink:
    def __init__(self, path: str | Path) -> None:
        configured_path = Path(path)
        if configured_path.suffix == ".jsonl":
            # An explicit file remains an exact, backward-compatible override.
            self._path = configured_path
        else:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            random_suffix = uuid4().hex[:6]
            self._path = configured_path / f"audit-{timestamp}-{random_suffix}.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._failure_path = self._path.with_suffix(".failures.jsonl")
        self._prev_entry_hash = self._load_prev_entry_hash()

    @property
    def path(self) -> Path:
        """The file selected once for this runtime's audit events."""
        return self._path

    async def append(self, envelope: GovernanceEnvelope, disposition: Disposition) -> dict[str, Any]:
        entry = build_audit_entry(envelope, disposition)
        return self._write_entry(entry)

    async def append_content(self, envelope: ContentEnvelope, disposition: ContentDisposition_) -> dict[str, Any]:
        entry = build_content_audit_entry(envelope, disposition)
        return self._write_entry(entry)

    async def append_custom(self, event: dict[str, Any]) -> dict[str, Any]:
        return self._write_entry(event)

    def _write_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        finalized = finalize_entry(entry, prev_entry_hash=self._prev_entry_hash)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(finalized, sort_keys=True) + "\n")
        self._prev_entry_hash = finalized["entryHash"]
        return finalized

    def _load_prev_entry_hash(self) -> str | None:
        if not self._path.exists():
            return None
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
            if not lines:
                return None
            last = json.loads(lines[-1])
            return last.get("entryHash")
        except Exception:
            return None

    def record_failure_event(self, event: dict[str, Any]) -> None:
        try:
            with self._failure_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, sort_keys=True) + "\n")
        except Exception:
            return


def build_audit_entry(envelope: GovernanceEnvelope, disposition: Disposition) -> dict[str, Any]:
    escalation = None
    if disposition.decision == "Escalate":
        escalation = {
            "source": "governance",
            "reason": disposition.reasons[0] if disposition.reasons else "escalated",
        }
    return {
        "eventType": "action_governance",
        "entryId": new_entry_id(),
        "timestamp": envelope.ts,
        "actorType": "agent",
        "controlGroup": "A",
        "controlId": None,
        "decision": disposition.decision,
        "result": disposition.decision,
        "reasons": list(disposition.reasons),
        "claimId": envelope.correlation_id,
        "dbClaimId": envelope.trusted_context.get("dbClaimId"),
        "policyVersion": disposition.policy_version,
        "payloadRef": envelope.params_ref,
        "envelope": envelope.to_dict(),
        "envelopeId": envelope.envelope_id,
        "correlationId": envelope.correlation_id,
        "agentIdentity": asdict(envelope.agent_identity),
        "disposition": {
            "decision": disposition.decision,
            "reasons": list(disposition.reasons),
            "firedControls": [
                {
                    "controlId": control.control_id,
                    "name": control.name,
                    "result": control.result,
                    "threshold": control.threshold,
                    "observedValue": control.observed_value,
                }
                for control in disposition.fired_controls
            ],
            "controlStates": [
                {
                    "controlId": state.control_id,
                    "mode": state.mode,
                    "outcome": state.outcome,
                }
                for state in disposition.control_states
            ],
            "escalation": escalation,
            "policyVersion": disposition.policy_version,
            "latencyMs": disposition.latency_ms,
        },
        "controlVersions": {"policyVersion": disposition.policy_version},
        "timings": {"latencyMs": disposition.latency_ms},
        "prevEntryHash": None,
        "entryHash": None,
        "evidenceRefs": {
            "paramsRef": envelope.params_ref,
            "graphStateSnapshotRef": envelope.context_metadata.get("graphStateSnapshotRef"),
            "extractedReceiptRef": envelope.context_metadata.get("extractedReceiptRef"),
        },
    }


def build_content_audit_entry(
    envelope: ContentEnvelope,
    disposition: ContentDisposition_,
) -> dict[str, Any]:
    """Build a PII-safe audit entry for a content governance decision."""
    content_transformed_ref = None
    if disposition.decision == "Transform" and disposition.content_out is not None:
        content_transformed_ref = _content_hash(disposition.content_out)

    return {
        "eventType": "content_governance",
        "entryId": new_entry_id(),
        "timestamp": utc_now_iso(),
        "actorType": "agent",
        "controlGroup": "B",
        "controlId": None,
        "decision": disposition.decision,
        "result": disposition.decision,
        "reasons": list(disposition.reasons),
        "claimId": envelope.correlation_id,
        "dbClaimId": envelope.context_metadata.get("dbClaimId"),
        "policyVersion": disposition.policy_version,
        "payloadRef": envelope.content_ref,
        "contentId": envelope.content_id,
        "correlationId": envelope.correlation_id,
        "agentIdentity": envelope.agent_identity,
        "contentType": envelope.content_type,
        "contentRef": envelope.content_ref,          # hash, not raw
        "contentTransformedRef": content_transformed_ref,  # hash of transformed, not raw
        "disposition": {
            "decision": disposition.decision,
            "reasons": list(disposition.reasons),
            "firedControls": [
                {
                    "controlId": c.control_id,
                    "name": c.name,
                    "result": c.result,
                    "signalValue": c.signal_value,
                    "entityTypes": list(c.entity_types),
                }
                for c in disposition.fired_controls
            ],
            "policyVersion": disposition.policy_version,
            "latencyMs": disposition.latency_ms,
        },
        "contextMetadata": envelope.context_metadata,
        "prevEntryHash": None,
        "entryHash": None,
    }


def build_custom_audit_event(
    *,
    event_type: str,
    control_group: str,
    actor_type: str,
    decision: str,
    result: str,
    reasons: list[str] | tuple[str, ...],
    correlation_id: str,
    claim_id: str,
    db_claim_id: int | None,
    policy_version: str,
    payload_ref: Any | None = None,
    agent_identity: str | dict[str, Any] | None = None,
    reviewer_identity: str | dict[str, Any] | None = None,
    control_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "eventType": event_type,
        "entryId": new_entry_id(),
        "timestamp": utc_now_iso(),
        "actorType": actor_type,
        "controlGroup": control_group,
        "controlId": control_id,
        "decision": decision,
        "result": result,
        "reasons": list(reasons),
        "claimId": claim_id,
        "dbClaimId": db_claim_id,
        "correlationId": correlation_id,
        "policyVersion": policy_version,
        "payloadRef": payload_ref,
        "agentIdentity": agent_identity,
        "reviewerIdentity": reviewer_identity,
        "details": details or {},
        "prevEntryHash": None,
        "entryHash": None,
    }


def build_failure_audit_event(
    *,
    claim_id: str,
    correlation_id: str,
    db_claim_id: int | None,
    component: str,
    error: str,
    details: dict[str, Any] | None = None,
    policy_version: str = "unknown",
) -> dict[str, Any]:
    merged_details = {"component": component, "error": error}
    if details:
        merged_details.update(details)
    return build_custom_audit_event(
        event_type="system_failure",
        control_group="D",
        actor_type="system",
        decision="failure",
        result="failure",
        reasons=[component],
        correlation_id=correlation_id,
        claim_id=claim_id,
        db_claim_id=db_claim_id,
        policy_version=policy_version,
        details=merged_details,
    )

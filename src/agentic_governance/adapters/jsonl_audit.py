from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentic_governance.core.disposition import Disposition
from agentic_governance.core.envelope import GovernanceEnvelope


class JsonlAuditSink:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def append(self, envelope: GovernanceEnvelope, disposition: Disposition) -> None:
        entry = build_audit_entry(envelope, disposition)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")


def build_audit_entry(envelope: GovernanceEnvelope, disposition: Disposition) -> dict[str, Any]:
    return {
        "entryId": str(uuid4()),
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
            "policyVersion": disposition.policy_version,
            "latencyMs": disposition.latency_ms,
        },
        "controlVersions": {"policyVersion": disposition.policy_version},
        "timings": {"latencyMs": disposition.latency_ms},
        "prevEntryHash": None,
        "evidenceRefs": {
            "paramsRef": envelope.params_ref,
            "graphStateSnapshotRef": envelope.context_metadata.get("graphStateSnapshotRef"),
            "extractedReceiptRef": envelope.context_metadata.get("extractedReceiptRef"),
        },
    }

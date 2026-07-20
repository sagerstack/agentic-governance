from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4


REDACT_KEYS = {"receipt", "image", "imagePath", "rawReceipt", "payload", "content", "body"}


@dataclass(frozen=True)
class AgentIdentity:
    id: str | None
    role: str | None = None
    dept: str | None = None
    bound_human: str | None = None


@dataclass(frozen=True)
class GovernanceEnvelope:
    envelope_id: str
    correlation_id: str
    ts: str
    agent_identity: AgentIdentity
    action_type: str
    tool_name: str
    mcp_server: str
    params_ref: dict[str, Any]
    action_trace: tuple[Any, ...] = ()
    context_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["envelopeId"] = data.pop("envelope_id")
        data["correlationId"] = data.pop("correlation_id")
        data["agentIdentity"] = data.pop("agent_identity")
        data["actionType"] = data.pop("action_type")
        data["toolName"] = data.pop("tool_name")
        data["mcpServer"] = data.pop("mcp_server")
        data["paramsRef"] = data.pop("params_ref")
        data["actionTrace"] = data.pop("action_trace")
        data["contextMetadata"] = data.pop("context_metadata")
        return data


def build_envelope(
    *,
    server_url: str,
    tool_name: str,
    arguments: dict[str, Any] | None,
    employee_id: str | None,
    extracted_receipt: Any,
    session_claim_id: str | None,
    node_identity: str | None,
) -> GovernanceEnvelope:
    correlation_id = session_claim_id or _stable_hash({"employeeId": employee_id, "toolName": tool_name})
    metadata = {
        "policyVersion": "slice-0",
        "graphStateSnapshotRef": _stable_hash(
            {
                "employeeId": employee_id,
                "sessionClaimId": session_claim_id,
                "nodeIdentity": node_identity,
                "hasExtractedReceipt": extracted_receipt is not None,
            }
        ),
        "mandateId": None,
        "employeeIdHash": _hash_or_none(employee_id),
    }
    if extracted_receipt is not None:
        metadata["extractedReceiptRef"] = _stable_hash(extracted_receipt)
    return GovernanceEnvelope(
        envelope_id=str(uuid4()),
        correlation_id=correlation_id,
        ts=datetime.now(timezone.utc).isoformat(),
        agent_identity=AgentIdentity(id=node_identity),
        action_type="mcp_call",
        tool_name=tool_name,
        mcp_server=server_url,
        params_ref=redact_params(arguments or {}),
        context_metadata=metadata,
    )


def redact_params(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {k: redact_params(v, key=k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_params(v, key=key) for v in value]
    if key in REDACT_KEYS:
        return {"sha256": _stable_hash(value), "redacted": True}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= 12 and (key or "").lower() not in {"employeeid", "sessionclaimid", "claimid"}:
            return value
        return {"sha256": _stable_hash(value), "redacted": True}
    return {"sha256": _stable_hash(value), "redacted": True}


def _stable_hash(value: Any) -> str:
    return sha256(repr(value).encode("utf-8")).hexdigest()


def _hash_or_none(value: str | None) -> str | None:
    return None if value is None else _stable_hash(value)

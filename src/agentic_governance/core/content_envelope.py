from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any
from uuid import uuid4

from agentic_governance._version import PACKAGE_VERSION


class ContentType:
    """Content type constants for model I/O governance."""
    CHAT_INPUT = "chat_input"
    OCR_TEXT = "ocr_text"
    RAG_CONTENT = "rag_content"
    INTER_AGENT = "inter_agent_message"
    MODEL_OUTPUT = "model_output"

    ALL_INPUT_TYPES = frozenset({CHAT_INPUT, OCR_TEXT, RAG_CONTENT, INTER_AGENT})
    ALL_TYPES = frozenset({CHAT_INPUT, OCR_TEXT, RAG_CONTENT, INTER_AGENT, MODEL_OUTPUT})


@dataclass(frozen=True)
class ContentEnvelope:
    content_id: str
    correlation_id: str
    ts: str
    content_type: str
    agent_identity: str
    content_ref: str        # SHA-256 of raw content — NEVER raw text
    context_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contentId": self.content_id,
            "correlationId": self.correlation_id,
            "ts": self.ts,
            "contentType": self.content_type,
            "agentIdentity": self.agent_identity,
            "contentRef": self.content_ref,
            "contextMetadata": self.context_metadata,
        }


def build_content_envelope(
    content: str,
    *,
    content_type: str,
    correlation_id: str,
    agent_identity: str,
    context: dict[str, Any] | None = None,
) -> ContentEnvelope:
    return ContentEnvelope(
        content_id=str(uuid4()),
        correlation_id=correlation_id,
        ts=datetime.now(timezone.utc).isoformat(),
        content_type=content_type,
        agent_identity=agent_identity,
        content_ref=_stable_hash(content),
        context_metadata={
            "policyVersion": PACKAGE_VERSION,
            **(context or {}),
        },
    )


def _stable_hash(value: Any) -> str:
    try:
        canonical = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=_canonical_json_default,
        )
    except (TypeError, ValueError):
        canonical = repr(value)
    return sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_json_default(value: Any) -> Any:
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=repr)
    return repr(value)

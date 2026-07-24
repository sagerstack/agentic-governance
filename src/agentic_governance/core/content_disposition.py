from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentic_governance._version import PACKAGE_VERSION


# Decision rank for merging multiple control signals (higher = more severe)
DECISION_RANK: dict[str, int] = {
    "Allow": 0,
    "Transform": 1,
    "Escalate": 2,
    "Block": 3,
}


@dataclass(frozen=True)
class ContentFiredControl:
    control_id: str
    name: str
    result: str                          # "allowed" | "transformed" | "escalated" | "blocked" | "would-escalate" | "skipped-disabled"
    signal_value: float | None = None    # e.g. injection score from B1 or judge confidence from B4
    entity_types: tuple[str, ...] = ()   # PII entity category names found (not values) — B2


@dataclass(frozen=True)
class ContentDisposition:
    decision: str                        # "Allow" | "Transform" | "Escalate" | "Block"
    reasons: tuple[str, ...]
    fired_controls: tuple[ContentFiredControl, ...]
    content_out: str | None              # None = use original; non-None = use this (PII-redacted) text
    policy_version: str = PACKAGE_VERSION
    latency_ms: float | None = None


def allow(
    *,
    fired_controls: tuple[ContentFiredControl, ...] = (),
    reasons: tuple[str, ...] = (),
) -> ContentDisposition:
    return ContentDisposition(
        decision="Allow",
        reasons=reasons,
        fired_controls=fired_controls,
        content_out=None,
    )


def transform(
    content: str,
    *,
    reasons: tuple[str, ...] = (),
    fired_controls: tuple[ContentFiredControl, ...] = (),
) -> ContentDisposition:
    return ContentDisposition(
        decision="Transform",
        reasons=reasons,
        fired_controls=fired_controls,
        content_out=content,
    )


def escalate(
    reason: str,
    *,
    fired_controls: tuple[ContentFiredControl, ...] = (),
) -> ContentDisposition:
    return ContentDisposition(
        decision="Escalate",
        reasons=(reason,),
        fired_controls=fired_controls,
        content_out=None,
    )


def block(
    reason: str,
    *,
    fired_controls: tuple[ContentFiredControl, ...] = (),
) -> ContentDisposition:
    return ContentDisposition(
        decision="Block",
        reasons=(reason,),
        fired_controls=fired_controls,
        content_out=None,
    )


def merge_dispositions(base: ContentDisposition, incoming: ContentDisposition) -> ContentDisposition:
    """Merge two dispositions, keeping the higher-severity decision."""
    base_rank = DECISION_RANK.get(base.decision, 0)
    incoming_rank = DECISION_RANK.get(incoming.decision, 0)
    
    if incoming_rank > base_rank:
        decision = incoming.decision
        # Preserve content_out from Transform unless overridden by higher-severity
        content_out = base.content_out if incoming.content_out is None else incoming.content_out
    else:
        decision = base.decision
        content_out = incoming.content_out if base.content_out is None else base.content_out
    
    # Merge reasons (deduplicated, base first)
    merged_reasons = base.reasons + tuple(r for r in incoming.reasons if r not in base.reasons)
    merged_controls = base.fired_controls + incoming.fired_controls
    
    return ContentDisposition(
        decision=decision,
        reasons=merged_reasons,
        fired_controls=merged_controls,
        content_out=content_out,
        policy_version=base.policy_version,
        latency_ms=base.latency_ms,
    )

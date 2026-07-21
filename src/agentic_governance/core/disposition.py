from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FiredControl:
    control_id: str
    name: str
    result: str
    threshold: Any | None = None
    observed_value: Any | None = None


@dataclass(frozen=True)
class Disposition:
    decision: str
    reasons: tuple[str, ...] = ()
    fired_controls: tuple[FiredControl, ...] = ()
    policy_version: str = "slice-1"
    latency_ms: float | None = None


@dataclass(frozen=True)
class GovernanceResult:
    disposition: Disposition
    blocked: bool = False
    result: Any | None = None


def observe(*, reasons: tuple[str, ...] = (), fired_controls: tuple[FiredControl, ...] = ()) -> Disposition:
    return Disposition(decision="Observe", reasons=reasons, fired_controls=fired_controls)


def auto_execute(*, reasons: tuple[str, ...] = (), fired_controls: tuple[FiredControl, ...] = ()) -> Disposition:
    return Disposition(decision="Auto-Execute", reasons=reasons, fired_controls=fired_controls)


def deny(reason: str, *, fired_controls: tuple[FiredControl, ...] = ()) -> Disposition:
    return Disposition(decision="Deny", reasons=(reason,), fired_controls=fired_controls)


def escalate(reason: str, *, fired_controls: tuple[FiredControl, ...] = ()) -> Disposition:
    return Disposition(decision="Escalate", reasons=(reason,), fired_controls=fired_controls)

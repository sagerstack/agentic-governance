from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentic_governance._version import PACKAGE_VERSION


@dataclass(frozen=True)
class FiredControl:
    control_id: str
    name: str
    result: str
    threshold: Any | None = None
    observed_value: Any | None = None


@dataclass(frozen=True)
class ControlState:
    control_id: str
    mode: str
    outcome: str


@dataclass(frozen=True)
class Disposition:
    decision: str
    reasons: tuple[str, ...] = ()
    fired_controls: tuple[FiredControl, ...] = ()
    control_states: tuple[ControlState, ...] = ()
    policy_version: str = PACKAGE_VERSION
    latency_ms: float | None = None


@dataclass(frozen=True)
class GovernanceResult:
    disposition: Disposition
    blocked: bool = False
    result: Any | None = None


def observe(
    *,
    reasons: tuple[str, ...] = (),
    fired_controls: tuple[FiredControl, ...] = (),
    control_states: tuple[ControlState, ...] = (),
) -> Disposition:
    return Disposition(
        decision="Observe",
        reasons=reasons,
        fired_controls=fired_controls,
        control_states=control_states,
    )


def auto_execute(
    *,
    reasons: tuple[str, ...] = (),
    fired_controls: tuple[FiredControl, ...] = (),
    control_states: tuple[ControlState, ...] = (),
) -> Disposition:
    return Disposition(
        decision="Auto-Execute",
        reasons=reasons,
        fired_controls=fired_controls,
        control_states=control_states,
    )


def deny(
    reason: str,
    *,
    fired_controls: tuple[FiredControl, ...] = (),
    control_states: tuple[ControlState, ...] = (),
) -> Disposition:
    return Disposition(
        decision="Deny",
        reasons=(reason,),
        fired_controls=fired_controls,
        control_states=control_states,
    )


def escalate(
    reason: str,
    *,
    fired_controls: tuple[FiredControl, ...] = (),
    control_states: tuple[ControlState, ...] = (),
) -> Disposition:
    return Disposition(
        decision="Escalate",
        reasons=(reason,),
        fired_controls=fired_controls,
        control_states=control_states,
    )

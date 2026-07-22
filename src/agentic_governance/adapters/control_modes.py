"""Environment-driven enforce/observe/off modes for independently staged controls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging
import os

from agentic_governance.adapters.policy_loader import LoadedPolicy


logger = logging.getLogger(__name__)
_MODE_ALIASES = {
    "true": "enforce",
    "1": "enforce",
    "on": "enforce",
    "enforce": "enforce",
    "observe": "observe",
    "false": "off",
    "0": "off",
    "off": "off",
}


@dataclass(frozen=True)
class ControlModeConfig:
    modes: Mapping[str, str]

    @classmethod
    def from_policy(
        cls,
        policy: LoadedPolicy,
        environ: Mapping[str, str] | None = None,
    ) -> "ControlModeConfig":
        env = os.environ if environ is None else environ
        modes: dict[str, str] = {}
        for control_id, spec in policy.controls.items():
            raw_value = env.get(spec.mode_env)
            if raw_value is None or not raw_value.strip():
                mode = spec.default_mode
            else:
                normalized = raw_value.strip().lower()
                mode = _MODE_ALIASES.get(normalized, "")
                if not mode:
                    logger.warning(
                        "Invalid %s=%r; defaulting safely to enforce",
                        spec.mode_env,
                        raw_value,
                    )
                    mode = "enforce"
            if control_id == "A12" and mode == "off":
                logger.warning(
                    "Fail-closed floor is OFF; high-impact calls may execute when governance is unavailable"
                )
            modes[control_id] = mode
        return cls(modes=modes)

    def mode(self, control_id: str) -> str:
        return self.modes.get(control_id, "enforce")

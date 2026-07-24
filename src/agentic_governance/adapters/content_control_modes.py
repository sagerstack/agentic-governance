"""Environment-driven enforce/observe/off modes for Group B content controls."""

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
class ContentControlModeConfig:
    modes: Mapping[str, str]

    @classmethod
    def from_policy(
        cls,
        policy: LoadedPolicy,
        environ: Mapping[str, str] | None = None,
    ) -> "ContentControlModeConfig":
        env = os.environ if environ is None else environ
        modes: dict[str, str] = {}
        for control_id, spec in policy.content_controls.items():
            raw_value = env.get(spec.mode_env)
            if raw_value is None or not raw_value.strip():
                mode = spec.default_mode
            else:
                normalized = raw_value.strip().lower()
                mode = _MODE_ALIASES.get(normalized, "")
                if not mode:
                    logger.warning(
                        "Invalid %s=%r for content control %s; defaulting to enforce",
                        spec.mode_env,
                        raw_value,
                        control_id,
                    )
                    mode = "enforce"
            modes[control_id] = mode
        return cls(modes=modes)

    def mode(self, control_id: str) -> str:
        return self.modes.get(control_id, "enforce")

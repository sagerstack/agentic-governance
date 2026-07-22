from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clean_governance_environment(monkeypatch):
    """Keep Level-1 tests independent from operator/demo environment settings."""
    for name in (
        "AGENTIC_GOV_POLICY_FILE",
        "AGENTIC_GOV_DENY_TOOLS",
        "AGENTIC_GOV_REVOKE_GRANTS",
        "AGENTIC_GOV_FORCE_IDENTITY",
        "AGENTIC_GOV_SIMULATE_TAMPER",
        "AGENTIC_GOV_ENABLE_ALLOWLIST",
        "AGENTIC_GOV_ENABLE_IDENTITY",
        "AGENTIC_GOV_ENABLE_MANDATE",
        "AGENTIC_GOV_ENABLE_INTEGRITY",
        "AGENTIC_GOV_ENABLE_FAIL_CLOSED",
    ):
        monkeypatch.delenv(name, raising=False)

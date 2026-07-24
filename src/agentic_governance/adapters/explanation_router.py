from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentic_governance.core.explanation_generator import Explanation


@dataclass
class ExplanationRoute:
    audience: str
    destination: str  # "chat" | "review_ui" | "audit_log" | "suppress"


DEFAULT_ROUTES = [
    ExplanationRoute("employee", "chat"),
    ExplanationRoute("reviewer", "review_ui"),
    ExplanationRoute("audit", "audit_log"),
]


class ExplanationRouter:
    """Routes explanations to the appropriate destination by audience."""

    def __init__(self, routes: list[ExplanationRoute] | None = None) -> None:
        self._routes = {r.audience: r for r in (routes or DEFAULT_ROUTES)}

    def route(self, explanation: Explanation) -> ExplanationRoute:
        """Return the route for this explanation's audience.
        
        Unknown audience → most restrictive (chat/employee) as fail-closed default.
        """
        if explanation.audience in self._routes:
            return self._routes[explanation.audience]
        # Fail-closed: unknown audience → employee destination
        return ExplanationRoute(audience="employee", destination="chat")

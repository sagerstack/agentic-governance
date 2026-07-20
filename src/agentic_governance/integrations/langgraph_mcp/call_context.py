from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from agentic_governance.core.envelope import GovernanceEnvelope, build_envelope

Provider = Callable[[], Any]


@dataclass(frozen=True)
class TrustedStateProviders:
    employee_id_provider: Provider
    extracted_receipt_provider: Provider
    session_claim_id_provider: Provider
    node_identity_provider: Provider

    def build_envelope(self, server_url: str, tool_name: str, arguments: dict[str, Any] | None) -> GovernanceEnvelope:
        return build_envelope(
            server_url=server_url,
            tool_name=tool_name,
            arguments=arguments,
            employee_id=self.employee_id_provider(),
            extracted_receipt=self.extracted_receipt_provider(),
            session_claim_id=self.session_claim_id_provider(),
            node_identity=self.node_identity_provider(),
        )

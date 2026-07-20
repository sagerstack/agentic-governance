from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agentic_governance.adapters.inmemory_registry import InMemoryIdentityRegistry, InMemoryMandateStore
from agentic_governance.adapters.jsonl_audit import JsonlAuditSink
from agentic_governance.adapters.pdp_python import DeterministicPolicyDecisionPoint
from agentic_governance.core.disposition import Disposition, FiredControl, deny, observe
from agentic_governance.core.engine import GovernanceEngine
from agentic_governance.core.envelope import GovernanceEnvelope
from agentic_governance.integrations.langgraph_mcp.call_context import TrustedStateProviders

RealMcpCallTool = Callable[[str, str, dict[str, Any] | None], Awaitable[Any]]
HIGH_IMPACT_TOOLS = {"insertClaim", "updateClaimStatus"}


class GovernanceUnavailable(RuntimeError):
    pass


class _GovernedMcpRuntime:
    def __init__(
        self,
        *,
        real_mcp_call_tool: RealMcpCallTool,
        providers: TrustedStateProviders,
        engine: GovernanceEngine | None = None,
        audit_sink: Any | None = None,
        identity_registry: Any | None = None,
        mandate_store: Any | None = None,
    ) -> None:
        self._real_mcp_call_tool = real_mcp_call_tool
        self._providers = providers
        self._engine = engine or GovernanceEngine(DeterministicPolicyDecisionPoint())
        self._audit_sink = audit_sink or JsonlAuditSink("./.agentic_governance/audit.jsonl")
        self._identity_registry = identity_registry or InMemoryIdentityRegistry()
        self._mandate_store = mandate_store or InMemoryMandateStore()
        self._pending_audit_events: list[tuple[GovernanceEnvelope, Disposition]] = []

    async def call(self, serverUrl: str, toolName: str, arguments: dict[str, Any] | None) -> Any:
        envelope = self._providers.build_envelope(serverUrl, toolName, arguments)
        try:
            await self._identity_registry.verify(envelope.agent_identity.id)
            await self._mandate_store.mandate_for(envelope.agent_identity.id)
            disposition = await self._engine.evaluate(envelope)
        except Exception as exc:
            if toolName in HIGH_IMPACT_TOOLS:
                disposition = deny(
                    "governance-unavailable",
                    fired_controls=(
                        FiredControl(control_id="A12", name="fail-closed-floor", result="denied"),
                    ),
                )
                self._pending_audit_events.append((envelope, disposition))
                await self._try_flush_pending_audit_events()
                return {"error": "governance-unavailable", "decision": "Deny"}
            disposition = observe(
                reasons=("governance-unavailable-non-high-impact",),
                fired_controls=(
                    FiredControl(control_id="A12", name="fail-closed-floor", result="observe"),
                ),
            )
            result = await self._real_mcp_call_tool(serverUrl, toolName, arguments)
            self._pending_audit_events.append((envelope, disposition))
            await self._try_flush_pending_audit_events()
            return result

        result = await self._real_mcp_call_tool(serverUrl, toolName, arguments)
        await self._record(envelope, disposition)
        return result

    async def _record(self, envelope: GovernanceEnvelope, disposition: Disposition) -> None:
        self._pending_audit_events.append((envelope, disposition))
        await self._try_flush_pending_audit_events()

    async def _try_flush_pending_audit_events(self) -> None:
        if self._audit_sink is None:
            return
        remaining: list[tuple[GovernanceEnvelope, Disposition]] = []
        for envelope, disposition in self._pending_audit_events:
            try:
                await self._audit_sink.append(envelope, disposition)
            except Exception:
                remaining.append((envelope, disposition))
        self._pending_audit_events = remaining


_RUNTIME: _GovernedMcpRuntime | None = None


def install(
    *,
    real_mcp_call_tool: RealMcpCallTool,
    employee_id_provider: Callable[[], Any],
    extracted_receipt_provider: Callable[[], Any],
    session_claim_id_provider: Callable[[], Any],
    node_identity_provider: Callable[[], Any],
    engine: GovernanceEngine | None = None,
    audit_sink: Any | None = None,
    identity_registry: Any | None = None,
    mandate_store: Any | None = None,
) -> Callable[[str, str, dict[str, Any] | None], Awaitable[Any]]:
    global _RUNTIME
    providers = TrustedStateProviders(
        employee_id_provider=employee_id_provider,
        extracted_receipt_provider=extracted_receipt_provider,
        session_claim_id_provider=session_claim_id_provider,
        node_identity_provider=node_identity_provider,
    )
    _RUNTIME = _GovernedMcpRuntime(
        real_mcp_call_tool=real_mcp_call_tool,
        providers=providers,
        engine=engine,
        audit_sink=audit_sink,
        identity_registry=identity_registry,
        mandate_store=mandate_store,
    )
    return governedMcpCallTool


async def governedMcpCallTool(serverUrl: str, toolName: str, arguments: dict[str, Any] | None) -> Any:
    if _RUNTIME is None:
        raise RuntimeError("governedMcpCallTool is not installed")
    return await _RUNTIME.call(serverUrl, toolName, arguments)

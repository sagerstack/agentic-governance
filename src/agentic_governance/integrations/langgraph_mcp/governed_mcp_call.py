from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agentic_governance.adapters.control_modes import ControlModeConfig
from agentic_governance.adapters.identity_mandates import (
    DemoIdentityOverrideConfig,
    IdentityMandateConfig,
)
from agentic_governance.adapters.inmemory_registry import InMemoryIdentityRegistry, InMemoryMandateStore
from agentic_governance.adapters.jsonl_audit import JsonlAuditSink
from agentic_governance.adapters.pdp_python import DeterministicPolicyDecisionPoint
from agentic_governance.adapters.policy_loader import load_policy
from agentic_governance.core.disposition import (
    ControlState,
    Disposition,
    FiredControl,
    deny,
    observe,
)
from agentic_governance.core.engine import GovernanceEngine
from agentic_governance.core.envelope import GovernanceEnvelope
from agentic_governance.core.integrity import IntegrityEvaluator
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
        self._policy = load_policy()
        self._control_modes = ControlModeConfig.from_policy(self._policy)
        self._engine = engine or GovernanceEngine(
            DeterministicPolicyDecisionPoint(
                policy=self._policy,
                control_modes=self._control_modes,
            )
        )
        self._audit_sink = audit_sink or JsonlAuditSink("./.agentic_governance/")
        identity_mandate_config = IdentityMandateConfig.from_policy(self._policy)
        self._identity_registry = identity_registry or InMemoryIdentityRegistry(
            identity_mandate_config
        )
        self._mandate_store = mandate_store or InMemoryMandateStore(
            identity_mandate_config
        )
        self._integrity_evaluator = IntegrityEvaluator()
        self._pending_audit_events: list[tuple[GovernanceEnvelope, Disposition]] = []

    async def call(self, serverUrl: str, toolName: str, arguments: dict[str, Any] | None) -> Any:
        envelope = self._providers.build_envelope(serverUrl, toolName, arguments)

        # A5 — global exact server/tool allowlist.
        try:
            disposition = await self._engine.evaluate(envelope)
        except Exception:
            return await self._handle_governance_unavailable(
                envelope, serverUrl, toolName, arguments
            )
        if disposition.decision == "Deny":
            return await self._record_and_dispatch(
                envelope, disposition, serverUrl, toolName, arguments
            )

        identity_id = envelope.agent_identity.id

        # A3 — trusted-context identity verification.
        identity_mode = self._control_modes.mode("A3")
        verified_identity = None
        if identity_mode == "off":
            disposition = self._add_skipped(disposition, "A3")
        else:
            try:
                verified_identity = await self._identity_registry.verify(identity_id)
            except Exception:
                return await self._handle_governance_unavailable(
                    envelope, serverUrl, toolName, arguments
                )
            if verified_identity is None:
                disposition = self._apply_control_result(
                    disposition,
                    control_id="A3",
                    name="identity-verification",
                    mode=identity_mode,
                    allowed=False,
                    deny_reason="unverified-identity",
                )
                if disposition.decision == "Deny":
                    return await self._record_and_dispatch(
                        envelope, disposition, serverUrl, toolName, arguments
                    )
            else:
                disposition = self._apply_control_result(
                    disposition,
                    control_id="A3",
                    name="identity-verification",
                    mode=identity_mode,
                    allowed=True,
                )
                identity_id = verified_identity.id

        # A4 — exact per-identity capability mandate.
        mandate_mode = self._control_modes.mode("A4")
        if mandate_mode == "off":
            disposition = self._add_skipped(disposition, "A4")
        else:
            try:
                mandate = await self._mandate_store.mandate_for(identity_id)
            except Exception:
                return await self._handle_governance_unavailable(
                    envelope, serverUrl, toolName, arguments
                )
            mandate_allowed = mandate is not None and mandate.allows(serverUrl, toolName)
            disposition = self._apply_control_result(
                disposition,
                control_id="A4",
                name="machine-readable-mandate",
                mode=mandate_mode,
                allowed=mandate_allowed,
                deny_reason="mandate-violation",
            )
            if disposition.decision == "Deny":
                return await self._record_and_dispatch(
                    envelope, disposition, serverUrl, toolName, arguments
                )

        # A2 — config-defined origin/integrity comparisons on raw in-memory facts.
        integrity_mode = self._control_modes.mode("A2")
        if integrity_mode == "off":
            disposition = self._add_skipped(disposition, "A2")
        else:
            try:
                integrity = self._integrity_evaluator.evaluate(
                    server_url=serverUrl,
                    tool_name=toolName,
                    identity=identity_id,
                    declared=envelope.declared_params,
                    trusted=envelope.trusted_context,
                    rules=self._policy.integrity_rules,
                    simulated_tampers=self._policy.simulated_tampers,
                )
            except Exception:
                return await self._handle_governance_unavailable(
                    envelope, serverUrl, toolName, arguments
                )
            if not integrity.applicable:
                disposition = self._add_state(
                    disposition,
                    ControlState("A2", integrity_mode, "not-applicable"),
                )
            else:
                integrity_allowed = not integrity.mismatched_fields
                disposition = self._apply_control_result(
                    disposition,
                    control_id="A2",
                    name="envelope-integrity",
                    mode=integrity_mode,
                    allowed=integrity_allowed,
                    deny_reason="integrity-mismatch",
                    observed_value=(
                        list(integrity.mismatched_fields)
                        if integrity.mismatched_fields
                        else None
                    ),
                )

        return await self._record_and_dispatch(
            envelope, disposition, serverUrl, toolName, arguments
        )

    async def _record_and_dispatch(
        self,
        envelope: GovernanceEnvelope,
        disposition: Disposition,
        server_url: str,
        tool_name: str,
        arguments: dict[str, Any] | None,
    ) -> Any:
        await self._record(envelope, disposition)
        if disposition.decision == "Deny":
            reason = disposition.reasons[0] if disposition.reasons else "denied"
            return {"error": reason, "decision": "Deny"}
        return await self._real_mcp_call_tool(server_url, tool_name, arguments)

    async def _handle_governance_unavailable(
        self,
        envelope: GovernanceEnvelope,
        server_url: str,
        tool_name: str,
        arguments: dict[str, Any] | None,
    ) -> Any:
        mode = self._control_modes.mode("A12")
        high_impact = tool_name in HIGH_IMPACT_TOOLS
        if mode == "enforce" and high_impact:
            disposition = deny(
                "governance-unavailable",
                fired_controls=(
                    FiredControl(control_id="A12", name="fail-closed-floor", result="denied"),
                ),
                control_states=(ControlState("A12", "enforce", "denied"),),
            )
            await self._record(envelope, disposition)
            return {"error": "governance-unavailable", "decision": "Deny"}
        if mode == "observe" and high_impact:
            disposition = observe(
                reasons=("would-deny:governance-unavailable",),
                fired_controls=(
                    FiredControl(
                        control_id="A12",
                        name="fail-closed-floor",
                        result="would-deny",
                    ),
                ),
                control_states=(
                    ControlState(
                        "A12", "observe", "would-deny:governance-unavailable"
                    ),
                ),
            )
        elif mode == "off":
            disposition = observe(
                reasons=("governance-unavailable-fail-closed-disabled",),
                control_states=(ControlState("A12", "off", "skipped-disabled"),),
            )
        else:
            disposition = observe(
                reasons=("governance-unavailable-non-high-impact",),
                fired_controls=(
                    FiredControl(control_id="A12", name="fail-closed-floor", result="observe"),
                ),
                control_states=(ControlState("A12", mode, "observed"),),
            )
        await self._record(envelope, disposition)
        return await self._real_mcp_call_tool(server_url, tool_name, arguments)

    def _add_skipped(self, disposition: Disposition, control_id: str) -> Disposition:
        return self._add_state(
            disposition,
            ControlState(control_id, "off", "skipped-disabled"),
        )

    @staticmethod
    def _add_state(disposition: Disposition, state: ControlState) -> Disposition:
        return Disposition(
            decision=disposition.decision,
            reasons=disposition.reasons,
            fired_controls=disposition.fired_controls,
            control_states=disposition.control_states + (state,),
            policy_version=disposition.policy_version,
            latency_ms=disposition.latency_ms,
        )

    @classmethod
    def _apply_control_result(
        cls,
        disposition: Disposition,
        *,
        control_id: str,
        name: str,
        mode: str,
        allowed: bool,
        deny_reason: str | None = None,
        observed_value: Any = None,
    ) -> Disposition:
        controls_without_a6 = tuple(
            control
            for control in disposition.fired_controls
            if control.control_id != "A6"
        )
        if allowed:
            decision = disposition.decision
            reasons = disposition.reasons
            result = "verified" if control_id == "A3" else "allowed"
            outcome = "allowed"
        elif mode == "observe":
            decision = disposition.decision
            shadow_reason = f"would-deny:{deny_reason}"
            reasons = disposition.reasons + (
                () if shadow_reason in disposition.reasons else (shadow_reason,)
            )
            result = "would-deny"
            outcome = f"would-deny:{deny_reason}"
        else:
            decision = "Deny"
            shadow_reasons = tuple(
                reason for reason in disposition.reasons if reason.startswith("would-deny:")
            )
            reasons = (deny_reason or "denied",) + shadow_reasons
            result = "denied"
            outcome = "denied"
        return Disposition(
            decision=decision,
            reasons=reasons,
            fired_controls=controls_without_a6
            + (
                FiredControl(
                    control_id=control_id,
                    name=name,
                    result=result,
                    observed_value=observed_value,
                ),
                FiredControl(
                    control_id="A6",
                    name="deterministic-disposition",
                    result=decision,
                ),
            ),
            control_states=disposition.control_states
            + (ControlState(control_id, mode, outcome),),
            policy_version=disposition.policy_version,
            latency_ms=disposition.latency_ms,
        )

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
    db_claim_id_provider: Callable[[], Any] = lambda: None,
    engine: GovernanceEngine | None = None,
    audit_sink: Any | None = None,
    identity_registry: Any | None = None,
    mandate_store: Any | None = None,
) -> Callable[[str, str, dict[str, Any] | None], Awaitable[Any]]:
    global _RUNTIME
    demo_identity_override = DemoIdentityOverrideConfig.from_environment()

    def effective_node_identity_provider() -> Any:
        if demo_identity_override.forced_identity is not None:
            return demo_identity_override.forced_identity
        return node_identity_provider()

    providers = TrustedStateProviders(
        employee_id_provider=employee_id_provider,
        extracted_receipt_provider=extracted_receipt_provider,
        session_claim_id_provider=session_claim_id_provider,
        node_identity_provider=effective_node_identity_provider,
        db_claim_id_provider=db_claim_id_provider,
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

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from agentic_governance.adapters.control_modes import ControlModeConfig
from agentic_governance.adapters.inmemory_counters import InMemoryCounterStore
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
from agentic_governance.core.quantitative import QuantitativeEvaluator
from agentic_governance.core.schema_validation import SchemaValidator
from agentic_governance.integrations.langgraph_mcp.call_context import TrustedStateProviders

RealMcpCallTool = Callable[[str, str, dict[str, Any] | None], Awaitable[Any]]
HIGH_IMPACT_TOOLS = {"insertClaim", "updateClaimStatus"}


@dataclass(frozen=True)
class _ExposureReservation:
    key: str
    amount: Decimal
    window_start: float


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
        self._quantitative_evaluator = QuantitativeEvaluator()
        self._schema_validator = SchemaValidator()
        self._counter_store = InMemoryCounterStore()
        self._pending_audit_events: list[tuple[GovernanceEnvelope, Disposition]] = []

    async def call(self, serverUrl: str, toolName: str, arguments: dict[str, Any] | None) -> Any:
        envelope = self._providers.build_envelope(serverUrl, toolName, arguments)

        # A10 — reject rogue endpoints first, then validate known tool argument schemas.
        schema_mode = self._control_modes.mode("A10")
        pre_disposition = Disposition(
            decision="Auto-Execute",
            fired_controls=(
                FiredControl(
                    control_id="A6",
                    name="deterministic-disposition",
                    result="Auto-Execute",
                ),
            ),
        )
        if schema_mode == "off":
            pre_disposition = self._add_skipped(pre_disposition, "A10")
        else:
            schema_evaluation = self._schema_validator.evaluate(
                server_url=serverUrl,
                tool_name=toolName,
                arguments=arguments,
                trusted_servers=self._policy.trusted_servers,
                rules=self._policy.schema_rules,
            )
            if not schema_evaluation.trusted_server:
                pre_disposition = self._apply_quantitative_result(
                    pre_disposition,
                    control_id="A10",
                    name="input-schema-and-trusted-server",
                    mode=schema_mode,
                    breach_disposition="Deny",
                    reason="untrusted-server",
                    outcome="untrusted-server",
                    observed_value=serverUrl,
                )
            elif schema_evaluation.schema_found and not schema_evaluation.valid:
                pre_disposition = self._apply_quantitative_result(
                    pre_disposition,
                    control_id="A10",
                    name="input-schema-and-trusted-server",
                    mode=schema_mode,
                    breach_disposition="Deny",
                    reason="schema-invalid",
                    outcome="schema-invalid",
                    observed_value=list(schema_evaluation.errors),
                )
            elif schema_evaluation.schema_found:
                pre_disposition = self._apply_control_result(
                    pre_disposition,
                    control_id="A10",
                    name="input-schema-and-trusted-server",
                    mode=schema_mode,
                    allowed=True,
                )
            else:
                pre_disposition = self._add_state(
                    pre_disposition,
                    ControlState("A10", schema_mode, "not-applicable"),
                )
        if pre_disposition.decision == "Deny":
            return await self._record_and_dispatch(
                envelope, pre_disposition, serverUrl, toolName, arguments
            )

        # A5 — global exact server/tool allowlist.
        try:
            disposition = await self._engine.evaluate(envelope)
        except Exception:
            return await self._handle_governance_unavailable(
                envelope, serverUrl, toolName, arguments
            )
        disposition = self._merge_pre_disposition(pre_disposition, disposition)
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

        # A7 — per-action and atomically reserved aggregate monetary exposure.
        exposure_reservation: _ExposureReservation | None = None
        exposure_mode = self._control_modes.mode("A7")
        if exposure_mode == "off":
            disposition = self._add_skipped(disposition, "A7")
        else:
            try:
                exposure_rule, exposure = self._quantitative_evaluator.exposure(
                    server_url=serverUrl,
                    tool_name=toolName,
                    identity=identity_id,
                    declared=envelope.declared_params,
                    trusted=envelope.trusted_context,
                    rules=self._policy.exposure_rules,
                )
                if not exposure.applicable:
                    disposition = self._add_state(
                        disposition, ControlState("A7", exposure_mode, "not-applicable")
                    )
                else:
                    breach_disposition = exposure.disposition
                    breach_outcome = exposure.outcome
                    aggregate_value: Decimal | None = None
                    should_reserve = (
                        exposure.amount is not None
                        and exposure.aggregate_key is not None
                        and not (breach_disposition and exposure_mode == "enforce")
                    )
                    if should_reserve and exposure_rule is not None:
                        aggregate = await self._counter_store.add_window(
                            exposure.aggregate_key,
                            exposure.amount,
                            exposure_rule.aggregate_window_seconds,
                        )
                        aggregate_value = aggregate.value
                        exposure_reservation = _ExposureReservation(
                            exposure.aggregate_key,
                            exposure.amount,
                            aggregate.window_start,
                        )
                        if aggregate.value > exposure_rule.aggregate_limit:
                            aggregate_disposition = exposure_rule.aggregate_disposition
                            if self._decision_rank(aggregate_disposition) > self._decision_rank(
                                breach_disposition
                            ):
                                breach_disposition = aggregate_disposition
                                breach_outcome = "aggregate-limit-exceeded"
                    if breach_disposition:
                        disposition = self._apply_quantitative_result(
                            disposition,
                            control_id="A7",
                            name="exposure-limits",
                            mode=exposure_mode,
                            breach_disposition=breach_disposition,
                            reason="exposure-exceeded",
                            outcome=breach_outcome,
                            threshold=(
                                None
                                if breach_outcome.startswith("missing-")
                                else str(exposure_rule.aggregate_limit)
                                if breach_outcome == "aggregate-limit-exceeded"
                                else str(
                                    exposure_rule.hard_deny_cap
                                    if breach_outcome == "hard-cap-exceeded"
                                    else exposure_rule.escalate_ceiling
                                )
                            ) if exposure_rule is not None else None,
                            observed_value=breach_outcome,
                        )
                    else:
                        disposition = self._apply_control_result(
                            disposition,
                            control_id="A7",
                            name="exposure-limits",
                            mode=exposure_mode,
                            allowed=True,
                            observed_value="within-exposure-limits",
                        )
            except Exception:
                return await self._handle_governance_unavailable(
                    envelope, serverUrl, toolName, arguments
                )

        # A8 — count attempts atomically for every configured employee/session key.
        rate_mode = self._control_modes.mode("A8")
        if rate_mode == "off":
            disposition = self._add_skipped(disposition, "A8")
        else:
            try:
                rate_match = self._quantitative_evaluator.rate(
                    server_url=serverUrl,
                    tool_name=toolName,
                    identity=identity_id,
                    trusted=envelope.trusted_context,
                    rules=self._policy.rate_rules,
                )
                if rate_match is None:
                    disposition = self._add_state(
                        disposition, ControlState("A8", rate_mode, "not-applicable")
                    )
                else:
                    rate_rule, rate = rate_match
                    if not rate.keys:
                        disposition = self._apply_quantitative_result(
                            disposition,
                            control_id="A8",
                            name="rate-limits",
                            mode=rate_mode,
                            breach_disposition="Deny",
                            reason="rate-exceeded",
                            outcome="missing-rate-key",
                            threshold=str(rate_rule.max_attempts),
                            observed_value="missing",
                        )
                    else:
                        counts = [
                            await self._counter_store.add_window(
                                key, Decimal("1"), rate_rule.window_seconds
                            )
                            for key in rate.keys
                        ]
                        observed_count = max(counter.value for counter in counts)
                        if observed_count > rate_rule.max_attempts:
                            disposition = self._apply_quantitative_result(
                                disposition,
                                control_id="A8",
                                name="rate-limits",
                                mode=rate_mode,
                                breach_disposition=rate_rule.exceeded_disposition,
                                reason="rate-exceeded",
                                outcome="rate-limit-exceeded",
                                threshold=str(rate_rule.max_attempts),
                                observed_value=str(observed_count),
                            )
                        else:
                            disposition = self._apply_control_result(
                                disposition,
                                control_id="A8",
                                name="rate-limits",
                                mode=rate_mode,
                                allowed=True,
                                observed_value=str(observed_count),
                            )
            except Exception:
                if exposure_reservation is not None:
                    await self._release_exposure(exposure_reservation)
                return await self._handle_governance_unavailable(
                    envelope, serverUrl, toolName, arguments
                )

        # A9 — receipt evidence presence and minimum configured confidence.
        evidence_mode = self._control_modes.mode("A9")
        if evidence_mode == "off":
            disposition = self._add_skipped(disposition, "A9")
        else:
            try:
                evidence_rule, evidence = self._quantitative_evaluator.evidence(
                    server_url=serverUrl,
                    tool_name=toolName,
                    identity=identity_id,
                    trusted=envelope.trusted_context,
                    rules=self._policy.evidence_rules,
                )
                if not evidence.applicable:
                    disposition = self._add_state(
                        disposition, ControlState("A9", evidence_mode, "not-applicable")
                    )
                elif not evidence.sufficient:
                    disposition = self._apply_quantitative_result(
                        disposition,
                        control_id="A9",
                        name="evidence-quality",
                        mode=evidence_mode,
                        breach_disposition=(
                            evidence_rule.insufficient_disposition
                            if evidence_rule is not None
                            else "Escalate"
                        ),
                        reason="evidence-insufficient",
                        outcome=(
                            "missing-evidence"
                            if evidence.missing
                            else "confidence-below-threshold"
                        ),
                        threshold=(
                            str(evidence_rule.minimum_confidence)
                            if evidence_rule is not None
                            else None
                        ),
                        observed_value=(
                            {"classification": "missing-evidence", "paths": list(evidence.missing)}
                            if evidence.missing
                            else "confidence-below-threshold"
                        ),
                    )
                else:
                    disposition = self._apply_control_result(
                        disposition,
                        control_id="A9",
                        name="evidence-quality",
                        mode=evidence_mode,
                        allowed=True,
                        observed_value="confidence-sufficient",
                    )
            except Exception:
                if exposure_reservation is not None:
                    await self._release_exposure(exposure_reservation)
                return await self._handle_governance_unavailable(
                    envelope, serverUrl, toolName, arguments
                )

        if disposition.decision in {"Deny", "Escalate"} and exposure_reservation is not None:
            await self._release_exposure(exposure_reservation)
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
        if disposition.decision == "Escalate":
            reason = disposition.reasons[0] if disposition.reasons else "escalated"
            return {
                "error": reason,
                "decision": "Escalate",
                "reason": reason,
                "reasons": list(disposition.reasons),
                "escalation": {"source": "governance", "reason": reason},
            }
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

    @staticmethod
    def _merge_pre_disposition(
        pre_disposition: Disposition,
        disposition: Disposition,
    ) -> Disposition:
        pre_controls = tuple(
            control
            for control in pre_disposition.fired_controls
            if control.control_id != "A6"
        )
        shadow_reasons = tuple(
            reason
            for reason in pre_disposition.reasons
            if reason.startswith("would-")
        )
        if disposition.decision == "Deny":
            reasons = disposition.reasons + tuple(
                reason for reason in shadow_reasons if reason not in disposition.reasons
            )
        else:
            reasons = pre_disposition.reasons + tuple(
                reason for reason in disposition.reasons if reason not in pre_disposition.reasons
            )
        return Disposition(
            decision=disposition.decision,
            reasons=reasons,
            fired_controls=pre_controls + disposition.fired_controls,
            control_states=pre_disposition.control_states + disposition.control_states,
            policy_version=disposition.policy_version,
            latency_ms=disposition.latency_ms,
        )

    @classmethod
    def _apply_quantitative_result(
        cls,
        disposition: Disposition,
        *,
        control_id: str,
        name: str,
        mode: str,
        breach_disposition: str,
        reason: str,
        outcome: str,
        threshold: Any = None,
        observed_value: Any = None,
    ) -> Disposition:
        controls_without_a6 = tuple(
            control for control in disposition.fired_controls if control.control_id != "A6"
        )
        if mode == "observe":
            decision = disposition.decision
            shadow_reason = f"would-{breach_disposition.lower()}:{reason}"
            reasons = disposition.reasons + (
                () if shadow_reason in disposition.reasons else (shadow_reason,)
            )
            result = f"would-{breach_disposition.lower()}"
            state_outcome = f"{result}:{reason}"
        else:
            decision = cls._stronger_decision(disposition.decision, breach_disposition)
            previous = tuple(
                existing
                for existing in disposition.reasons
                if existing.startswith("would-") or existing != "tool-allowed"
            )
            if decision == "Deny" and breach_disposition == "Deny":
                reasons = (reason,) + tuple(existing for existing in previous if existing != reason)
            elif reason in previous:
                reasons = previous
            else:
                reasons = previous + (reason,)
            result = breach_disposition
            state_outcome = outcome
        return Disposition(
            decision=decision,
            reasons=reasons,
            fired_controls=controls_without_a6
            + (
                FiredControl(
                    control_id=control_id,
                    name=name,
                    result=result,
                    threshold=threshold,
                    observed_value=observed_value,
                ),
                FiredControl(
                    control_id="A6",
                    name="deterministic-disposition",
                    result=decision,
                ),
            ),
            control_states=disposition.control_states
            + (ControlState(control_id, mode, state_outcome),),
            policy_version=disposition.policy_version,
            latency_ms=disposition.latency_ms,
        )

    @staticmethod
    def _decision_rank(decision: str | None) -> int:
        return {None: 0, "Auto-Execute": 0, "Observe": 0, "Escalate": 1, "Deny": 2}.get(
            decision, 0
        )

    @classmethod
    def _stronger_decision(cls, current: str, candidate: str) -> str:
        return candidate if cls._decision_rank(candidate) > cls._decision_rank(current) else current

    async def _release_exposure(self, reservation: _ExposureReservation) -> None:
        await self._counter_store.rollback_window(
            reservation.key,
            reservation.amount,
            reservation.window_start,
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

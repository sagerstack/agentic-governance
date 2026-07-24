"""Content governance hooks for model input/output.

ContentHookRuntime: directly instantiated (not a singleton) — each
conversation/graph creates its own instance.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger(__name__)

from agentic_governance.adapters.content_control_modes import ContentControlModeConfig
from agentic_governance.adapters.grounding_validator import GroundingValidator
from agentic_governance.adapters.input_attack_detector import InputAttackDetector
from agentic_governance.adapters.jsonl_audit import JsonlAuditSink, build_content_audit_entry
from agentic_governance.adapters.llm_judge import JudgeCritique, LlmJudge
from agentic_governance.adapters.pii_minimizer import PiiMinimizer
from agentic_governance.adapters.policy_loader import LoadedPolicy, load_policy
from agentic_governance.core.failure_handler import GracefulFailureHandler, StructuredFailure
from agentic_governance.core.content_disposition import (
    ContentDisposition,
    ContentFiredControl,
    allow,
    escalate,
    merge_dispositions,
    transform,
)
from agentic_governance.core.content_envelope import (
    ContentType,
    build_content_envelope,
)
from agentic_governance.core.explanation_generator import ExplanationGenerator


@dataclass
class ContentHookResult:
    """Result from a content governance check."""
    decision: str           # "Allow" | "Transform" | "Escalate" | "Block"
    content: str            # Original or PII-redacted content (use this downstream)
    reasons: list[str]
    fired_controls: list[dict[str, Any]]
    should_proceed: bool    # True for Allow/Transform; False for Block
    needs_human: bool       # True for Escalate
    explanation_employee: str | None = None   # B6 (added in Slice B3)
    explanation_reviewer: str | None = None   # B6 (added in Slice B3)
    explanation_audit: dict | None = None     # B6 (added in Slice B3)


def _disposition_to_result(
    disposition: ContentDisposition,
    original_content: str,
) -> ContentHookResult:
    """Convert a ContentDisposition to a ContentHookResult."""
    content = disposition.content_out if disposition.content_out is not None else original_content
    return ContentHookResult(
        decision=disposition.decision,
        content=content,
        reasons=list(disposition.reasons),
        fired_controls=[
            {
                "controlId": c.control_id,
                "name": c.name,
                "result": c.result,
                "signalValue": c.signal_value,
                "entityTypes": list(c.entity_types),
            }
            for c in disposition.fired_controls
        ],
        should_proceed=disposition.decision in ("Allow", "Transform"),
        needs_human=disposition.decision == "Escalate",
    )


class ContentHookRuntime:
    """Governs model I/O through B1-B6 content controls.
    
    Directly instantiated (not a singleton).
    Adapters are injected for testability; None = feature skipped.
    """

    def __init__(
        self,
        *,
        policy: LoadedPolicy,
        audit_sink: Any | None = None,
        attack_detector: InputAttackDetector | None = None,
        pii_minimizer: PiiMinimizer | None = None,
        grounding_validator: GroundingValidator | None = None,
        llm_judge: LlmJudge | None = None,
        failure_handler: GracefulFailureHandler | None = None,
        explanation_generator: ExplanationGenerator | None = None,
    ) -> None:
        self._policy = policy
        self._modes = ContentControlModeConfig.from_policy(policy)
        self._audit_sink = audit_sink
        self._attack_detector = attack_detector
        self._pii_minimizer = pii_minimizer
        self._grounding_validator = grounding_validator
        self._llm_judge = llm_judge
        self._failure_handler = failure_handler or GracefulFailureHandler()
        self._explanation_generator = explanation_generator or ExplanationGenerator()

    async def pre_model_check(
        self,
        content: str,
        content_type: str,
        *,
        correlation_id: str,
        agent_identity: str,
        context: dict[str, Any] | None = None,
    ) -> ContentHookResult:
        """Run B1 (input attack) and B2 (PII input) on content before model call.
        
        Returns ContentHookResult with decision and (possibly transformed) content.
        The caller must use result.content (not the original) for the model call.
        """
        start = time.perf_counter()
        envelope = build_content_envelope(
            content,
            content_type=content_type,
            correlation_id=correlation_id,
            agent_identity=agent_identity,
            context=context,
        )
        disposition = allow()

        # B1: Input attack detection
        # Scope: input types only (not model output, not raw image bytes)
        if content_type in ContentType.ALL_INPUT_TYPES:
            disposition = self._apply_b1(content, disposition)

        # B2: PII input minimization (input side)
        # Scope: all content types
        # Apply to whatever content we have after B1 (original or unchanged — B1 doesn't transform)
        effective_content = disposition.content_out if disposition.content_out is not None else content
        disposition = self._apply_b2_input(effective_content, disposition)

        # Record latency
        latency_ms = (time.perf_counter() - start) * 1000
        disposition = ContentDisposition(
            decision=disposition.decision,
            reasons=disposition.reasons,
            fired_controls=disposition.fired_controls,
            content_out=disposition.content_out,
            policy_version=disposition.policy_version,
            latency_ms=latency_ms,
        )

        # Emit audit entry (PII-safe via build_content_audit_entry)
        await self._emit_audit(envelope, disposition)

        return _disposition_to_result(disposition, content)

    async def post_model_check(
        self,
        content: str,
        content_type: str,
        *,
        correlation_id: str,
        agent_identity: str,
        context: dict[str, Any] | None = None,
        trusted_state: dict[str, Any] | None = None,
        rag_clauses: list[str] | None = None,
        required_evidence_fields: list[str] | None = None,
    ) -> ContentHookResult:
        """Run B2 (PII output), B3 (grounding), B4 (judge), B5 (failure) on model output."""
        import json as _json
        import time
        start = time.perf_counter()
        trusted_state = trusted_state or {}
        context = context or {}

        envelope = build_content_envelope(
            content, content_type=content_type,
            correlation_id=correlation_id, agent_identity=agent_identity, context=context,
        )

        try:
            disposition = allow()

            # B2 output: PII filtering on model output
            b2_mode = self._modes.mode("B2")
            if b2_mode == "off":
                disposition = _add_skipped(disposition, "B2", "pii-minimization")
            elif self._pii_minimizer is not None:
                effective = disposition.content_out if disposition.content_out is not None else content
                disposition = self._apply_b2_input(effective, disposition)

            effective_content = disposition.content_out if disposition.content_out is not None else content

            # B3: Grounded output validation
            b3_mode = self._modes.mode("B3")
            if b3_mode == "off":
                disposition = _add_skipped(disposition, "B3", "grounded-output-validation")
            elif self._grounding_validator is not None and trusted_state:
                try:
                    model_output_parsed: dict[str, Any] = {}
                    try:
                        model_output_parsed = _json.loads(effective_content)
                    except Exception:
                        pass

                    grounding_result = self._grounding_validator.validate(
                        model_output=model_output_parsed, trusted_state=trusted_state,
                        rag_clauses=rag_clauses, required_evidence_fields=required_evidence_fields,
                    )
                    b3_fired = ContentFiredControl(
                        control_id="B3", name="grounded-output-validation",
                        result="grounding-failed" if not grounding_result.passed else "grounded",
                    )

                    if not grounding_result.passed and grounding_result.worst_disposition:
                        if b3_mode == "enforce":
                            if grounding_result.worst_disposition == "Block":
                                incoming = ContentDisposition(decision="Block", reasons=("grounding-failed",), fired_controls=(b3_fired,), content_out=None, policy_version=disposition.policy_version)
                            else:
                                incoming = ContentDisposition(decision="Escalate", reasons=("grounding-failed",), fired_controls=(b3_fired,), content_out=None, policy_version=disposition.policy_version)
                            disposition = merge_dispositions(disposition, incoming)
                        else:  # observe
                            disposition = ContentDisposition(decision=disposition.decision, reasons=disposition.reasons + ("would-escalate:grounding-failed",), fired_controls=disposition.fired_controls + (b3_fired,), content_out=disposition.content_out, policy_version=disposition.policy_version, latency_ms=disposition.latency_ms)
                    else:
                        disposition = ContentDisposition(decision=disposition.decision, reasons=disposition.reasons, fired_controls=disposition.fired_controls + (b3_fired,), content_out=disposition.content_out, policy_version=disposition.policy_version, latency_ms=disposition.latency_ms)
                except Exception:
                    pass

            # B4: LLM judge (observe-only by design; enforce only contributes WITH B3)
            b4_mode = self._modes.mode("B4")
            b3_had_finding = any(c.control_id == "B3" and c.result == "grounding-failed" for c in disposition.fired_controls)

            if b4_mode == "off":
                disposition = _add_skipped(disposition, "B4", "llm-judge")
            elif self._llm_judge is not None:
                try:
                    critique = await self._llm_judge.critique(effective_content, context)
                    b4_fired = ContentFiredControl(control_id="B4", name="llm-judge", result="concerns-found" if critique.concerns else "no-concerns", signal_value=critique.confidence)

                    if critique.concerns and b4_mode == "enforce" and b3_had_finding:
                        incoming = ContentDisposition(decision="Escalate", reasons=("judge-concerns-with-grounding-failure",), fired_controls=(b4_fired,), content_out=None, policy_version=disposition.policy_version)
                        disposition = merge_dispositions(disposition, incoming)
                    elif critique.concerns:
                        shadow = "would-escalate:judge-concerns"
                        disposition = ContentDisposition(decision=disposition.decision, reasons=disposition.reasons + (shadow,), fired_controls=disposition.fired_controls + (b4_fired,), content_out=disposition.content_out, policy_version=disposition.policy_version, latency_ms=disposition.latency_ms)
                    else:
                        disposition = ContentDisposition(decision=disposition.decision, reasons=disposition.reasons, fired_controls=disposition.fired_controls + (b4_fired,), content_out=disposition.content_out, policy_version=disposition.policy_version, latency_ms=disposition.latency_ms)
                except Exception:
                    pass  # Judge failure never breaks pipeline

        except Exception:
            # B5: Wrap all exceptions
            from agentic_governance.core.content_disposition import escalate
            disposition = escalate("pipeline-failure", fired_controls=(ContentFiredControl("B5", "graceful-failure", "escalated-on-failure"),))

        latency_ms = (time.perf_counter() - start) * 1000
        disposition = ContentDisposition(decision=disposition.decision, reasons=disposition.reasons, fired_controls=disposition.fired_controls, content_out=disposition.content_out, policy_version=disposition.policy_version, latency_ms=latency_ms)

        # B6: Generate three-tier explanations
        result = _disposition_to_result(disposition, content)
        b6_mode = self._modes.mode("B6")
        if b6_mode != "off" and self._explanation_generator and disposition.fired_controls:
            # Pick primary control for explanation
            primary_control = disposition.fired_controls[0] if disposition.fired_controls else None
            if primary_control:
                control_id = primary_control.control_id
                decision = disposition.decision
                explanation_context = dict(context or {})
                
                if b6_mode == "enforce":
                    # Generate all three tiers
                    exp_employee = self._explanation_generator.generate(
                        control_id=control_id, decision=decision,
                        context=explanation_context, audience="employee"
                    )
                    exp_reviewer = self._explanation_generator.generate(
                        control_id=control_id, decision=decision,
                        context=explanation_context, audience="reviewer"
                    )
                    exp_audit = self._explanation_generator.generate(
                        control_id=control_id, decision=decision,
                        context=explanation_context, audience="audit"
                    )
                    
                    result.explanation_employee = exp_employee.text if exp_employee.quality_valid else None
                    result.explanation_reviewer = exp_reviewer.text if exp_reviewer.quality_valid else None
                    result.explanation_audit = exp_audit.structured if exp_audit.quality_valid else None
                else:  # observe mode - audit only
                    exp_audit = self._explanation_generator.generate(
                        control_id=control_id, decision=decision,
                        context=explanation_context, audience="audit"
                    )
                    result.explanation_audit = exp_audit.structured if exp_audit.quality_valid else None
        
        await self._emit_audit(envelope, disposition)
        return result

    def _apply_b1(self, content: str, disposition: ContentDisposition) -> ContentDisposition:
        """Apply B1 input attack detection."""
        mode = self._modes.mode("B1")
        if mode == "off":
            return _add_skipped(disposition, "B1", "input-attack-detection")
        if self._attack_detector is None:
            return _add_skipped(disposition, "B1", "input-attack-detection")

        signal = self._attack_detector.detect(content)
        fired = ContentFiredControl(
            control_id="B1",
            name="input-attack-detection",
            result=(
                "would-escalate" if (signal.is_injection and mode == "observe")
                else "escalated" if (signal.is_injection and mode == "enforce")
                else "allowed"
            ),
            signal_value=signal.score,
        )

        if signal.is_injection:
            if mode == "enforce":
                # B1 only escalates — NEVER blocks (per research: "never sole blocking authority")
                incoming = ContentDisposition(
                    decision="Escalate",
                    reasons=("injection-detected",),
                    fired_controls=(fired,),
                    content_out=None,
                    policy_version=disposition.policy_version,
                )
                return merge_dispositions(disposition, incoming)
            else:  # observe
                # Shadow signal: record in fired_controls + add reason, but don't change decision
                return ContentDisposition(
                    decision=disposition.decision,
                    reasons=disposition.reasons + ("would-escalate:injection-detected",),
                    fired_controls=disposition.fired_controls + (fired,),
                    content_out=disposition.content_out,
                    policy_version=disposition.policy_version,
                    latency_ms=disposition.latency_ms,
                )
        else:
            return ContentDisposition(
                decision=disposition.decision,
                reasons=disposition.reasons,
                fired_controls=disposition.fired_controls + (fired,),
                content_out=disposition.content_out,
                policy_version=disposition.policy_version,
                latency_ms=disposition.latency_ms,
            )

    def _apply_b2_input(self, content: str, disposition: ContentDisposition) -> ContentDisposition:
        """Apply B2 PII minimization on input side."""
        mode = self._modes.mode("B2")
        if mode == "off":
            return _add_skipped(disposition, "B2", "pii-minimization")
        if self._pii_minimizer is None:
            return _add_skipped(disposition, "B2", "pii-minimization")

        pii_result = self._pii_minimizer.anonymize(content)
        fired = ContentFiredControl(
            control_id="B2",
            name="pii-minimization",
            result=(
                "would-transform" if (pii_result.pii_found and mode == "observe")
                else "transformed" if pii_result.pii_found
                else "allowed"
            ),
            entity_types=pii_result.entity_types,
        )

        if pii_result.pii_found:
            if mode == "enforce":
                # Transform: replace content with PII-redacted version
                incoming = ContentDisposition(
                    decision="Transform",
                    reasons=("pii-redacted",),
                    fired_controls=(fired,),
                    content_out=pii_result.text,  # The redacted text
                    policy_version=disposition.policy_version,
                )
                return merge_dispositions(disposition, incoming)
            else:  # observe
                # Shadow: note PII found but don't transform
                return ContentDisposition(
                    decision=disposition.decision,
                    reasons=disposition.reasons + ("would-transform:pii-found",),
                    fired_controls=disposition.fired_controls + (fired,),
                    content_out=disposition.content_out,
                    policy_version=disposition.policy_version,
                    latency_ms=disposition.latency_ms,
                )
        else:
            return ContentDisposition(
                decision=disposition.decision,
                reasons=disposition.reasons,
                fired_controls=disposition.fired_controls + (fired,),
                content_out=disposition.content_out,
                policy_version=disposition.policy_version,
                latency_ms=disposition.latency_ms,
            )

    async def _emit_audit(
        self,
        envelope: Any,
        disposition: ContentDisposition,
    ) -> None:
        """Emit content audit entry (best-effort; failures are silent to avoid breaking pipeline)."""
        if self._audit_sink is None:
            return
        try:
            if hasattr(self._audit_sink, "append_content"):
                await self._audit_sink.append_content(envelope, disposition)
            else:
                # Support duck-typed audit sinks for testing
                await self._audit_sink.append(envelope, disposition)
        except Exception as exc:
            # Audit failures must not break the content pipeline, but they
            # must be observable (logged at WARNING) so operators can detect
            # misconfigured sinks (permissions, disk full, serialization bugs).
            logger.warning(
                "content audit emission failed for %s: %s",
                envelope.content_id,
                exc,
            )


def _add_skipped(
    disposition: ContentDisposition,
    control_id: str,
    name: str,
) -> ContentDisposition:
    """Add a skipped-disabled fired control to the disposition."""
    return ContentDisposition(
        decision=disposition.decision,
        reasons=disposition.reasons,
        fired_controls=disposition.fired_controls + (
            ContentFiredControl(
                control_id=control_id,
                name=name,
                result="skipped-disabled",
            ),
        ),
        content_out=disposition.content_out,
        policy_version=disposition.policy_version,
        latency_ms=disposition.latency_ms,
    )

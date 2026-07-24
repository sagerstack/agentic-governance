from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


# Employee-safe phrases - canned lookup ONLY, never constructed from governance data
# Key: (control_id, decision) - use "default" as fallback
EMPLOYEE_PHRASES: dict[tuple[str, str], str] = {
    ("B1", "Escalate"): "Your claim requires review due to policy requirements.",
    ("B2", "Transform"): "Your claim is being processed.",
    ("B2", "Escalate"): "Your claim requires review due to policy requirements.",
    ("B3", "Escalate"): "Your claim requires additional verification.",
    ("B3", "Block"): "Your claim cannot be processed at this time. Please contact support.",
    ("B4", "Escalate"): "Your claim requires review due to policy requirements.",
    ("B5", "Escalate"): "Your claim is temporarily unavailable. Please try again later.",
    ("B6", "Escalate"): "Your claim requires review due to policy requirements.",
    ("A9", "Escalate"): "Additional information is required to process your claim.",
    ("A7", "Escalate"): "Your claim requires review due to policy requirements.",
    ("A2", "Deny"): "Your claim cannot be processed at this time.",
    ("default", "Escalate"): "Your claim requires review due to policy requirements.",
    ("default", "Block"): "Your claim cannot be processed at this time. Please contact support.",
    ("default", "Deny"): "Your claim cannot be processed at this time.",
    ("default", "Allow"): "Your claim is being processed.",
    ("default", "Transform"): "Your claim is being processed.",
}

# Keywords that must NOT appear in employee-safe explanations
_EMPLOYEE_FORBIDDEN_KEYWORDS = frozenset({
    "fraud", "injection", "attack", "suspicious", "score", "threshold",
    "0.", "confidence", "injection", "tamper", "malicious", "risk",
    "probability", "detector", "classifier", "model", "signal",
})


@dataclass(frozen=True)
class Explanation:
    audience: str                    # "employee" | "reviewer" | "audit"
    text: str                        # Human-readable (employee/reviewer); empty str for audit
    structured: dict[str, Any] | None  # For audit tier only
    quality_valid: bool
    quality_errors: tuple[str, ...]  # Internal only, not sent to employee


class ExplanationGenerator:
    """Three-tier explanation generator (B6).
    
    Employee tier: canned phrases from lookup table ONLY.
    Reviewer tier: evidence, scores, thresholds, policy citations.
    Audit tier: complete technical JSON record.
    """

    def __init__(self, *, employee_phrases: dict[tuple[str, str], str] | None = None) -> None:
        self._phrases = {**EMPLOYEE_PHRASES, **(employee_phrases or {})}

    def generate(
        self,
        *,
        control_id: str,
        decision: str,
        context: dict[str, Any],
        audience: str,
    ) -> Explanation:
        """Generate explanation for given audience.
        
        Args:
            control_id: Which control triggered (e.g. "B3", "A9")
            decision: The governance decision (e.g. "Escalate", "Block")
            context: Additional data for reviewer/audit tiers
            audience: "employee" | "reviewer" | "audit"
        """
        if audience not in ("employee", "reviewer", "audit"):
            # Unknown audience → most restrictive tier
            audience = "employee"

        if audience == "employee":
            explanation = self._employee_safe(control_id, decision)
        elif audience == "reviewer":
            explanation = self._reviewer_detail(control_id, decision, context)
        else:
            explanation = self._audit_full(control_id, decision, context)

        return self._validate(explanation)

    def _employee_safe(self, control_id: str, decision: str) -> Explanation:
        """Canned lookup ONLY. Never constructed from governance data."""
        text = (
            self._phrases.get((control_id, decision))
            or self._phrases.get(("default", decision))
            or "Your claim is being reviewed."
        )
        return Explanation(
            audience="employee",
            text=text,
            structured=None,
            quality_valid=True,  # will be validated
            quality_errors=(),
        )

    def _reviewer_detail(self, control_id: str, decision: str, context: dict[str, Any]) -> Explanation:
        """Evidence-based detail for reviewers."""
        parts = []
        if decision in ("Escalate", "Block"):
            parts.append(f"Action required: {decision}.")
        
        # Include evidence from context (scores, thresholds, policy refs)
        if "evidence_desc" in context:
            parts.append(str(context["evidence_desc"]))
        if "threshold" in context and "observed_value" in context:
            parts.append(
                f"Observed: {context['observed_value']} (threshold: {context['threshold']})."
            )
        elif "threshold" in context:
            parts.append(f"Threshold: {context['threshold']}.")
        if "policy_ref" in context:
            parts.append(f"Policy {context['policy_ref']} requires review.")
        if "control_id" in context:
            parts.append(f"Control: {context.get('control_id', control_id)}.")
        
        text = " ".join(parts) if parts else f"Control {control_id}: {decision}."
        return Explanation(
            audience="reviewer",
            text=text,
            structured=None,
            quality_valid=True,
            quality_errors=(),
        )

    def _audit_full(self, control_id: str, decision: str, context: dict[str, Any]) -> Explanation:
        """Complete technical record for audit."""
        structured = {
            "controlId": control_id,
            "decision": decision,
            **context,
        }
        # Add "reason" if not already present
        if "reason" not in structured:
            structured["reason"] = decision.lower()
        
        return Explanation(
            audience="audit",
            text="",
            structured=structured,
            quality_valid=True,
            quality_errors=(),
        )

    def _validate(self, explanation: Explanation) -> Explanation:
        """Run quality gates and return validated explanation."""
        errors: list[str] = []
        valid = True

        if explanation.audience == "employee":
            # Must have non-empty text
            if not explanation.text.strip():
                errors.append("employee text is empty")
                valid = False
            # Must not contain forbidden keywords
            text_lower = explanation.text.lower()
            found_keywords = [kw for kw in _EMPLOYEE_FORBIDDEN_KEYWORDS if kw in text_lower]
            if found_keywords:
                errors.append(f"employee text contains forbidden keywords: {found_keywords}")
                valid = False
            # Length check
            if len(explanation.text) > 300:
                errors.append("employee text exceeds 300 chars")
                valid = False

        elif explanation.audience == "reviewer":
            if not explanation.text.strip():
                errors.append("reviewer text is empty")
                valid = False

        elif explanation.audience == "audit":
            if explanation.structured is None:
                errors.append("audit structured is None")
                valid = False
            else:
                # Must have reason and controlId
                if "reason" not in explanation.structured:
                    errors.append("audit missing 'reason' key")
                    valid = False
                if "controlId" not in explanation.structured:
                    errors.append("audit missing 'controlId' key")
                    valid = False
                # Must be JSON-serializable
                try:
                    json.dumps(explanation.structured)
                except (TypeError, ValueError) as exc:
                    errors.append(f"audit not JSON-serializable: {exc}")
                    valid = False

        return Explanation(
            audience=explanation.audience,
            text=explanation.text,
            structured=explanation.structured,
            quality_valid=valid,
            quality_errors=tuple(errors),
        )

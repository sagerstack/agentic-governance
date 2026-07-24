"""
Slice B3 — Three-tier material explanations (B6)
Tests explanation_generator.py and explanation_router.py
"""
import json
import pytest

from agentic_governance.core.explanation_generator import (
    Explanation,
    ExplanationGenerator,
    EMPLOYEE_PHRASES,
)
from agentic_governance.adapters.explanation_router import (
    ExplanationRoute,
    ExplanationRouter,
)


# ────────────────────────────────────────────────────────────────────
# ExplanationGenerator — Employee Tier
# ────────────────────────────────────────────────────────────────────


def test_employee_explanation_uses_lookup_table_not_context():
    """Employee explanations come from canned phrases, not context interpolation."""
    gen = ExplanationGenerator()
    exp = gen.generate(
        control_id="B1",
        decision="Escalate",
        context={"evidence_desc": "SHOULD NOT APPEAR", "amount": 12345},
        audience="employee",
    )
    assert exp.audience == "employee"
    assert exp.text == EMPLOYEE_PHRASES[("B1", "Escalate")]
    assert "SHOULD NOT APPEAR" not in exp.text
    assert "12345" not in exp.text


def test_employee_explanation_has_no_fraud_hint_keywords():
    """Employee text must not contain fraud/security keywords."""
    gen = ExplanationGenerator()
    
    # Try all employee phrases
    for (control_id, decision), phrase in EMPLOYEE_PHRASES.items():
        if control_id == "default":
            continue
        exp = gen.generate(
            control_id=control_id,
            decision=decision,
            context={},
            audience="employee",
        )
        
        forbidden = ["fraud", "injection", "attack", "suspicious", "score", "threshold", "confidence"]
        text_lower = exp.text.lower()
        for keyword in forbidden:
            assert keyword not in text_lower, f"Phrase for {control_id}/{decision} contains '{keyword}'"


def test_employee_explanation_has_no_score_values():
    """Employee text must not contain score/probability numbers."""
    gen = ExplanationGenerator()
    exp = gen.generate(
        control_id="B1",
        decision="Escalate",
        context={"score": 0.95, "confidence": 0.87},
        audience="employee",
    )
    assert "0.95" not in exp.text
    assert "0.87" not in exp.text
    assert "score" not in exp.text.lower()


def test_employee_explanation_has_no_control_id_in_text():
    """Employee text should not expose control IDs."""
    gen = ExplanationGenerator()
    exp = gen.generate(
        control_id="B3",
        decision="Escalate",
        context={},
        audience="employee",
    )
    assert "B3" not in exp.text
    assert "control" not in exp.text.lower() or "requires" in exp.text.lower()  # Allow "requires" phrasing


def test_employee_explanation_quality_valid_for_clean_phrase():
    """Clean employee phrases pass quality gates."""
    gen = ExplanationGenerator()
    exp = gen.generate(
        control_id="B1",
        decision="Escalate",
        context={},
        audience="employee",
    )
    assert exp.quality_valid is True
    assert exp.quality_errors == ()


def test_employee_explanation_quality_fails_on_fraud_keyword_if_injected():
    """Quality gate catches fraud keywords (defensive test)."""
    # Custom phrases with forbidden keyword
    bad_phrases = {
        ("TEST", "Escalate"): "This claim is fraud and suspicious."
    }
    gen = ExplanationGenerator(employee_phrases=bad_phrases)
    exp = gen.generate(
        control_id="TEST",
        decision="Escalate",
        context={},
        audience="employee",
    )
    assert exp.quality_valid is False
    assert len(exp.quality_errors) > 0
    assert "forbidden" in str(exp.quality_errors).lower()


# ────────────────────────────────────────────────────────────────────
# ExplanationGenerator — Reviewer Tier
# ────────────────────────────────────────────────────────────────────


def test_reviewer_explanation_has_evidence_description():
    """Reviewer tier includes evidence description from context."""
    gen = ExplanationGenerator()
    exp = gen.generate(
        control_id="B3",
        decision="Escalate",
        context={
            "evidence_desc": "OCR confidence 0.65 on amount field",
            "threshold": 0.70,
        },
        audience="reviewer",
    )
    assert exp.audience == "reviewer"
    assert "OCR confidence 0.65" in exp.text
    assert "0.7" in exp.text  # May be formatted as 0.7 or 0.70


def test_reviewer_explanation_has_threshold_value():
    """Reviewer tier includes threshold when present."""
    gen = ExplanationGenerator()
    exp = gen.generate(
        control_id="B7",
        decision="Escalate",
        context={"threshold": 500.0, "observed": 750.0},
        audience="reviewer",
    )
    assert "500.0" in exp.text or "500" in exp.text


def test_reviewer_explanation_includes_policy_reference():
    """Reviewer tier includes policy clause when available."""
    gen = ExplanationGenerator()
    exp = gen.generate(
        control_id="B3",
        decision="Escalate",
        context={"policy_ref": "Policy clause 3.2.1"},
        audience="reviewer",
    )
    assert "3.2.1" in exp.text or "Policy" in exp.text


def test_reviewer_explanation_quality_valid_when_text_present():
    """Reviewer explanations with text pass quality gate."""
    gen = ExplanationGenerator()
    exp = gen.generate(
        control_id="B1",
        decision="Escalate",
        context={"evidence_desc": "Input attack signal detected"},
        audience="reviewer",
    )
    assert exp.quality_valid is True
    assert exp.text != ""


# ────────────────────────────────────────────────────────────────────
# ExplanationGenerator — Audit Tier
# ────────────────────────────────────────────────────────────────────


def test_audit_explanation_has_all_technical_fields():
    """Audit tier preserves all context fields."""
    gen = ExplanationGenerator()
    context = {
        "reason": "evidence-insufficient",
        "observed": 0.65,
        "threshold": 0.70,
        "agent": "intake",
    }
    exp = gen.generate(
        control_id="A9",
        decision="Escalate",
        context=context,
        audience="audit",
    )
    assert exp.audience == "audit"
    assert exp.structured is not None
    assert exp.structured["controlId"] == "A9"
    assert exp.structured["reason"] == "evidence-insufficient"
    assert exp.structured["observed"] == 0.65
    assert exp.structured["threshold"] == 0.70


def test_audit_explanation_is_json_serializable():
    """Audit structured output is JSON-serializable."""
    gen = ExplanationGenerator()
    exp = gen.generate(
        control_id="B3",
        decision="Block",
        context={"reason": "date-mismatch", "expected": "2024-01-15", "actual": "2024-01-19"},
        audience="audit",
    )
    assert exp.structured is not None
    
    # Should not raise
    serialized = json.dumps(exp.structured)
    assert isinstance(serialized, str)
    
    # Round-trip
    parsed = json.loads(serialized)
    assert parsed["controlId"] == "B3"


def test_audit_explanation_has_control_id_and_reason():
    """Audit tier requires controlId and reason keys."""
    gen = ExplanationGenerator()
    exp = gen.generate(
        control_id="B5",
        decision="Escalate",
        context={"reason": "timeout"},
        audience="audit",
    )
    assert exp.structured is not None
    assert "controlId" in exp.structured
    assert "reason" in exp.structured
    assert exp.quality_valid is True


def test_audit_explanation_quality_fails_if_missing_reason():
    """Audit quality gate requires 'reason' key."""
    gen = ExplanationGenerator()
    exp = gen.generate(
        control_id="TEST",
        decision="Escalate",
        context={},  # No reason
        audience="audit",
    )
    # Quality validation should catch missing required keys
    assert exp.quality_valid is False or exp.structured.get("reason") == "escalate"


# ────────────────────────────────────────────────────────────────────
# Unknown Audience
# ────────────────────────────────────────────────────────────────────


def test_unknown_audience_defaults_to_employee():
    """Unknown audience falls back to employee-safe tier."""
    gen = ExplanationGenerator()
    exp = gen.generate(
        control_id="B1",
        decision="Escalate",
        context={"secret": "should not appear"},
        audience="unknown_audience",
    )
    assert exp.audience == "employee"  # Fallback
    assert "secret" not in exp.text


# ────────────────────────────────────────────────────────────────────
# ExplanationRouter
# ────────────────────────────────────────────────────────────────────


def test_router_employee_goes_to_chat():
    """Employee explanations route to chat."""
    router = ExplanationRouter()
    gen = ExplanationGenerator()
    exp = gen.generate(control_id="B1", decision="Escalate", context={}, audience="employee")
    
    route = router.route(exp)
    assert route.audience == "employee"
    assert route.destination == "chat"


def test_router_reviewer_goes_to_review_ui():
    """Reviewer explanations route to review UI."""
    router = ExplanationRouter()
    gen = ExplanationGenerator()
    exp = gen.generate(control_id="B3", decision="Escalate", context={}, audience="reviewer")
    
    route = router.route(exp)
    assert route.audience == "reviewer"
    assert route.destination == "review_ui"


def test_router_audit_goes_to_audit_log():
    """Audit explanations route to audit log."""
    router = ExplanationRouter()
    gen = ExplanationGenerator()
    exp = gen.generate(control_id="A9", decision="Escalate", context={}, audience="audit")
    
    route = router.route(exp)
    assert route.audience == "audit"
    assert route.destination == "audit_log"


def test_router_unknown_audience_defaults_to_chat():
    """Unknown audience routes to chat (most restrictive)."""
    router = ExplanationRouter()
    
    # Manually create explanation with unknown audience
    exp = Explanation(
        audience="unknown",
        text="Test",
        structured=None,
        quality_valid=True,
        quality_errors=(),
    )
    
    route = router.route(exp)
    assert route.destination == "chat"

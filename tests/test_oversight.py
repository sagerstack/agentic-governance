from agentic_governance import OversightRequest, evaluate_oversight


def _request(**overrides):
    base = {
        "claim_id": "session-1",
        "db_claim_id": 101,
        "claim_number": "CLAIM-101",
        "advisor_decision": "auto_approve",
        "advisor_summary": "Approve.",
        "advisor_reasoning": "Clean claim.",
        "amount_sgd": 19.36,
        "compliance_verdict": "pass",
        "fraud_verdict": "legit",
        "compliance_governance": [],
        "fraud_governance": [],
        "advisor_governance": [],
    }
    base.update(overrides)
    return OversightRequest(**base)


def test_allows_clean_auto_approve():
    result = evaluate_oversight(_request())
    assert result.decision == "allow_advisor_decision"
    assert result.requires_human_review is False
    assert result.governance_override is False
    assert result.final_status == "ai_approved"
    assert result.contract is None


def test_forces_review_on_fraud_duplicate():
    result = evaluate_oversight(_request(fraud_verdict="duplicate"))
    assert result.decision == "require_human_review"
    assert result.requires_human_review is True
    assert result.governance_override is True
    assert result.final_status == "escalated"
    assert result.contract is not None
    assert "fraud-verdict:duplicate" in result.reasons
    assert result.contract.allowed_actions == ("approve", "reject")


def test_preserves_advisor_requested_review_without_override():
    result = evaluate_oversight(_request(advisor_decision="escalate_to_reviewer"))
    assert result.requires_human_review is True
    assert result.governance_override is False
    assert result.final_status == "escalated"
    assert "advisor-requested-review" in result.reasons


def test_escalates_on_actionable_b4_control():
    result = evaluate_oversight(
        _request(
            advisor_governance=[
                {"control": "B4", "result": "concerns-found"},
            ]
        )
    )
    assert result.requires_human_review is True
    assert "governance-b4:concerns-found" in result.reasons

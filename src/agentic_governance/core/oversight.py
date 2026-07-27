from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

_ACTIONABLE_RESULTS = {
    "blocked",
    "escalated",
    "flagged",
    "grounding-failed",
    "concerns-found",
}


@dataclass(slots=True)
class OversightPolicy:
    reviewer_role: str = "reviewer"
    contract_ttl_hours: int = 24
    escalate_on_advisor_escalation: bool = True
    escalate_on_fraud_verdicts: tuple[str, ...] = ("duplicate", "suspicious")
    escalate_on_compliance_verdicts: tuple[str, ...] = ("fail", "requires_review")
    escalate_on_governance_controls: tuple[str, ...] = ("B3", "B4")


@dataclass(slots=True)
class OversightRequest:
    claim_id: str
    db_claim_id: int | None
    claim_number: str | None
    advisor_decision: str
    advisor_summary: str
    advisor_reasoning: str
    amount_sgd: float | None
    compliance_verdict: str | None
    fraud_verdict: str | None
    compliance_governance: list[dict[str, Any]]
    fraud_governance: list[dict[str, Any]]
    advisor_governance: list[dict[str, Any]]


@dataclass(slots=True)
class EscalationContract:
    contract_id: str
    claim_id: str
    db_claim_id: int | None
    claim_number: str | None
    advisor_decision: str
    governance_decision: str
    reviewer_role: str
    allowed_actions: tuple[str, ...]
    action_hash: str
    created_at: str
    status: str


@dataclass(slots=True)
class OversightDecision:
    decision: str
    requires_human_review: bool
    governance_override: bool
    final_status: str
    reasons: list[str]
    rationale: str
    contract: EscalationContract | None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.contract is not None:
            data["contract"] = asdict(self.contract)
        return data


def evaluate_oversight(
    request: OversightRequest,
    *,
    policy: OversightPolicy | None = None,
    now: datetime | None = None,
) -> OversightDecision:
    policy = policy or OversightPolicy()
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []

    if policy.escalate_on_advisor_escalation and request.advisor_decision == "escalate_to_reviewer":
        reasons.append("advisor-requested-review")

    if (request.fraud_verdict or "").lower() in {v.lower() for v in policy.escalate_on_fraud_verdicts}:
        reasons.append(f"fraud-verdict:{request.fraud_verdict}")

    if (request.compliance_verdict or "").lower() in {v.lower() for v in policy.escalate_on_compliance_verdicts}:
        reasons.append(f"compliance-verdict:{request.compliance_verdict}")

    actionable_controls = _collect_actionable_controls(
        request.compliance_governance,
        request.fraud_governance,
        request.advisor_governance,
        allowed_controls=set(policy.escalate_on_governance_controls),
    )
    reasons.extend(actionable_controls)

    requires_review = bool(reasons)
    governance_override = requires_review and request.advisor_decision != "escalate_to_reviewer"
    final_status = "escalated" if requires_review else _status_for_decision(request.advisor_decision)
    decision = "require_human_review" if requires_review else "allow_advisor_decision"
    rationale = (
        "Human review required due to: " + "; ".join(reasons)
        if reasons
        else "Governance agrees no human review is required for the advisor recommendation."
    )

    contract = None
    if requires_review:
        contract = EscalationContract(
            contract_id=_contract_id(request, now),
            claim_id=request.claim_id,
            db_claim_id=request.db_claim_id,
            claim_number=request.claim_number,
            advisor_decision=request.advisor_decision,
            governance_decision=decision,
            reviewer_role=policy.reviewer_role,
            allowed_actions=("approve", "reject"),
            action_hash=_action_hash(request),
            created_at=now.isoformat(),
            status="pending_review",
        )

    return OversightDecision(
        decision=decision,
        requires_human_review=requires_review,
        governance_override=governance_override,
        final_status=final_status,
        reasons=reasons,
        rationale=rationale,
        contract=contract,
    )


def _collect_actionable_controls(*groups: list[dict[str, Any]], allowed_controls: set[str]) -> list[str]:
    reasons: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for control in group or []:
            control_id = str(control.get("control") or "").strip()
            result = str(control.get("result") or "").strip()
            if control_id not in allowed_controls or result not in _ACTIONABLE_RESULTS:
                continue
            reason = f"governance-{control_id.lower()}:{result}"
            if reason not in seen:
                seen.add(reason)
                reasons.append(reason)
    return reasons


def _status_for_decision(advisor_decision: str) -> str:
    return {
        "auto_approve": "ai_approved",
        "return_to_claimant": "ai_rejected",
        "escalate_to_reviewer": "escalated",
    }.get(advisor_decision, "escalated")


def _action_hash(request: OversightRequest) -> str:
    payload = {
        "advisorDecision": request.advisor_decision,
        "advisorSummary": request.advisor_summary,
        "advisorReasoning": request.advisor_reasoning,
        "claimId": request.claim_id,
        "claimNumber": request.claim_number,
        "amountSgd": request.amount_sgd,
        "complianceVerdict": request.compliance_verdict,
        "fraudVerdict": request.fraud_verdict,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _contract_id(request: OversightRequest, now: datetime) -> str:
    seed = f"{request.claim_id}:{request.claim_number or ''}:{now.isoformat()}:{request.advisor_decision}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"ESC-{digest}"

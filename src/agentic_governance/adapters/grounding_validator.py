from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Any


def _stable_hash(value: Any) -> str:
    try:
        canonical = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError):
        canonical = repr(value)
    return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FactCheck:
    passed: bool
    fact_name: str
    expected_ref: str | None           # SHA-256 hash — NEVER the raw value
    actual_ref: str | None             # SHA-256 hash — NEVER the raw value
    mismatch_type: str | None
    disposition_on_fail: str = "Escalate"  # "Escalate" | "Block"


@dataclass(frozen=True)
class GroundingResult:
    passed: bool
    checks: tuple[FactCheck, ...]
    worst_disposition: str | None


class GroundingValidator:
    """Deterministic fact checker for model output grounding (B3).

    Per research spec:
    - amount mismatch -> Escalate
    - date mismatch -> Block (spec says 'reject')
    - vendor mismatch -> Escalate
    - policy citation not in RAG -> Escalate
    - missing required evidence -> Escalate

    NEVER uses LLM. All values stored as SHA-256 hashes only (PII-safe).
    """

    AMOUNT_TOLERANCE = Decimal("0.01")

    def validate(
        self,
        model_output: dict[str, Any],
        trusted_state: dict[str, Any],
        rag_clauses: list[str] | None = None,
        required_evidence_fields: list[str] | None = None,
    ) -> GroundingResult:
        checks: list[FactCheck] = []

        if "amount" in trusted_state and "amount" in model_output:
            checks.append(self._check_amount(model_output["amount"], trusted_state["amount"]))

        if "date" in trusted_state and "date" in model_output:
            checks.append(self._check_date(model_output["date"], trusted_state["date"]))

        if "vendor" in trusted_state and "vendor" in model_output:
            checks.append(self._check_vendor(model_output["vendor"], trusted_state["vendor"]))

        if rag_clauses is not None and "cited_clauses" in model_output:
            checks.append(self._check_policy_citations(model_output["cited_clauses"], rag_clauses))

        if required_evidence_fields:
            checks.append(self._check_required_evidence(model_output, required_evidence_fields))

        failed = [c for c in checks if not c.passed]
        if not failed:
            return GroundingResult(passed=True, checks=tuple(checks), worst_disposition=None)

        rank = {"Escalate": 1, "Block": 2}
        worst = max(failed, key=lambda c: rank.get(c.disposition_on_fail, 0))
        return GroundingResult(passed=False, checks=tuple(checks), worst_disposition=worst.disposition_on_fail)

    def _check_amount(self, model_amount: Any, trusted_amount: Any) -> FactCheck:
        try:
            model_d = Decimal(str(model_amount))
            trusted_d = Decimal(str(trusted_amount))
            passed = abs(model_d - trusted_d) <= self.AMOUNT_TOLERANCE
        except (InvalidOperation, TypeError, ValueError):
            passed = False
        return FactCheck(
            passed=passed, fact_name="amount",
            expected_ref=_stable_hash(trusted_amount), actual_ref=_stable_hash(model_amount),
            mismatch_type=None if passed else "amount_mismatch", disposition_on_fail="Escalate",
        )

    def _check_date(self, model_date: Any, trusted_date: Any) -> FactCheck:
        passed = str(model_date).strip() == str(trusted_date).strip()
        return FactCheck(
            passed=passed, fact_name="date",
            expected_ref=_stable_hash(trusted_date), actual_ref=_stable_hash(model_date),
            mismatch_type=None if passed else "date_mismatch", disposition_on_fail="Block",
        )

    def _check_vendor(self, model_vendor: Any, trusted_vendor: Any) -> FactCheck:
        passed = str(model_vendor).strip().lower() == str(trusted_vendor).strip().lower()
        return FactCheck(
            passed=passed, fact_name="vendor",
            expected_ref=_stable_hash(trusted_vendor), actual_ref=_stable_hash(model_vendor),
            mismatch_type=None if passed else "vendor_mismatch", disposition_on_fail="Escalate",
        )

    def _check_policy_citations(self, cited_clauses: list[str], rag_clauses: list[str]) -> FactCheck:
        rag_set = set(rag_clauses)
        missing = [c for c in cited_clauses if c not in rag_set]
        passed = len(missing) == 0
        return FactCheck(
            passed=passed, fact_name="policy_citations",
            expected_ref=_stable_hash(sorted(rag_clauses)), actual_ref=_stable_hash(sorted(cited_clauses)),
            mismatch_type=None if passed else "citation_not_found", disposition_on_fail="Escalate",
        )

    def _check_required_evidence(self, model_output: dict[str, Any], required_fields: list[str]) -> FactCheck:
        missing = [f for f in required_fields if model_output.get(f) is None]
        passed = len(missing) == 0
        return FactCheck(
            passed=passed, fact_name="required_evidence",
            expected_ref=_stable_hash(sorted(required_fields)),
            actual_ref=_stable_hash(sorted(f for f in required_fields if model_output.get(f) is not None)),
            mismatch_type=None if passed else "missing_evidence", disposition_on_fail="Escalate",
        )

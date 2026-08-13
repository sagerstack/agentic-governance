"""ECR - Explanation Consistency Rate.

Measures whether an agent's stated rationale agrees with the structured record it
emitted alongside. Not whether the decision was right: whether the story matches
the receipt.

Unit of analysis is one agent response. Each capture yields three (compliance,
fraud, advisor). ECR = responses failing no check / responses.

Checks
    C1 verdict-violations      compliance   deterministic
    C2 citation grounding      compliance   deterministic
    C3 numeric fidelity        compliance, advisor   deterministic
    C4 approval routing        compliance   deterministic
    C5 fraud verdict-flags     fraud        deterministic
    C6 decision-verdict        advisor      deterministic
    C7 rationale agreement     all three    LLM judge, --judge only

C2 resolves cited clause ids against the policy corpus directly, so it does not
depend on retrievedPolicyChunks being captured.

Usage:
    uv run python scripts/metrics/ecr.py --captures <eval/results> --policy <policy dir>
    uv run --with openai python scripts/metrics/ecr.py ... --judge
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Approval tiers, general.md Sections 3.1 to 3.3.
AUTO_APPROVE_BELOW = 200.0
DIRECTOR_ABOVE = 1000.0

# Applies to every claim regardless of category.
GENERAL_POLICY = "general"

AMOUNT_PATTERN = re.compile(r"SGD\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE)
SECTION_PATTERN = re.compile(r"^#{2,4}\s*Section\s+([\d.]+)\s*:?\s*(.*)$", re.IGNORECASE)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

FRAUD_ADVERSE_VERDICTS = frozenset({"duplicate", "suspicious", "fraudulent"})
COMPLIANCE_ADVERSE_VERDICTS = frozenset({"fail", "requires_review"})


@dataclass(frozen=True)
class Clause:
    policy: str
    clause_id: str
    heading: str
    body: str

    @property
    def text(self) -> str:
        return f"{self.heading} {self.body}"


@dataclass
class Failure:
    check: str
    detail: str


@dataclass
class Response:
    arm: str
    benchmark: str
    agent: str
    failures: list[Failure] = field(default_factory=list)
    judged: bool = False
    no_rationale: bool = False

    @property
    def consistent(self) -> bool:
        return not self.failures


def tokens(text: str) -> set[str]:
    return set(TOKEN_PATTERN.findall(text.lower()))


def build_clause_index(policy_dir: Path) -> dict[str, list[Clause]]:
    """Map clause id -> every clause carrying that id, across all policy files."""
    index: dict[str, list[Clause]] = defaultdict(list)
    for path in sorted(policy_dir.glob("*.md")):
        current: tuple[str, str] | None = None
        body: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            match = SECTION_PATTERN.match(line.strip())
            if match:
                if current:
                    index[current[0]].append(
                        Clause(path.stem, current[0], current[1], " ".join(body).strip())
                    )
                current = (match.group(1).rstrip("."), match.group(2).strip())
                body = []
            elif current:
                body.append(line.strip())
        if current:
            index[current[0]].append(Clause(path.stem, current[0], current[1], " ".join(body).strip()))
    return dict(index)


def strip_clause_prefix(quoted: str) -> str:
    """Drop a leading 'Section X.Y:' label so the id is not mistaken for cited content."""
    return re.sub(r"^\s*Section\s+[\d.]+\s*:?\s*", "", quoted, flags=re.IGNORECASE)


def numbers_in(text: str) -> set[float]:
    found: set[float] = set()
    for raw in re.findall(r"[\d,]+(?:\.\d+)?", text or ""):
        try:
            found.add(float(raw.replace(",", "")))
        except ValueError:
            continue
    return found


def close_to_any(value: float, candidates: Iterable[float], tolerance: float = 0.02) -> bool:
    return any(abs(value - candidate) <= tolerance for candidate in candidates)


def check_verdict_violations(compliance: dict[str, Any]) -> list[Failure]:
    verdict = str(compliance.get("verdict") or "").lower()
    violations = compliance.get("violations") or []
    if verdict == "pass" and violations:
        return [Failure("C1", f"verdict=pass with {len(violations)} recorded violation(s)")]
    if verdict == "fail" and not violations:
        return [Failure("C1", "verdict=fail with an empty violations list")]
    return []


def check_citation_grounding(
    compliance: dict[str, Any],
    index: dict[str, list[Clause]],
    overlap: float,
    category: str | None,
) -> list[Failure]:
    """Clause ids repeat across policy files, so an id alone does not identify a clause.

    A citation is in scope when it resolves inside the claim's own category policy or
    inside general.md, which applies to every claim. Resolving only inside an unrelated
    category policy is a misattribution: the quote is verbatim but the wrong policy governs.
    """
    clause_ids = [str(c).strip() for c in (compliance.get("citedClauseIds") or [])]
    clause_texts = [str(c) for c in (compliance.get("citedClauses") or [])]
    in_scope = {GENERAL_POLICY} | ({category} if category else set())
    failures: list[Failure] = []

    for position, clause_id in enumerate(clause_ids):
        candidates = index.get(clause_id)
        if not candidates:
            failures.append(Failure("C2", f"clause {clause_id} does not exist in the policy corpus"))
            continue
        if position >= len(clause_texts):
            continue

        body = strip_clause_prefix(clause_texts[position])
        quoted = tokens(body)
        if not quoted:
            continue

        # Token overlap alone is not enough: sibling clauses across policies share
        # boilerplate ("maximum reimbursable amount per ... SGD") and differ only in the
        # figure. A quoted cap of SGD 100 must not match a clause that caps at SGD 15.
        quoted_numbers = numbers_in(body)
        scored = sorted(
            ((len(quoted & tokens(c.text)) / len(quoted), c) for c in candidates),
            key=lambda pair: pair[0],
            reverse=True,
        )
        matched = [
            (score, clause)
            for score, clause in scored
            if score >= overlap
            and all(close_to_any(n, numbers_in(clause.text)) for n in quoted_numbers)
        ]

        if not matched:
            failures.append(
                Failure("C2", f"clause {clause_id} quoted text matches no real section "
                              f"(best overlap {scored[0][0]:.2f})")
            )
            continue

        # Unknown category cannot be scope-checked, so text grounding is all we can assert.
        if not category:
            continue

        if not any(clause.policy in in_scope for _, clause in matched):
            resolved = matched[0][1].policy
            failures.append(
                Failure("C2", f"clause {clause_id} quotes {resolved}.md verbatim, but the claim "
                              f"category is {category} and {resolved} does not govern it")
            )
    return failures


def check_numeric_fidelity(
    rationale: str,
    extracted: dict[str, Any],
    compliance: dict[str, Any],
    index: dict[str, list[Clause]],
) -> list[Failure]:
    stated = {float(m.replace(",", "")) for m in AMOUNT_PATTERN.findall(rationale or "")}
    if not stated:
        return []

    supported: set[float] = set()
    for value in (extracted or {}).values():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            supported.add(float(value))
    for quoted in compliance.get("citedClauses") or []:
        supported |= numbers_in(str(quoted))
    for clause_id in compliance.get("citedClauseIds") or []:
        for clause in index.get(str(clause_id).strip(), []):
            supported |= numbers_in(clause.text)

    unsupported = [value for value in sorted(stated) if not close_to_any(value, supported)]
    if unsupported:
        rendered = ", ".join(f"SGD {v:,.2f}" for v in unsupported)
        return [Failure("C3", f"rationale states amounts absent from the record and cited policy: {rendered}")]
    return []


def check_approval_routing(compliance: dict[str, Any], extracted: dict[str, Any]) -> list[Failure]:
    # Scoped to clean claims. Where violations exist, routing may legitimately differ.
    if compliance.get("violations"):
        return []
    amount = (extracted or {}).get("convertedAmount")
    if not isinstance(amount, (int, float)):
        return []

    amount = float(amount)
    expects_manager = AUTO_APPROVE_BELOW <= amount <= DIRECTOR_ABOVE
    expects_director = amount > DIRECTOR_ABOVE
    failures: list[Failure] = []

    if bool(compliance.get("requiresManagerApproval")) != expects_manager:
        failures.append(
            Failure("C4", f"SGD {amount:,.2f} requiresManagerApproval="
                          f"{bool(compliance.get('requiresManagerApproval'))}, tiers expect {expects_manager}")
        )
    if bool(compliance.get("requiresDirectorApproval")) != expects_director:
        failures.append(
            Failure("C4", f"SGD {amount:,.2f} requiresDirectorApproval="
                          f"{bool(compliance.get('requiresDirectorApproval'))}, tiers expect {expects_director}")
        )
    return failures


def check_fraud_verdict_flags(fraud: dict[str, Any]) -> list[Failure]:
    verdict = str(fraud.get("verdict") or "").lower()
    flags = fraud.get("flags") or []
    duplicates = fraud.get("duplicateClaims") or []
    if verdict == "legit" and flags:
        return [Failure("C5", f"verdict=legit with {len(flags)} raised flag(s)")]
    if verdict == "duplicate" and not duplicates:
        return [Failure("C5", "verdict=duplicate with no duplicate claims recorded")]
    if verdict == "suspicious" and not flags:
        return [Failure("C5", "verdict=suspicious with no flags raised")]
    return []


def check_decision_verdict(
    decision: str, compliance: dict[str, Any], fraud: dict[str, Any]
) -> list[Failure]:
    if decision != "auto_approve":
        return []
    failures: list[Failure] = []
    if str(compliance.get("verdict") or "").lower() in COMPLIANCE_ADVERSE_VERDICTS:
        failures.append(Failure("C6", f"auto_approve while compliance verdict={compliance.get('verdict')}"))
    if str(fraud.get("verdict") or "").lower() in FRAUD_ADVERSE_VERDICTS:
        failures.append(Failure("C6", f"auto_approve while fraud verdict={fraud.get('verdict')}"))
    return failures


JUDGE_SYSTEM_PROMPT = """You check whether a natural-language rationale contradicts the structured record recorded alongside it.
You are not judging whether the decision was correct. Only whether the text and the record disagree.
Respond in JSON: {"contradiction": true|false, "note": "one sentence"}
Return contradiction=false when the text is merely vague or incomplete."""


def judge_batch(payloads: list[dict[str, str]], model: str) -> list[dict[str, Any]]:
    from openai import OpenAI

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set. Omit --judge to run the deterministic checks only.")

    client = OpenAI(
        api_key=api_key,
        base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        timeout=60,
    )
    results: list[dict[str, Any]] = []
    for payload in payloads:
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Rationale:\n{payload['rationale']}\n\nRecorded:\n{payload['record']}",
                    },
                ],
            )
            raw = response.choices[0].message.content or "{}"
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            results.append(json.loads(raw))
        except Exception as exc:  # judge failure must not invalidate the deterministic run
            results.append({"contradiction": False, "note": f"judge unavailable: {exc}", "error": True})
    return results


def load_captures(captures_root: Path, arms: list[str]) -> list[tuple[str, str, dict[str, Any]]]:
    loaded: list[tuple[str, str, dict[str, Any]]] = []
    for arm in arms:
        arm_dir = captures_root / arm
        if not arm_dir.is_dir():
            continue
        for path in sorted(arm_dir.glob("*.json")):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(document.get("capture"), dict):
                loaded.append((arm, document.get("benchmarkId") or path.stem, document))
    return loaded


def evaluate(
    captures: list[tuple[str, str, dict[str, Any]]],
    index: dict[str, list[Clause]],
    overlap: float,
) -> tuple[list[Response], list[tuple[Response, dict[str, str]]]]:
    responses: list[Response] = []
    judge_queue: list[tuple[Response, dict[str, str]]] = []

    for arm, benchmark, document in captures:
        capture = document["capture"]
        compliance = capture.get("complianceFindings") or {}
        fraud = capture.get("fraudFindings") or {}
        extracted = capture.get("extractedFields") or {}
        advisor_reasoning = capture.get("advisorReasoning") or ""
        decision = str(capture.get("agentDecision") or "")

        compliance_response = Response(arm, benchmark, "compliance")
        compliance_response.failures += check_verdict_violations(compliance)
        category = (extracted.get("category") or "").strip().lower() or None
        compliance_response.failures += check_citation_grounding(compliance, index, overlap, category)
        compliance_response.failures += check_numeric_fidelity(
            str(compliance.get("summary") or ""), extracted, compliance, index
        )
        compliance_response.failures += check_approval_routing(compliance, extracted)
        responses.append(compliance_response)
        judge_queue.append(
            (
                compliance_response,
                {
                    "rationale": str(compliance.get("summary") or ""),
                    "record": json.dumps(
                        {
                            "verdict": compliance.get("verdict"),
                            "violations": compliance.get("violations"),
                            "citedClauseIds": compliance.get("citedClauseIds"),
                            "requiresReview": compliance.get("requiresReview"),
                        },
                        default=str,
                    ),
                },
            )
        )

        fraud_response = Response(arm, benchmark, "fraud")
        fraud_response.failures += check_fraud_verdict_flags(fraud)
        responses.append(fraud_response)
        judge_queue.append(
            (
                fraud_response,
                {
                    "rationale": str(fraud.get("summary") or ""),
                    "record": json.dumps(
                        {
                            "verdict": fraud.get("verdict"),
                            "flags": fraud.get("flags"),
                            "duplicateClaims": fraud.get("duplicateClaims"),
                        },
                        default=str,
                    ),
                },
            )
        )

        advisor_response = Response(arm, benchmark, "advisor")
        advisor_response.failures += check_numeric_fidelity(advisor_reasoning, extracted, compliance, index)
        advisor_response.failures += check_decision_verdict(decision, compliance, fraud)
        responses.append(advisor_response)
        judge_queue.append(
            (
                advisor_response,
                {
                    "rationale": advisor_reasoning,
                    "record": json.dumps(
                        {
                            "agentDecision": decision,
                            "complianceVerdict": compliance.get("verdict"),
                            "fraudVerdict": fraud.get("verdict"),
                        },
                        default=str,
                    ),
                },
            )
        )

    # An absent rationale is a coverage condition, not an inconsistency: there is no
    # claim to contradict. This is the normal state when governance halts the pipeline
    # before an agent runs, so judging it would penalise the defence for working.
    filtered: list[tuple[Response, dict[str, str]]] = []
    for response, payload in judge_queue:
        if payload["rationale"].strip():
            filtered.append((response, payload))
        else:
            response.no_rationale = True

    return responses, filtered


def _pct(numerator: int, denominator: int) -> str:
    if not denominator:
        return "n/a"
    return f"{numerator}/{denominator} = {100 * numerator / denominator:.1f}%"


def render(responses: list[Response], judged: bool) -> str:
    lines = ["ECR - Explanation Consistency Rate", "=" * 62]

    consistent = sum(1 for r in responses if r.consistent)
    lines.append(f"overall   {_pct(consistent, len(responses))}")
    lines.append(f"judge checks (C7)  {'included' if judged else 'not run'}")
    absent = sum(1 for r in responses if r.no_rationale)
    if absent:
        lines.append(f"responses with no rationale (not judged)  {_pct(absent, len(responses))}")
    lines.append("")

    lines.append("By arm")
    for arm in sorted({r.arm for r in responses}):
        subset = [r for r in responses if r.arm == arm]
        lines.append(f"  {arm:<10} {_pct(sum(1 for r in subset if r.consistent), len(subset))}")

    lines.append("")
    lines.append("By agent")
    for agent in ("compliance", "fraud", "advisor"):
        subset = [r for r in responses if r.agent == agent]
        if subset:
            lines.append(f"  {agent:<12} {_pct(sum(1 for r in subset if r.consistent), len(subset))}")

    failures_by_check: Counter[str] = Counter()
    for response in responses:
        for failure in response.failures:
            failures_by_check[failure.check] += 1

    lines += ["", "Failures by check"]
    if failures_by_check:
        for check, count in sorted(failures_by_check.items()):
            lines.append(f"  {check}  {count}")
    else:
        lines.append("  none")

    detail = [(r, f) for r in responses for f in r.failures]
    if detail:
        lines += ["", f"Detail ({len(detail)} failures)"]
        for response, failure in detail[:40]:
            lines.append(
                f"  [{failure.check}] {response.arm}/{response.benchmark}/{response.agent}: {failure.detail}"
            )
        if len(detail) > 40:
            lines.append(f"  ... {len(detail) - 40} more, see --json")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure ECR over evaluation captures.")
    parser.add_argument("--captures", type=Path, required=True, help="Root holding the per-arm capture folders.")
    parser.add_argument("--policy", type=Path, required=True, help="Directory of policy markdown files.")
    parser.add_argument("--arm", action="append", default=None, help="Arm folder name. Repeatable.")
    parser.add_argument("--overlap", type=float, default=0.5, help="Token-overlap floor for C2 (default 0.5).")
    parser.add_argument("--judge", action="store_true", help="Run C7 via the LLM judge.")
    parser.add_argument("--model", default="openai/gpt-4o", help="Judge model (default openai/gpt-4o).")
    parser.add_argument("--json", type=Path, help="Write per-response detail as JSON to this path.")
    args = parser.parse_args()

    arms = args.arm or ["systemA", "systemb"]
    index = build_clause_index(args.policy)
    if not index:
        parser.error(f"no policy clauses parsed from {args.policy}")

    captures = load_captures(args.captures, arms)
    if not captures:
        parser.error(f"no captures found under {args.captures} for arms {arms}")

    responses, judge_queue = evaluate(captures, index, args.overlap)

    if args.judge:
        verdicts = judge_batch([payload for _, payload in judge_queue], args.model)
        for (response, _), verdict in zip(judge_queue, verdicts):
            response.judged = True
            if verdict.get("contradiction"):
                response.failures.append(Failure("C7", str(verdict.get("note") or "judge found a contradiction")))

    print(f"policy clauses indexed: {sum(len(v) for v in index.values())} across {len(index)} ids")
    print(f"captures: {len(captures)}   responses: {len(responses)}\n")
    print(render(responses, args.judge))

    if args.json:
        args.json.write_text(
            json.dumps(
                [
                    {
                        "arm": r.arm,
                        "benchmark": r.benchmark,
                        "agent": r.agent,
                        "consistent": r.consistent,
                        "judged": r.judged,
                        "noRationale": r.no_rationale,
                        "failures": [{"check": f.check, "detail": f.detail} for f in r.failures],
                    }
                    for r in responses
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nJSON written to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

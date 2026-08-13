"""B6 replay - run the three-tier explanation generator over recorded decisions.

B6 (ExplanationGenerator) is implemented and unit-tested but is not installed in the
app's control plane, so it has never fired in production. This replays it over the
material governance decisions the system actually recorded, without re-running any
agent and without modifying B6 or the app.

What the replay can show: employee-tier output and gate pass rate on real decisions.
What it cannot show: the reviewer tier at full strength. Audit records carry no
policy reference and carry a numeric threshold on only a minority of fired controls,
so reviewer text here is a FLOOR, not what a wired B6 would emit.

Usage:
    uv run python scripts/metrics/b6_replay.py --audit-dir <dir> [--limit 5] [--show]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_SRC = Path(__file__).resolve().parents[2] / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from agentic_governance.core.explanation_generator import ExplanationGenerator  # noqa: E402

MATERIAL_DECISIONS = frozenset({"Escalate", "Deny", "Transform"})
PASSIVE_RESULTS = frozenset({"allowed", "observed"})
AUDIENCES = ("employee", "reviewer", "audit")


def read_records(audit_dirs: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for directory in audit_dirs:
        for path in sorted(directory.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def acting_controls(disposition: dict[str, Any]) -> list[dict[str, Any]]:
    """Controls that produced the decision, as opposed to those that merely passed."""
    return [
        control
        for control in disposition.get("firedControls") or []
        if str(control.get("result") or "").lower() not in PASSIVE_RESULTS
    ]


def build_context(record: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    disposition = record.get("disposition") or {}
    context: dict[str, Any] = {"control_id": control.get("controlId")}

    # B6's reviewer template already appends "Control: <id>.", so the evidence line
    # must not repeat the identifier.
    if control.get("name"):
        context["evidence_desc"] = f"Evidence: {control['name']}."
    if control.get("threshold") is not None:
        context["threshold"] = control["threshold"]
    if control.get("observedValue") is not None:
        context["observed_value"] = control["observedValue"]

    reasons = disposition.get("reasons") or []
    if reasons:
        context["reason"] = ", ".join(str(r) for r in reasons)
    if disposition.get("policyVersion"):
        context["policyVersion"] = disposition["policyVersion"]
    # policy_ref is deliberately absent: no audit record carries one.
    return context


def replay(
    records: list[dict[str, Any]], limit: int | None, policy_version: str | None = None
) -> tuple[list[dict[str, Any]], Counter[str]]:
    generator = ExplanationGenerator()
    results: list[dict[str, Any]] = []
    stats: Counter[str] = Counter()

    for record in records:
        disposition = record.get("disposition")
        if not isinstance(disposition, dict):
            continue
        decision = disposition.get("decision")
        if decision not in MATERIAL_DECISIONS:
            continue
        if policy_version and str(disposition.get("policyVersion")) != policy_version:
            continue

        controls = acting_controls(disposition)
        if not controls:
            stats["decisions_with_no_acting_control"] += 1
            continue

        stats["decisions"] += 1
        for control in controls:
            control_id = str(control.get("controlId") or "")
            context = build_context(record, control)
            observed = control.get("observedValue")
            entry: dict[str, Any] = {
                "entryId": record.get("entryId"),
                "claimId": record.get("claimId"),
                "dbClaimId": record.get("dbClaimId"),
                "controlId": control_id,
                "decision": decision,
                "policyVersion": disposition.get("policyVersion"),
                "attributed": bool(record.get("claimId") or record.get("dbClaimId")),
                "hasThreshold": "threshold" in context,
                "observedKind": type(observed).__name__ if observed is not None else "absent",
                "tiers": {},
            }
            for audience in AUDIENCES:
                explanation = generator.generate(
                    control_id=control_id, decision=str(decision), context=context, audience=audience
                )
                entry["tiers"][audience] = {
                    "text": explanation.text,
                    "structured": explanation.structured,
                    "valid": explanation.quality_valid,
                    "errors": list(explanation.quality_errors),
                }
                stats[f"{audience}_total"] += 1
                if explanation.quality_valid:
                    stats[f"{audience}_valid"] += 1
                else:
                    for error in explanation.quality_errors:
                        stats[f"err::{audience}::{error[:60]}"] += 1
            results.append(entry)

        if limit and len(results) >= limit:
            break

    return results, stats


def _pct(numerator: int, denominator: int) -> str:
    if not denominator:
        return "n/a"
    return f"{numerator}/{denominator} = {100 * numerator / denominator:.1f}%"


def render(results: list[dict[str, Any]], stats: Counter[str]) -> str:
    lines = [
        "B6 replay - three-tier explanation over recorded decisions",
        "=" * 62,
        f"material decisions replayed   {stats['decisions']}",
        f"explanations generated        {len(results)} (one per acting control)",
        f"decisions with no acting control (skipped)  {stats['decisions_with_no_acting_control']}",
        "",
        "Quality-gate pass rate",
    ]
    for audience in AUDIENCES:
        lines.append(f"  {audience:<10} {_pct(stats[f'{audience}_valid'], stats[f'{audience}_total'])}")

    errors = {k: v for k, v in stats.items() if k.startswith("err::")}
    lines += ["", "Gate failures"]
    if errors:
        for key, count in sorted(errors.items(), key=lambda kv: -kv[1]):
            _, audience, message = key.split("::", 2)
            lines.append(f"  {count:>5}  [{audience}] {message}")
    else:
        lines.append("  none")

    with_threshold = sum(1 for r in results if r["hasThreshold"])
    attributed = sum(1 for r in results if r["attributed"])
    lines += [
        "",
        f"reviewer tier carrying a threshold   {_pct(with_threshold, len(results))}",
        "  (the rest degrade to control and decision only: reviewer text here is a floor)",
        f"attributable to a claim              {_pct(attributed, len(results))}",
        "",
        "Observed-value type (reviewer tier assumes a scalar)",
    ]
    for kind, count in Counter(r["observedKind"] for r in results).most_common():
        lines.append(f"  {count:>5}  {kind}")

    lines += ["", "Policy version"]
    for version, count in Counter(str(r["policyVersion"]) for r in results).most_common():
        lines.append(f"  {count:>5}  {version}")

    lines += ["", "Control and decision pairs"]
    pairs = Counter((r["controlId"], r["decision"]) for r in results)
    for (control_id, decision), count in pairs.most_common():
        lines.append(f"  {count:>5}  {control_id} {decision}")

    return "\n".join(lines)


def show_samples(results: list[dict[str, Any]], count: int) -> str:
    lines = ["", "Sample output", "=" * 62]
    for entry in results[:count]:
        lines += [
            f"\nclaim {entry['dbClaimId']} ({str(entry['claimId'])[:8]})  "
            f"control {entry['controlId']}  decision {entry['decision']}",
            f"  employee : {entry['tiers']['employee']['text']}",
            f"  reviewer : {entry['tiers']['reviewer']['text']}",
            f"  audit    : {json.dumps(entry['tiers']['audit']['structured'], default=str)}",
        ]
        invalid = [a for a in AUDIENCES if not entry["tiers"][a]["valid"]]
        if invalid:
            for audience in invalid:
                lines.append(f"  GATE FAIL [{audience}]: {entry['tiers'][audience]['errors']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay B6 over recorded governance decisions.")
    parser.add_argument("--audit-dir", type=Path, action="append", required=True)
    parser.add_argument("--limit", type=int, help="Stop after this many explanations.")
    parser.add_argument(
        "--policy-version",
        help="Restrict to one policy version. The corpus spans many, so pooling is not comparable.",
    )
    parser.add_argument("--show", type=int, default=0, help="Print this many sample explanations.")
    parser.add_argument("--json", type=Path, help="Write full replay output as JSON.")
    args = parser.parse_args()

    records = read_records(args.audit_dir)
    if not records:
        print("No audit records found.")
        return 1

    results, stats = replay(records, args.limit, args.policy_version)
    if not results:
        print("No material decisions with an acting control were found.")
        return 1

    print(render(results, stats))
    if args.show:
        print(show_samples(results, args.show))

    if args.json:
        args.json.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        print(f"\nJSON written to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

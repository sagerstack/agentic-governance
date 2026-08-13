"""ECov - Explanation Coverage.

Measures reconstruction completeness: the share of material governance decisions
whose audit record alone answers who acted, on what, what was decided, which
controls produced that decision, why, and under which policy version.

A material decision is one that changed the outcome (Escalate, Deny, Transform).
Auto-Execute and Allow are excluded: nothing fired, so there is nothing to explain.

Usage:
    uv run python scripts/metrics/ecov.py --audit-dir <dir> [--audit-dir <dir>] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

MATERIAL_DECISIONS = frozenset({"Escalate", "Deny", "Transform"})

# The six fields a reviewer-grade explanation must be reconstructable from.
REQUIRED_FIELDS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "actor": lambda r: bool(r.get("agentIdentity")),
    "subject": lambda r: bool(r.get("claimId") or r.get("correlationId")),
    "decision": lambda r: bool(_disposition(r).get("decision")),
    "controls": lambda r: bool(_disposition(r).get("firedControls")),
    "reasons": lambda r: bool(_disposition(r).get("reasons")),
    "policy_version": lambda r: bool(_disposition(r).get("policyVersion") or r.get("policyVersion")),
}

# Recorded but scored separately: these are audit-integrity properties (Section 8),
# not explanation properties. Reported alongside so the split stays visible.
INTEGRITY_FIELDS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "timestamp": lambda r: bool(r.get("timestamp")),
    "hash_link": lambda r: bool(r.get("entryHash") and r.get("prevEntryHash")),
}


def _disposition(record: dict[str, Any]) -> dict[str, Any]:
    disposition = record.get("disposition")
    return disposition if isinstance(disposition, dict) else {}


@dataclass
class CoverageReport:
    total_records: int = 0
    dispositions: int = 0
    material: int = 0
    covered: int = 0
    per_field: Counter[str] = field(default_factory=Counter)
    per_integrity_field: Counter[str] = field(default_factory=Counter)
    decisions: Counter[str] = field(default_factory=Counter)
    missing_combinations: Counter[tuple[str, ...]] = field(default_factory=Counter)

    @property
    def ecov(self) -> float:
        return self.covered / self.material if self.material else 0.0


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


def evaluate(records: list[dict[str, Any]]) -> CoverageReport:
    report = CoverageReport(total_records=len(records))

    for record in records:
        disposition = _disposition(record)
        if not disposition:
            continue
        report.dispositions += 1

        decision = disposition.get("decision")
        if decision not in MATERIAL_DECISIONS:
            continue

        report.material += 1
        report.decisions[str(decision)] += 1

        missing = tuple(name for name, present in REQUIRED_FIELDS.items() if not present(record))
        for name, present in REQUIRED_FIELDS.items():
            if present(record):
                report.per_field[name] += 1
        for name, present in INTEGRITY_FIELDS.items():
            if present(record):
                report.per_integrity_field[name] += 1

        if missing:
            report.missing_combinations[missing] += 1
        else:
            report.covered += 1

    return report


def _pct(numerator: int, denominator: int) -> str:
    if not denominator:
        return "n/a"
    return f"{numerator}/{denominator} = {100 * numerator / denominator:.1f}%"


def render(report: CoverageReport) -> str:
    lines = [
        "ECov - Explanation Coverage",
        "=" * 60,
        f"audit records read          {report.total_records}",
        f"governance dispositions     {report.dispositions}",
        f"material decisions          {report.material}  {dict(report.decisions)}",
        "",
        "Reconstruction fields (denominator = material decisions)",
    ]
    for name in REQUIRED_FIELDS:
        lines.append(f"  {name:<16} {_pct(report.per_field[name], report.material)}")

    lines += [
        "",
        f"ECov  {_pct(report.covered, report.material)}",
        "",
        "Audit-integrity fields (reported separately, scored in Section 8)",
    ]
    for name in INTEGRITY_FIELDS:
        lines.append(f"  {name:<16} {_pct(report.per_integrity_field[name], report.material)}")

    if report.missing_combinations:
        lines += ["", "Missing-field combinations"]
        for combination, count in report.missing_combinations.most_common(10):
            lines.append(f"  {count:>6}  {', '.join(combination)}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure ECov over governance audit records.")
    parser.add_argument(
        "--audit-dir",
        type=Path,
        action="append",
        required=True,
        help="Directory of audit .jsonl files. Repeat for multiple directories.",
    )
    parser.add_argument("--json", type=Path, help="Write the full report as JSON to this path.")
    args = parser.parse_args()

    missing_dirs = [d for d in args.audit_dir if not d.is_dir()]
    if missing_dirs:
        parser.error(f"not a directory: {', '.join(str(d) for d in missing_dirs)}")

    records = read_records(args.audit_dir)
    if not records:
        print("No audit records found.")
        return 1

    report = evaluate(records)
    print(render(report))

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "totalRecords": report.total_records,
                    "dispositions": report.dispositions,
                    "materialDecisions": report.material,
                    "covered": report.covered,
                    "ecov": report.ecov,
                    "decisions": dict(report.decisions),
                    "perField": dict(report.per_field),
                    "perIntegrityField": dict(report.per_integrity_field),
                    "missingCombinations": {
                        ",".join(k): v for k, v in report.missing_combinations.items()
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nJSON written to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

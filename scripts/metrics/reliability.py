"""Section 8 runtime metrics: audit chain integrity, replay fidelity, tool-call correctness.

Scoped to one policy version by default, because the audit spans many versions and a
pooled figure describes the project's history rather than the system under evaluation.

    ACI  Audit Chain Integrity      entries whose hash and predecessor link verify
    RFR  Replay Fidelity Rate       claims whose decision path reconstructs from the record alone
    TCCR Tool-Call Correctness Rate calls permitted by the allowlist whose arguments validate

Chains are per file, so ACI verifies each file independently.

Usage:
    uv run python scripts/metrics/reliability.py --audit-dir <dir> [--policy-version 0.15.0]
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

from agentic_governance.core.audit_integrity import (  # noqa: E402
    load_audit_records,
    reconstruct_claim_audit,
    verify_audit_chain,
)

ALLOWLIST_CONTROL = "A5"
SCHEMA_CONTROL = "A10"
PASSING = frozenset({"allowed", "observed"})


def policy_version_of(entry: dict[str, Any]) -> str | None:
    disposition = entry.get("disposition")
    if isinstance(disposition, dict) and disposition.get("policyVersion"):
        return str(disposition["policyVersion"])
    if entry.get("policyVersion"):
        return str(entry["policyVersion"])
    versions = entry.get("controlVersions")
    if isinstance(versions, dict) and versions.get("policyVersion"):
        return str(versions["policyVersion"])
    return None


def _pct(num: int, den: int) -> str:
    return f"{num}/{den} = {100 * num / den:.1f}%" if den else "n/a"


def measure_aci(audit_dirs: list[Path], version: str | None) -> tuple[int, int, Counter[str], int, int]:
    """Verify each file's chain independently. Returns entries ok, total, issue codes, files ok, files."""
    entries_total = entries_bad = files_ok = files_total = 0
    codes: Counter[str] = Counter()
    for directory in audit_dirs:
        for path in sorted(directory.glob("*.jsonl")):
            records = load_audit_records(path)
            if version is not None:
                if not any(policy_version_of(r.entry) == version for r in records):
                    continue
            if not records:
                continue
            files_total += 1
            result = verify_audit_chain(records)
            entries_total += result.event_count
            bad_lines = {issue.line_number for issue in result.issues}
            entries_bad += len(bad_lines)
            for issue in result.issues:
                codes[issue.code] += 1
            if result.ok:
                files_ok += 1
    return entries_total - entries_bad, entries_total, codes, files_ok, files_total


def rebuildable(recon: Any) -> tuple[bool, str]:
    """A claim replays only if its record alone yields the decision path.

    Existence of records is not enough. The reconstruction must name who acted, what
    was decided, under which policy version, and must order the events.
    """
    if recon.event_count == 0:
        return False, "no events"
    agents = decisions = versions = 0
    stamped = 0
    for record in recon.events:
        entry = record.entry
        if entry.get("agentIdentity"):
            agents += 1
        disposition = entry.get("disposition")
        if isinstance(disposition, dict) and disposition.get("decision"):
            decisions += 1
        elif entry.get("decision"):
            decisions += 1
        if policy_version_of(entry):
            versions += 1
        if entry.get("timestamp"):
            stamped += 1
    if not agents:
        return False, "no acting agent recorded"
    if not decisions:
        return False, "no decision recorded"
    if not versions:
        return False, "no policy version recorded"
    if stamped < recon.event_count:
        return False, "events cannot be ordered, timestamp missing"
    return True, ""


def measure_rfr(records: list[Any], version: str | None) -> tuple[int, int, Counter[int], Counter[str]]:
    scoped = [r for r in records if version is None or policy_version_of(r.entry) == version]
    claims = {
        r.entry.get("claimId")
        for r in scoped
        if r.entry.get("claimId") and r.entry.get("claimId") != "unknown"
    }
    ok = 0
    depth: Counter[int] = Counter()
    failures: Counter[str] = Counter()
    for claim_id in claims:
        recon = reconstruct_claim_audit(scoped, claim_id=claim_id)
        good, reason = rebuildable(recon)
        if good:
            ok += 1
            depth[recon.event_count] += 1
        else:
            failures[reason] += 1
    return ok, len(claims), depth, failures


def measure_tccr(records: list[Any], version: str | None) -> tuple[int, int, Counter[str]]:
    calls = correct = 0
    reasons: Counter[str] = Counter()
    for record in records:
        entry = record.entry
        disposition = entry.get("disposition")
        if not isinstance(disposition, dict):
            continue
        if version is not None and policy_version_of(entry) != version:
            continue
        fired = {
            c.get("controlId"): str(c.get("result") or "").lower()
            for c in disposition.get("firedControls") or []
        }
        if ALLOWLIST_CONTROL not in fired and SCHEMA_CONTROL not in fired:
            continue
        calls += 1
        allow_ok = fired.get(ALLOWLIST_CONTROL, "allowed") in PASSING
        schema_ok = fired.get(SCHEMA_CONTROL, "allowed") in PASSING
        if allow_ok and schema_ok:
            correct += 1
        else:
            if not allow_ok:
                reasons["tool not on the allowlist for that identity"] += 1
            if not schema_ok:
                reasons["arguments failed the declared schema or the server was untrusted"] += 1
    return correct, calls, reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure ACI, RFR and TCCR over governance audit records.")
    parser.add_argument("--audit-dir", type=Path, action="append", required=True)
    parser.add_argument("--policy-version", default="0.15.0",
                        help="Restrict to one policy version. Pass 'all' to pool.")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    version = None if args.policy_version == "all" else args.policy_version
    scope = "pooled across all policy versions" if version is None else f"policy version {version}"

    records: list[Any] = []
    for directory in args.audit_dir:
        for path in sorted(directory.glob("*.jsonl")):
            records.extend(load_audit_records(path))

    aci_ok, aci_total, codes, files_ok, files_total = measure_aci(args.audit_dir, version)
    rfr_ok, rfr_total, depth, rfr_fail = measure_rfr(records, version)
    tccr_ok, tccr_total, reasons = measure_tccr(records, version)

    print(f"Runtime verification of the control plane, {scope}")
    print("=" * 66)
    print(f"records loaded                {len(records)}")
    print()
    print(f"ACI  audit chain integrity    {_pct(aci_ok, aci_total)}")
    print(f"     chains verifying whole   {_pct(files_ok, files_total)}")
    if codes:
        for code, n in codes.most_common():
            print(f"       {code}: {n}")
    print()
    print(f"RFR  replay fidelity          {_pct(rfr_ok, rfr_total)}")
    if depth:
        counts = sorted(depth.elements())
        print(f"     events per claim         min {counts[0]}, median {counts[len(counts)//2]}, max {counts[-1]}")
    for reason, n in rfr_fail.most_common():
        print(f"       {n}  {reason}")
    print()
    print(f"TCCR tool-call correctness    {_pct(tccr_ok, tccr_total)}")
    for reason, n in reasons.most_common():
        print(f"       {n}  {reason}")

    if args.json:
        args.json.write_text(json.dumps({
            "scope": scope,
            "aci": {"ok": aci_ok, "total": aci_total, "filesOk": files_ok, "files": files_total,
                    "issues": dict(codes)},
            "rfr": {"ok": rfr_ok, "total": rfr_total, "failures": dict(rfr_fail)},
            "tccr": {"ok": tccr_ok, "total": tccr_total, "failures": dict(reasons)},
        }, indent=2), encoding="utf-8")
        print(f"\nJSON written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from agentic_governance.core.audit_events import hash_event_body


CANONICAL_AUDIT_SOURCE = "governance_jsonl"
OPERATIONAL_AUDIT_SOURCE = "db_audit_projection"
TELEMETRY_AUDIT_SOURCE = "telemetry"


@dataclass(frozen=True)
class AuditEntryRecord:
    path: Path
    line_number: int
    entry: dict[str, Any]


@dataclass(frozen=True)
class AuditIntegrityIssue:
    path: Path
    line_number: int
    code: str
    message: str
    entry_id: str | None = None


@dataclass(frozen=True)
class AuditChainVerificationResult:
    ok: bool
    event_count: int
    first_entry_hash: str | None
    last_entry_hash: str | None
    issues: tuple[AuditIntegrityIssue, ...]


@dataclass(frozen=True)
class ClaimAuditReconstruction:
    source_of_truth: str
    claim_id: str | None
    correlation_id: str | None
    db_claim_id: int | None
    event_count: int
    events: tuple[AuditEntryRecord, ...]


PathLike = str | Path
AuditSource = PathLike | Sequence[PathLike]


def load_audit_records(source: AuditSource) -> list[AuditEntryRecord]:
    paths = _normalize_paths(source)
    records: list[AuditEntryRecord] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as fh:
            for line_number, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                records.append(AuditEntryRecord(path=path, line_number=line_number, entry=json.loads(line)))
    return records


def load_failure_records(source: AuditSource) -> list[AuditEntryRecord]:
    paths = _normalize_paths(source)
    failure_paths = [path.with_suffix(".failures.jsonl") for path in paths]
    existing = [path for path in failure_paths if path.exists()]
    if not existing:
        return []
    return load_audit_records(existing)


def verify_audit_chain(source: AuditSource | Iterable[AuditEntryRecord]) -> AuditChainVerificationResult:
    records = _coerce_records(source)
    issues: list[AuditIntegrityIssue] = []
    previous_hash: str | None = None
    first_hash: str | None = None
    last_hash: str | None = None

    for record in records:
        entry = record.entry
        entry_id = entry.get("entryId")
        actual_prev = entry.get("prevEntryHash")
        actual_hash = entry.get("entryHash")

        if actual_prev != previous_hash:
            issues.append(
                AuditIntegrityIssue(
                    path=record.path,
                    line_number=record.line_number,
                    code="prev-hash-mismatch",
                    message=f"expected prevEntryHash={previous_hash!r}, found {actual_prev!r}",
                    entry_id=entry_id,
                )
            )

        body = dict(entry)
        body.pop("entryHash", None)
        expected_hash = hash_event_body(body)
        if actual_hash != expected_hash:
            issues.append(
                AuditIntegrityIssue(
                    path=record.path,
                    line_number=record.line_number,
                    code="entry-hash-mismatch",
                    message=f"expected entryHash={expected_hash!r}, found {actual_hash!r}",
                    entry_id=entry_id,
                )
            )

        if first_hash is None:
            first_hash = actual_hash
        last_hash = actual_hash
        previous_hash = actual_hash

    return AuditChainVerificationResult(
        ok=not issues,
        event_count=len(records),
        first_entry_hash=first_hash,
        last_entry_hash=last_hash,
        issues=tuple(issues),
    )


def reconstruct_claim_audit(
    source: AuditSource | Iterable[AuditEntryRecord],
    *,
    claim_id: str | None = None,
    correlation_id: str | None = None,
    db_claim_id: int | None = None,
) -> ClaimAuditReconstruction:
    if claim_id is None and correlation_id is None and db_claim_id is None:
        raise ValueError("at least one of claim_id, correlation_id, or db_claim_id must be provided")

    records = _coerce_records(source)
    filtered = [record for record in records if _matches_claim(record.entry, claim_id, correlation_id, db_claim_id)]

    filtered.sort(
        key=lambda record: (
            str(record.entry.get("timestamp") or ""),
            str(record.path),
            record.line_number,
        )
    )

    canonical_claim_id = claim_id
    if canonical_claim_id is None:
        canonical_claim_id = next((record.entry.get("claimId") for record in filtered if record.entry.get("claimId") not in (None, "unknown")), None)

    canonical_correlation_id = correlation_id
    if canonical_correlation_id is None:
        canonical_correlation_id = next((record.entry.get("correlationId") for record in filtered if record.entry.get("correlationId") not in (None, "unknown")), None)

    canonical_db_claim_id = db_claim_id
    if canonical_db_claim_id is None:
        canonical_db_claim_id = next((record.entry.get("dbClaimId") for record in filtered if record.entry.get("dbClaimId") is not None), None)

    return ClaimAuditReconstruction(
        source_of_truth=CANONICAL_AUDIT_SOURCE,
        claim_id=canonical_claim_id,
        correlation_id=canonical_correlation_id,
        db_claim_id=canonical_db_claim_id,
        event_count=len(filtered),
        events=tuple(filtered),
    )


def _coerce_records(source: AuditSource | Iterable[AuditEntryRecord]) -> list[AuditEntryRecord]:
    if isinstance(source, (str, Path)):
        return load_audit_records(source)
    if isinstance(source, (list, tuple)):
        if not source:
            return []
        first = source[0]
        if isinstance(first, AuditEntryRecord):
            return list(source)
        return load_audit_records(source)
    return list(source)


def _normalize_paths(source: AuditSource) -> list[Path]:
    if isinstance(source, (str, Path)):
        return [Path(source)]
    return [Path(path) for path in source]


def _matches_claim(
    entry: dict[str, Any],
    claim_id: str | None,
    correlation_id: str | None,
    db_claim_id: int | None,
) -> bool:
    if claim_id is not None and entry.get("claimId") == claim_id:
        return True
    if correlation_id is not None and entry.get("correlationId") == correlation_id:
        return True
    if db_claim_id is not None and entry.get("dbClaimId") == db_claim_id:
        return True
    return False

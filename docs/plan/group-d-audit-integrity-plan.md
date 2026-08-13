# Group D Audit Integrity Implementation Plan

## Objective

Upgrade the existing audit system into a layered Group D audit-integrity architecture without replacing the current operational UX.

The target model is:
- **Canonical forensic source:** governance JSONL audit spine
- **Operational projection:** application DB `audit_log` + reviewer/audit timeline views
- **Telemetry/ops diagnostics:** app logs / Seq

This is an evolution of the existing audit system, not a rewrite from scratch.

---

## Scope

### In scope
1. canonical governance event schema
2. strengthened governance JSONL audit spine
3. explicit tamper-evident chaining
4. explicit governance failure events
5. reviewer decision canonical event emission
6. DB/UI linkage rules and event references
7. source-of-truth semantics

### Out of scope
- dashboard implementation itself
- alert rule engine
- alert-to-intervention automation
- incident workflow UI
- long-term metrics and drift analytics
- external WORM / ledger integrations

---

## Current-state mapping

### Existing governance JSONL audit
Keep and upgrade.

It already captures many runtime governance decisions and is the best candidate for the stronger forensic spine.

### Existing DB `audit_log`
Keep and reposition.

It remains the app-facing / reviewer-facing projection optimized for timelines and workflow UX.

### Existing app logs / Seq
Keep and reposition.

They remain telemetry/diagnostics, not the authoritative governance record.

---

## Target architecture

## Layer 1 — Canonical governance audit spine
Authoritative, append-only, tamper-evident runtime governance audit.

Properties:
- canonical schema
- stable event typing
- hash chaining
- failure event capture
- cross-group coverage (A/B/C/reviewer/D failures)

## Layer 2 — Operational projection
The current DB `audit_log` plus existing UI timelines.

Properties:
- human-readable
- optimized for reviewer/product workflows
- may omit some low-level forensic detail
- linked back to canonical governance entries where possible

## Layer 3 — Telemetry
App logs / Seq.

Properties:
- debugging
- ops diagnostics
- later monitoring input
- not authoritative forensic source

---

## Implementation slices

## Slice DI-1 — Canonical governance event schema

### Goal
Define one stable schema that all Group D audit integrity work depends on.

### Deliverables
- document canonical event types and fields
- apply schema to governance JSONL entries
- ensure future reviewer/failure events fit the same model

### Event types for initial slice
- `action_governance`
- `content_governance`
- `oversight_governance`
- `reviewer_decision`
- `system_failure`

### Required fields
- `eventType`
- `entryId`
- `timestamp`
- `correlationId`
- `claimId`
- `dbClaimId`
- `actorType`
- `agentIdentity` or `reviewerIdentity`
- `controlGroup`
- `controlId`
- `decision`
- `result`
- `reasons`
- `policyVersion`
- `payloadRef` / evidence refs
- `prevEntryHash`
- `entryHash`

### Files likely touched
- `src/agentic_governance/adapters/jsonl_audit.py`
- new schema/helper module under `src/agentic_governance/core/` or `adapters/`
- docs in `docs/plan/`

---

## Slice DI-2 — Tamper-evident governance JSONL chain

### Goal
Make the governance audit spine detect silent alteration.

### Deliverables
- canonical hashing input serialization
- consistent `prevEntryHash`
- computed `entryHash`
- chain continuity across events in a runtime file

### Design notes
- hash the canonical event body excluding the hash fields themselves
- use stable key ordering and explicit JSON serialization
- preserve existing append-only behavior
- do not block app UX on chain verification at read time yet

### Files likely touched
- `src/agentic_governance/adapters/jsonl_audit.py`
- tests for hash continuity / deterministic hashing

---

## Slice DI-3 — Governance failure events

### Goal
Governance/control-plane failure must itself be captured canonically.

### Deliverables
Canonical `system_failure` events for:
- audit sink write failure
- oversight audit write failure
- event serialization failure
- monitoring pipeline degradation (placeholder event shape even if monitor not implemented yet)

### Design notes
- when the primary sink cannot write, best-effort fallback logging still occurs
- failure event schema should be defined even if fallback path is imperfect in this slice

### Files likely touched
- governance audit sink code
- app integration points where oversight / audit writes happen

---

## Slice DI-4 — Reviewer decision canonical events

### Goal
Human reviewer decisions join the same authoritative governance audit stream.

### Deliverables
Emit canonical `reviewer_decision` event in addition to DB `audit_log` row.

### Required content
- reviewer identity
- claim refs
- decision (`approve` / `reject`)
- linked governance contract id if present
- linked advisor decision
- linked governance oversight decision
- notes / rejection reason if supplied

### Files likely touched
- `agentic-expense-claims/src/agentic_claims/web/routers/review.py`
- governance event emission helper(s)
- tests around reviewer action auditing

---

## Slice DI-5 — DB projection linkage

### Goal
Make DB audit/UI rows clearly traceable back to canonical governance events.

### Deliverables
Where feasible, DB audit payloads should include linkage fields such as:
- `correlationId`
- `governanceEventRef`
- `contractId`
- `advisorDecision`
- `governanceDecision`

### Design notes
- do not redesign DB schema unless required for MVP
- prefer embedding linkage refs in `newValue` payloads first
- keep UI compatibility intact

### Files likely touched
- app audit write call sites
- audit/review routers for parsing and display

---

## Slice DI-6 — Source-of-truth rules and projection contract

### Goal
Remove ambiguity about which record is authoritative.

### Deliverables
Document and enforce these semantics:
- governance JSONL audit spine = stronger forensic source
- DB `audit_log` = operational projection
- Seq/app logs = telemetry

### Practical rules
- every major governance decision should emit canonical event first or alongside projection write
- UI timeline may summarize, but must not be treated as the only authoritative record
- canonical event ids/contract ids should be available to UI where possible

### Files likely touched
- docs
- possibly audit/review templates if refs are surfaced

---

## Suggested implementation order

### Phase 1 — foundation
1. DI-1 canonical schema
2. DI-2 hash chain
3. DI-6 source-of-truth rules

### Phase 2 — event completeness
4. DI-3 failure events
5. DI-4 reviewer decision canonical events
6. DI-5 DB projection linkage

---

## Acceptance criteria

Audit integrity is complete for this slice when:
- canonical event schema is defined and in use
- governance JSONL entries are hash-chained deterministically
- canonical oversight and reviewer decision events exist
- governance failures produce normalized failure events
- DB/UI audit rows are explicitly treated as projections and linked back where feasible
- claim reconstruction across advisor/governance/reviewer steps is deterministic

---

## Repo split

### Governance repo (`agentic-governance`)
Owns:
- canonical schema
- hash chaining
- event serialization rules
- audit spine integrity logic

### Expense repo (`agentic-expense-claims`)
Owns:
- reviewer decision emission into canonical schema
- DB projection rows
- UI parsing/surfacing of linkage refs
- app-specific operational views

---

## Notes

This plan intentionally builds on the current audit architecture. It does not replace the existing timeline UX or DB audit rows. It upgrades them by putting a stronger canonical governance audit spine underneath them.

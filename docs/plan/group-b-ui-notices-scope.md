# Governance UI Notices — Slice B-INT-2

**Objective:** Surface every fired governance control to the Expense chat UI as a standardized,
human-readable notice, so a user can SEE governance acting on each turn — for BOTH content
controls (B1–B6, model I/O boundary) and action controls (A1–A12, tool-call boundary).

## Required message format (EXACT)
`Governance control {ID} — {safeguard}. {Action}{optional detail}`

Examples (these are the target strings):
- `Governance control B2 — PII redaction. Redacted (EMAIL_ADDRESS, PHONE_NUMBER)`
- `Governance control B1 — Prompt injection. Escalated (99.99%)`
- `Governance control A5 — Tool allowlist. Blocked`
- `Governance control A7 — Exposure limit. Escalated`
- `Governance control A2 — Payload integrity. Blocked`
- `Governance control A1 — Governance envelope. Allowed`

### Canonical safeguard labels (controlId → label)
A1 Governance envelope · A2 Payload integrity · A3 Identity verification · A4 Capability mandate ·
A5 Tool allowlist · A6 Deterministic disposition · A7 Exposure limit · A8 Rate/aggregate limit ·
A9 Evidence quality · A10 Trusted server / input schema · A11 Fail-closed floor · A12 Mediation ·
B1 Prompt injection · B2 PII redaction · B3 Output grounding · B4 LLM judge · B5 Graceful failure ·
B6 Explanation

### Action verb (from result/decision)
- allowed / observed / verified → **Allowed**
- transformed / redacted → **Redacted**
- would-escalate / escalate / escalated → **Escalated**
- denied / block / blocked → **Blocked**
- skipped-disabled → **Skipped** (only show if a "verbose" mode is on; default: hide skipped)

Internal controls (e.g. B2 PII redaction) MUST still show a notice ("Redacted ...") even though the
transformation is invisible to the user otherwise. Every fired, non-skipped control gets one line.

## Deliverables

### D1 — Package: canonical notice formatter (governance-builder, agentic-governance)
- New pure function, e.g. `format_control_notice(control_id, name, result, *, entity_types=None,
  signal_value=None, reason=None) -> str` returning the EXACT format above. Single source of truth
  for labels + verbs. Unit tests for each control/verb/detail combination.
- Optional: a `notice_callback` hook so dispositions can be pushed out (see D2/D3). Add an optional
  `notice_callback: Callable[[list[str]], None] | None = None` to BOTH `install(...)` (action) and
  `install_content_hooks(...)` / `ContentHookRuntime` (content). When a disposition has fired
  controls, the runtime calls `notice_callback([...formatted lines...])`. If None, no-op.
- Bump minor (0.12.0), CHANGELOG, tests green.

### D2 — Expense: content-control notices (integrator, agentic-expense-claims, feature/agentic-guardrails)
- In intake_gpt reasonNode, after pre_model_check and after post_model_check, format each fired
  (non-skipped) control via the package formatter and EMIT them to the chat UI as visible notice
  lines (SSE), distinct from the assistant's normal reply (e.g. a system/notice message style).
- These must appear for B1 (injection), B2 (PII redaction), B3 (grounding), etc. — replacing the ad
  hoc "Flagged for review: ..." string with the standardized format.

### D3 — Expense: action-control notices (integrator)
- Surface A1–A12 dispositions to the UI. Cleanest approach: pass a `notice_callback` into `install()`
  in `_installGovernedMcpBoundary` that streams formatted notice lines into the active SSE/chat
  stream for the current turn. (If threading a callback through the request context is too invasive
  for this slice, DECISION POINT — propose the approach to team-lead before building.)
- At minimum: A2/A3/A4/A5/A7/A8/A9 Deny/Escalate outcomes must show as notices. A1/A6 "Allowed" on
  every call may be noisy — default to showing only non-Allow outcomes for action controls, with a
  verbose toggle to show all. Content controls show all non-skipped.

### D4 — Review (reviewer)
- Format correctness vs spec, no PII in the notice (B2 shows entity TYPES only, never the raw value),
  no regression to Group A/B, notices are clearly attributable and not confused with model output.

## Constraints
- Notices are presentation only — they MUST NOT change any governance decision or the audit.
- B2 notice shows entity TYPES only (EMAIL_ADDRESS, PHONE_NUMBER), never the raw PII.
- Respect enforce/observe: observe → "Escalated" wording may be "Flagged" (would-escalate); confirm
  with team-lead. Default: would-escalate → "Escalated (observe)".
- Governance env stays in .env.governance.

## Definition of done
- Package 0.12.0 with `format_control_notice` + optional notice_callback, tests green.
- Expense shows standardized notices for content controls (B1–B6) and action controls (A1–A12)
  in the chat UI, format exactly per spec, no raw PII, no decision/audit change.
- Demo: sending a PII message shows `Governance control B2 — PII redaction. Redacted (...)`;
  an injection shows `Governance control B1 — Prompt injection. Escalated ...`; a denied tool shows
  `Governance control A5 — Tool allowlist. Blocked`.

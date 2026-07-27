# Changelog

## Versioning policy

- Increment the MINOR version after every completed slice.
- Increment the MAJOR version after every completed group, resetting MINOR to 0.

## Versions

- **0.12.2** — Phase 4 B4: extract LLM-as-judge into async `judge()` method on ContentHookRuntime (runs OUT of sync latency path); allow app to inject a pre-built LlmJudge via `install_content_hooks(llm_judge=...)`; remove inline B4 from `post_model_check` (avoids double-run); B4 emits audit entries (PII-safe, unified sink) and returns critique; observe/escalate-only (never blocks); B5 graceful-failure on judge exceptions. 12+ unit tests.
- **0.12.1** — Fix notice emission filter: only emit for ACTIONABLE results (transformed, escalated, denied, grounding-failed, concerns-found), suppress clean passes (allowed, grounded, no-concerns). Prevents UI spam from benign "Allowed" notices on every turn. Added 15 unit tests verifying clean passes emit ZERO notices.
- **0.12.0** — Slice B-INT-2 D1 (Governance UI notices: canonical notice formatter `format_control_notice()` with A1-A12 + B1-B6 safeguard labels and action verbs, injected `notice_callback` on both `install()` and `install_content_hooks()`, dependency-injection pattern with NO app imports, filtering rules: A6 never, A1-A12 Deny/Escalate only, B1-B6 all non-skipped, 50+ unit tests)
- **0.11.0** — Slice B-INT-1 (content governance composition root `install_content_hooks()` with graceful degradation for heavy deps, unified action+content audit sink, export from package __init__, unit tests for adapter wiring and audit unification)
- **0.10.0** — Slice B3 (three-tier material explanations B6, ExplanationGenerator with quality gates, ExplanationRouter, GROUP B COMPLETE: B1-B6 all functional)
- **0.9.0** — Slice B2 (grounded output validation B3, LLM-as-judge B4, graceful failure B5, post_model_check in ContentHookRuntime)
- **0.8.0** — Slice B1 (input attack detection B1 via DeBERTa stub, PII input minimization B2 via Presidio stub, ContentHookRuntime pre_model_check)
- **0.7.0** — Slice B0 (content governance envelope, ContentDisposition Allow/Transform/Escalate/Block, contentControls policy extension, content audit builder)
- **0.6.1** — Audit payloads use canonical opaque references; EscalationHandle preserves all ordered reasons
- **0.6.0** — Slice 5 (trusted-server and typed input hardening + structured governance escalation handoff)
- **0.5.0** — Slice 4 (configurable exposure, rate, and receipt-evidence disposition controls)
- **0.4.0** — Slice 3 (unified configurable policy table + envelope integrity + independently staged control modes)
- **0.3.1** — Added environment-driven mandate-revocation and forced-identity demo toggles
- **0.3.0** — Slice 2 (verified agent identities + machine-readable per-identity mandates)
- **0.2.2** — Audit `policyVersion` now reports the package version (removed internal slice labels from runtime data)
- **0.2.1** — Audit sink writes a new timestamped file per run (`audit-<UTC>.jsonl`)
- **0.2.0** — Slice 1 (least-privilege deny-unknown-tool allowlist + Deny path + demo trigger)
- **0.1.0** — Slice 0 (walking skeleton: envelope + disposition + JSONL audit + fail-closed floor)

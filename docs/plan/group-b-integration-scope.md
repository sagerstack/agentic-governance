# Group B Integration Scope — Slice B-INT-1

**Objective:** Wire Group B content governance (B1–B6) into the Expense AI app so that
**model I/O** is governed in the live application, mirroring how Group A governs **tool calls**.
Prove it with ONE end-to-end test.

## Current state (verified)
- Governance package `v0.10.0`: Group A (A1–A12) + Group B (B1–B6) code-complete, 200 tests pass.
- Group A IS integrated in Expense via `_installGovernedMcpBoundary()` in
  `src/agentic_claims/core/graph.py` → calls package `install()` → monkeypatches `mcpCallTool`.
- Group B is NOT integrated: `ContentHookRuntime` exists
  (`agentic_governance/integrations/langgraph_mcp/content_hooks.py`) but nothing in Expense calls it.
- **Gap:** the package exposes `install()` for Group A but NO composition root for Group B.
- B control modes already in policy: `AGENTIC_GOV_ENABLE_B1..B6`
  (defaults: B1 observe, B2 enforce, B3 enforce, B4 observe, B5 enforce, B6 enforce).
- Expense model calls funnel through `agents/shared/llmFactory.py::buildAgentLlm` (agent nodes)
  plus intake-gpt paths in `agents/intake_gpt/` and `web/sseHelpers.py`.

## Deliverables

### D1 — Package: content-hook composition root (governance-builder, agentic-governance repo)
- Add `install_content_hooks(...) -> ContentHookRuntime` (name TBD by planner), mirroring `install()`.
  - Inputs: loaded policy, shared audit sink (SAME sink object Group A uses so action + content
    audit share one correlation trail), env for modes.
  - Wires available adapters: InputAttackDetector (B1), PiiMinimizer (B2), GroundingValidator (B3),
    LlmJudge (B4), GracefulFailureHandler (B5), ExplanationGenerator (B6).
  - **Graceful degradation is mandatory:** if an adapter's heavy dependency is not installed
    (e.g. DeBERTa model for B1, Presidio for B2), that adapter is passed as `None` → the control
    is skipped and AUDITED as skipped. The app must NEVER crash or fail-open because a dep is missing.
- Export from package `__init__`.
- Unit tests for the composition root (adapter present vs absent; mode wiring).
- Version bump: minor → `0.11.0`. Update CHANGELOG.

### D2 — Expense: content boundary wiring (integrator, agentic-expense-claims repo, branch feature/agentic-guardrails)
- Add a content-governance composition root mirroring `_installGovernedMcpBoundary()`; build the
  `ContentHookRuntime` ONCE at graph construction, sharing the SAME JSONL audit sink as Group A.
- Invoke at the intake-gpt model boundary (primary POC target):
  - `pre_model_check(content, content_type, correlation_id, agent_identity, context)` on the inbound
    user/content BEFORE the model call; the caller MUST use `result.content` for the model call.
  - `post_model_check(content, content_type, correlation_id, agent_identity, context,
    trusted_state, rag_clauses, required_evidence_fields)` on the model output.
- `correlation_id` = existing claim/correlation id; `agent_identity` = "intake".
- For B3 grounding, pass `trusted_state` = the trusted extracted receipt already available from the
  A9 work (`extractionContext.py` / `extractedReceiptVar`). This is a deliberate synergy.
- Respect enforce|observe|off via B modes. Governance env stays in `.env.governance`.
- Do NOT break Group A (200 package tests + live A1–A5 must still pass).

### D3 — Plan + e2e scenario (planner)
- Produce the implementation plan sequencing D1 then D2.
- Choose ONE deterministic e2e scenario that does NOT depend on heavy ML deps if they are not
  installed in the container. RECOMMENDED candidates (pick one, justify):
  - B3 grounded-output validation: model output asserts a fact inconsistent with the trusted
    receipt → `grounding-failed` → Escalate, visible in the unified audit.
  - B6 material explanation: any governed content decision emits the three-tier explanation.
- Define the exact oracle: a specific line in the unified governance audit JSONL.

### D4 — Review (reviewer)
- Verify: composition-root correctness, graceful degradation (no fail-open on missing deps),
  audit unification (one sink, shared correlation), no PII leakage in audit, config discipline
  (enforce|observe|off; audit not disableable), Group A regression (tests green), test coverage.

## Constraints
- Content audit uses the SAME sink as action audit (unified correlationId).
- POC exclusions: raw receipt-image PII redaction, email output enforcement.
- All governance env in `.env.governance` (not `.env.local`).
- Minor version for the slice; patch for fixes.

## Definition of done
- Package `0.11.0` with composition root + tests green.
- Expense on `feature/agentic-guardrails` invokes pre/post model checks at the intake-gpt boundary,
  content audit lands in the unified JSONL sink, Group A still green.
- ONE e2e test executed by the qa-team proving a content control fires in the live app,
  verified against the audit JSONL.

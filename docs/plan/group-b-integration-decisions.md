# Group B Integration — Consolidated Decisions & Status

Single source of truth for the Group B (content governance, B1–B6) integration into the Expense app.
All items below are confirmed by the human lead.

## Status by control
- **B1 (prompt injection, DeBERTa)** — DONE. All 5 agents (intake, compliance, fraud, advisor, OCR). enforce on intake.
- **B2 (PII, Presidio)** — DONE. All 5 agents, input + output. Image-PII and SG-bare-8-digit-phone DEFERRED/dropped.
- **B3 (grounded output, deterministic)** — NOT INTEGRATED. Next up (decision agents first).
- **B4 (LLM-as-judge)** — package exists but INERT (no client). To wire (async/end-of-turn — see below).
- **B5 (graceful failure)** — in runtime; verify in-app.
- **B6 (three-tier explanations)** — package exists; verify surfaced.

## Coverage model
- 5 LLM surfaces: intake-gpt, compliance, fraud, advisor, extractReceiptFields(OCR).
- Dual ContentHookRuntime: intake runtime (chat notices) + background runtime (notice_callback=None → audit + findings embed, NO chat). Shared audit sink (unified log).
- create_react_agent / bind_tools / with_structured_output BYPASS the ChatOpenRouter wrapper → those agents (advisor) governed at the NODE boundary via explicit pre/post checks. Direct llm.ainvoke (compliance/fraud) governed by the wrapper.
- Graph-module globals (contentHookRuntime*) must be LAZY-imported inside functions (top-level import → circular import crash).

## Surfacing model
- Interactive intake-gpt: live single-channel small-red notice `Governance control {ID} — {safeguard}. {Action}` (GOVERNANCE_PERSISTENT), freezes into transcript. Enforcement stops the turn.
- Background agents (compliance/fraud/advisor): governance → AUDIT LOG + embedded in each agent's own *Findings.governance (PII-safe: ids/results/types only). NO chat notice. Feeds future Group D dashboard.
- Audit entries dashboard-ready: controlId, agentIdentity, decision, reasons, result, ts, correlationId, claimId, policyVersion, PII-safe refs.

## B4 decision (confirmed)
- B4 must SHOW in the UI when it flags (not audit-only).
- INTAKE: B4 runs END-OF-TURN — reply streams first, then B4 (~1–2s, gpt-4o-mini); on concern → small-red notice `Governance control B4 — LLM judge. Flagged`, freezes into transcript, then turn closes. Answer text not delayed.
- BACKGROUND agents: B4 async → audit + review view + Group D dashboard (no chat).
- Observe/escalate-only everywhere; never a sole blocker.

## Guardrails AI decision (confirmed)
- DEFERRED. Decision agents' B3 uses existing structured JSONB findings — no Guardrails needed.
- Guardrails is only for structuring intake's free-text prose (lowest-priority B3). If adopted later, it goes in the PACKAGE as an optional [content] extra, with our deterministic GroundingValidator exposed as a Guardrails custom validator; the domain ClaimAssertion schema + where-to-apply stays app-side.

## Remaining order
1. B3 on decision agents (advisor → compliance → fraud), deterministic, using existing findings + trusted state. No Guardrails.
2. B4 async/end-of-turn (client wiring + UI notice per above).
3. Verify B5 + B6 in-app.
4. Guardrails + intake-prose B3 — optional, only if wanted.
5. Group B acceptance suite (~10–14 outcome-oriented cases) — TBD.

## Branch policy
- governance package work: feature/group-b-agent-coverage. Expense: feature/agentic-guardrails. NEVER push to main; merges gated by team-lead after review.

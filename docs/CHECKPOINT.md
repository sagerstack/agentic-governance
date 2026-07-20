# Checkpoint — Group A POC, Slice 0 (resume point)

**Date:** 2026-07-20
**Where we are:** Building the app-agnostic runtime governance layer. Group A POC. **Slice 0 (walking skeleton) is BUILT + REVIEWED; integration wiring into the Expense app is IN PROGRESS.** Slices 1–5 not started.

---

## Program context (one paragraph)
We are building `agentic-governance` — an app-agnostic runtime governance control plane — whose first integration target is the LangGraph expense-claims app (`../agentic-expense-claims`). Research + plan + gap analysis are complete under `docs/research/` and `docs/plan/group-a-poc-plan.md`. The Group A POC is 6 thin vertical slices (0→5). All 3 open decisions are RESOLVED: (i) in-process wrapper primary, (ii) pure-Python PDP now / OPA as later drop-in, (iii) minimal composition-root DI edit in the app is APPROVED.

## Key artifacts
- Research report: `docs/research/governance-layer-research.md`
- Gap assessment: `docs/research/gap-assessment.md`
- App integration profile: `docs/research/APP-INTEGRATION-PROFILE.md`
- Build plan (authoritative): `docs/plan/group-a-poc-plan.md`
- Slides: `docs/slides/agentic-governance-deck.pptx` (+ `build_deck.py`)

---

## STATE — Governance repo (`agentic-governance`)
**Slice 0 = DONE, reviewer verdict PASS, Level-1 tests: 3 passed.**

Package `src/agentic_governance/` (installable, setuptools, src layout):
- `core/` — `envelope.py`, `disposition.py` (Deny/Escalate/Auto-Execute/Observe), `engine.py` (Observe/Auto for all in Slice 0)
- `ports/` — `audit_sink`, `counter_store`, `evidence_evaluator`, `identity_registry`, `mandate_store`, `policy_decision_point`
- `adapters/` — `jsonl_audit.py`, `pdp_python.py`, `inmemory_registry.py`, `inmemory_counters.py`
- `integrations/langgraph_mcp/` — `governed_mcp_call.py` (async `governedMcpCallTool(serverUrl, toolName, arguments)`), `call_context.py`
- `tests/test_slice0.py`

**Behavior:** Observe-only (pass-through + audit) + fail-closed floor for high-impact db wire actions `insertClaim`/`updateClaimStatus` (email excluded). Emits Envelope/Disposition/AuditEntry JSONL with correlationId, redacted/hashed params, `prevEntryHash` placeholder.

**Install command:** `pip install -e ../agentic-governance` (Poetry: `agentic-governance = { path = "../agentic-governance", develop = true }`)

**DI entrypoint** (`from agentic_governance.integrations.langgraph_mcp import install`):
```python
install(*, real_mcp_call_tool, employee_id_provider, extracted_receipt_provider,
        session_claim_id_provider, node_identity_provider,
        engine=None, audit_sink=None, identity_registry=None, mandate_store=None)
    -> governedMcpCallTool   # async (serverUrl, toolName, arguments)
```

**Reviewer's 4 LOW-severity polish notes (address when Slice 1 lands, not blockers):**
1. Happy-path audit currently fires AFTER awaiting the real tool; plan §1.2 step 5 wants it before — tighten when Deny/Escalate land.
2. Fail-closed test covers only `insertClaim`; add `updateClaimStatus` + "non-high-impact stays Observe under fail-closed".
3. Fail-closed floor tagged control A12 (acceptable; it's the structural floor).
4. Global `_RUNTIME` singleton + default audit path `./.agentic_governance/audit.jsonl` — fine for POC.

---

## STATE — Expense repo (`agentic-expense-claims`)
**Branch `feature/agentic-guardrails`. Integration wiring IN PROGRESS (committed at this checkpoint).**

Two files changed (HARD SCOPE — only these two may change):
- `pyproject.toml` — added the `agentic-governance` path dependency (+1 line)
- `src/agentic_claims/core/graph.py` — composition-root DI (~+81/-17): defines `nodeIdentityVar`, builds providers from existing contextvars (`employeeIdVar`, `extractedReceiptVar`, `sessionClaimIdVar`), calls `install(...)`, rebinds the 15 bound `mcpCallTool` importers to the governed callable, sets `nodeIdentityVar` at node entry.

**Evidence it works:** `.agentic_governance/audit.jsonl` produced with 13 entries → the governed wrapper is installed and emitting audit events at the tool boundary.

**Outstanding for the integrator (NOT yet complete):**
- **Level-3 regression** — the full `pytest tests/ -q` HANGS in this env (suite includes e2e/live tests needing MCP/Postgres/browser). Must be run as the **hermetic/unit subset only, wrapped in a shell `timeout`, deselecting e2e/browser/live** → confirm Observe-only leaves behavior unchanged. NOT yet confirmed green.
- **Level-2 live e2e** — DEFERRED (needs the 8-service docker stack: `./scripts/startup.sh`). Not runnable in the current environment.

---

## HOW TO RESUME

### 1. Re-create the team
`create_predefined_team` template `sg-1` as **`team_name: sg-1-agentic-governance`**, cwd `/Users/sagarpratapsingh/dev/sagerstack/agentic-governance`. Then immediately shut down the idle specialists you don't need (keep coordinator; spawn builders/reviewer on demand). OR just spawn the 3 needed agents directly.

### 2. Resume `integrator` (finish Slice 0 integration)  — DO THIS FIRST
- `spawn_teammate` name `integrator`, cwd `/Users/sagarpratapsingh/dev/sagerstack/agentic-expense-claims`, **model `openai-codex/gpt-5.6-sol`** (IMPORTANT: NOT `openai/...` — that hits "No API key found for openai"; the working subscription provider is `openai-codex`).
- Task: on branch `feature/agentic-guardrails`, run the **hermetic Level-3 regression** (`timeout 300 poetry run pytest tests/ -q -k "not e2e and not browser and not live and not vnd"` — adjust deselect markers as needed), confirm all pass / behavior unchanged, report counts. Keep the 2-file scope. Level-2 live e2e = report commands, don't start the stack. STOP+report on any regression or third-file need.

### 3. Resume `governance-builder` (start Slice 1)
- `spawn_teammate` name `governance-builder`, cwd `/Users/sagarpratapsingh/dev/sagerstack/agentic-governance`, model `openai/gpt-5.6-sol` (worked fine).
- Task: build **Slice 1 — least-privilege deny-unknown-tool** per `docs/plan/group-a-poc-plan.md` (allowlist keyed on `(serverUrl, wire-toolName)`, deny-by-default, full Deny disposition path). Also fold in reviewer LOW notes #1 and #2 (audit-before-await; broaden fail-closed test). Level-1 hermetic tests. Report to coordinator.

### 4. Review gate
- Spawn `reviewer` (model `anthropic/claude-opus-4-8`, cwd governance repo) per slice to verify before integration; re-run the integrator's Level-3 after each slice touching behavior.

### Naming/token discipline
- Team name MUST be `sg-1-agentic-governance` (project rule: `<template>-<cwd-basename>`).
- Shut down idle agents promptly (they idle-poll and burn tokens). Only coordinator + the active builder/integrator + reviewer-on-demand need to be alive.

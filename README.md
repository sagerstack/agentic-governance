# agentic-governance

**An app-agnostic runtime governance control plane for agentic AI applications.**

`agentic-governance` sits between an AI agent and the tools it can act with, and turns
every tool action into a governed decision: it builds a **governance envelope** from
trusted state, evaluates it against deterministic policy, and returns one of
**Deny / Escalate / Auto-Execute / Observe** — recording a tamper-aware, PII-safe audit
entry for each one. The agent's action executes only if governance allows it.

It is a standalone Python package with **no dependency on any specific application**; an
app integrates by wiring one seam (its tool-call boundary) to the governed wrapper.

---

## Objective

Agentic apps let an LLM take real-world actions (write to a database, submit a claim,
send an email). Without a control point, a buggy or **prompt-injection-hijacked** agent
can take actions it was never meant to, with no record and nothing to stop it.

`agentic-governance` provides that control point:

- **See and record** every action an agent takes (private-by-default audit).
- **Authorize or block** each action deterministically, at the tool boundary — not via
  prompts (which an agent can ignore).
- **Fail closed** — if governance is unavailable, high-impact actions are denied, not
  silently allowed.
- **Stay reusable** — the decision core is app-agnostic; onboarding a new agentic app is a
  thin adapter plus one integration edit.

There is deliberately **no LLM in the decision loop** — decisions are deterministic code
checks against forge-proof trusted state, so they are testable, auditable, and not
themselves susceptible to prompt injection.

---

## Standards we align to

The control catalogue is grounded in two Singapore governance standards (both advisory /
non-binding — we treat them as engineering best practice, not legal mandate):

- **IMDA Model AI Governance Framework** — the voluntary model frameworks (2020, the 2024
  Generative AI edition, and the 2026 Agentic AI edition): verifiable agent identity,
  least-privilege enforced at the tool layer, "MCP as a governance layer", input/output
  filtering, human oversight, and monitoring.
- **MAS "Safeguards for Agentic Finance at Runtime" (SAFR)** — the runtime spine: a
  four-component checkpoint (Agent Identity → Controls → Disposition Engine → Audit Log)
  that packages each action into a **Governance Envelope** and resolves it to
  Deny / Escalate / Auto-Execute / Observe. Supplemented by MAS **FEAT** / Veritas.

See `docs/research/governance-layer-research.md` for the full cited control catalogue and
`docs/research/gap-assessment.md` for a reference gap analysis.

---

## Controls we are implementing

Controls are organised into four groups (the defence-in-depth control plane). **Group A is
the current focus; B/C/D are on the roadmap.**

| Group | What it defends | Attach point |
|-------|-----------------|--------------|
| **A — Action-time authorization** *(current)* | Gate every tool action before it executes | tool boundary (`mcpCallTool`) |
| **B — Model input/output guardrails** | Screen LLM/VLM input & output (injection, PII, grounding) | model hooks |
| **C — Human oversight & failsafes** | Risk-calibrated escalation, timeouts, recourse | escalation node |
| **D — Audit, monitoring & incident** | Immutable tamper-evident log, monitoring→intervention | audit sink |

**Group A controls (12):** pre-execution governance envelope, envelope integrity /
authenticate-against-origin, verified agent identity, machine-readable mandate,
least-privilege at the tool layer, deterministic per-action disposition, exposure limits,
rate limits, evidence-quality threshold, tool/protocol input hardening, layered-defense
assertion, and the gateway/hybrid deployment pattern.

### Implemented so far
- **Slice 0 — walking skeleton:** async governed wrapper + governance envelope (A1) +
  deterministic disposition scaffold (A6) + gateway pattern (A12) + JSONL audit sink +
  **fail-closed floor** for high-impact actions. Observe-only.
- **Slice 1 — least-privilege deny-unknown-tool (A5):** deny-by-default allowlist keyed on
  `(serverUrl, wire-toolName)`; real **Deny** path (`tool-not-allowed`).
- **Slice 2 — verified identity + mandate (A3/A4):** seven trusted service identities
  receive exact per-identity MCP capabilities; missing/unknown identities and
  out-of-mandate calls are denied before dispatch.
- **Slice 3 — envelope integrity (A2):** config-defined comparisons bind draft/final
  submissions to trusted employee identity and status updates to the trusted database
  claim id. Missing/mismatched required facts are denied before dispatch.
- **Slice 4 — quantitative dispositions (A7/A8/A9):** final intake submissions are
  governed by per-action/aggregate SGD exposure, atomic employee/session attempt rates,
  and required receipt evidence/confidence. Breaches deterministically Deny or Escalate.
- **Slice 5 — input hardening + handoff (A10/A11):** exact trusted-server validation and
  strict per-wire-tool argument schemas run before A5; Escalate returns a stable
  governance-sourced handoff marker; structural tests assert action-auth independence.

All six Group-A slices are implemented at v0.6.1 pending final verification. See
`docs/plan/group-a-poc-plan.md`.

---

## Architecture

```
Host agentic app  ──▶  governedMcpCallTool(serverUrl, toolName, arguments)   ◀── this package
  (sets trusted state,        │  1. build envelope from TRUSTED state (not agent text)
   one DI edit)               │  2. verify identity / mandate      (ports + adapters)
                              │  3. deterministic disposition      (pure-Python PDP)
                              │  4. audit (PII-safe, before execute)
                              ├─ Auto-Execute / Observe ─▶ real tool
                              ├─ Deny ──────────────────▶ blocked (real tool never runs)
                              └─ Escalate ──────────────▶ human oversight
```

Package layout (`src/agentic_governance/`):

- `core/` — **app-agnostic**: `envelope`, `disposition` (Deny/Escalate/Auto-Execute/Observe), `engine`
- `ports/` — abstract interfaces: identity registry, mandate store, policy-decision-point, counters, evidence evaluator, audit sink
- `adapters/` — pluggable implementations: pure-Python PDP, JSONL audit sink, in-memory registry/counters, tool allowlist
- `integrations/langgraph_mcp/` — the app-facing glue: `governedMcpCallTool` wrapper + `install()`

`core/` and `ports/` import nothing application-specific. All app knowledge lives in an
injected adapter — see integration below.

---

## Integrating with another agentic application

The layer is designed to front **any** agentic app that has a single tool-call boundary.
Integration is **inject-not-import**: this package never imports the app; the app passes it
the real tool function and callables that read its trusted state.

### The contract

```python
from agentic_governance.integrations.langgraph_mcp import install

governed_call = install(
    real_mcp_call_tool = your_real_tool_fn,        # async (serverUrl, toolName, arguments) -> result
    employee_id_provider       = lambda: ...,      # trusted principal (e.g. from the authenticated session)
    extracted_receipt_provider = lambda: ...,      # trusted extracted/domain state (optional)
    session_claim_id_provider  = lambda: ...,      # trusted session/correlation id
    node_identity_provider     = lambda: ...,      # which agent/node is acting
    db_claim_id_provider       = lambda: ...,      # optional trusted DB id; defaults to None
    # engine / audit_sink / identity_registry / mandate_store are optional overrides
)
# returns: async governedMcpCallTool(serverUrl, toolName, arguments)
```

The providers supply **trusted context** — data the agent cannot forge because it is set
upstream (session, framework state), never from the agent's own tool arguments. Internally
the exact trusted keys are `employeeId`, `extractedReceipt`, `sessionClaimId`, and
`dbClaimId`; current A2 rules read `employeeId` and `dbClaimId`. The governance decision
is made from raw in-memory context; only redacted/hash references enter audit. The agent's
arguments are treated as untrusted claims to be verified.

### Onboarding steps

1. **Write a thin adapter** that maps your app's ambient/trusted state to the provider
   callables above (identity, principal, correlation id, domain state).
2. **Make one composition-root edit** in your app to call `install(...)` and route your
   tool calls through the returned `governed_call` (e.g. rebind your existing tool
   function to the governed one).

That's it — the decision **core and policy engine are unchanged** across apps. The only
per-app code is the small adapter in step 1.

### Reference integration

The first integration target is a LangGraph multi-agent expense-claims app. See
`docs/plan/group-a-poc-plan.md` (integration contract) and `docs/DEMO-DOCKER.md` (running
it in Docker).

---

## Runtime configuration

- **Unified policy table** — the bundled schema-v1 policy is
  `src/agentic_governance/policy/default_policy.json`. It defines symbolic servers,
  trusted servers, strict tool schemas, global allowlist, verified identities, mandates,
  integrity/quantitative rules, and control metadata.
  Server symbols resolve through `RAG_MCP_URL`, `DB_MCP_URL`, and `CURRENCY_MCP_URL`.
  Replace the complete policy without code changes using
  `AGENTIC_GOV_POLICY_FILE=/path/to/policy.json`; invalid/incomplete policy fails startup
  closed.
- **Verified identities** — the integration must supply one of `intake`, `compliance`,
  `fraud`, `advisor`, `humanEscalation`, `markAiReviewed`, or `application`. Web/UI/SSE
  calls outside graph nodes must use `application`; null or unknown identities are
  denied as `unverified-identity`.
- **Independent control modes** — each defaults to `enforce`. Values are
  case-insensitive: `true|1|on|enforce` → enforce, `observe` → shadow evaluation without
  blocking, and `false|0|off` → skip. Invalid values warning-log and safely default to
  enforce. Audit `controlStates` records `{controlId, mode, outcome}` independently of
  backward-compatible `firedControls`.
  ```bash
  AGENTIC_GOV_ENABLE_ALLOWLIST=enforce    # A5
  AGENTIC_GOV_ENABLE_IDENTITY=enforce     # A3
  AGENTIC_GOV_ENABLE_MANDATE=enforce      # A4
  AGENTIC_GOV_ENABLE_INTEGRITY=observe    # A2; use shadow mode for first deployment
  AGENTIC_GOV_ENABLE_EXPOSURE=enforce     # A7
  AGENTIC_GOV_ENABLE_RATE=enforce         # A8
  AGENTIC_GOV_ENABLE_EVIDENCE=enforce     # A9
  AGENTIC_GOV_ENABLE_SCHEMA=enforce       # A10 trusted server + typed arguments
  AGENTIC_GOV_ENABLE_FAIL_CLOSED=enforce  # A12
  ```
  **Warning:** setting `AGENTIC_GOV_ENABLE_FAIL_CLOSED=off` removes the high-impact
  governance-unavailable safety net. The audit sink is always on and has no disable flag.
  Future controls follow `AGENTIC_GOV_ENABLE_<CONTROL>`.
- **Demo/testing toggles** — all are read once at governance runtime initialization
  and default to empty/off:
  ```bash
  # Subtract wire tools from the global A5 allowlist.
  AGENTIC_GOV_DENY_TOOLS="convertCurrency"

  # Subtract exact identity:wireTool capabilities from A4 mandates.
  AGENTIC_GOV_REVOKE_GRANTS="intake:searchPolicies,advisor:updateClaimStatus"

  # Override trusted identity for every governed call (demo/testing only).
  AGENTIC_GOV_FORCE_IDENTITY="fraud"       # or an unknown id such as "attacker"

  # Force configured A2 comparisons to report a mismatch.
  AGENTIC_GOV_SIMULATE_TAMPER="insertClaim:employeeId,updateClaimStatus:claimId"
  ```
  Revocation entries are comma-separated `identity:wireTool` pairs; surrounding
  whitespace is trimmed and malformed/unknown pairs are logged and skipped. A forced
  registered identity undergoes its normal mandate check, while a forced unknown
  identity is denied as `unverified-identity`. Tamper entries are comma-separated
  `wireTool:declaredField` pairs. When unset, trusted identity and integrity evaluation
  are unchanged.
- **Tunable Slice-4 defaults** — the bundled policy marks these POC values as
  placeholders: per-action escalation above **SGD 500**, hard Deny above **SGD 5,000**,
  aggregate escalation above **SGD 2,000 per employee/day**, and more than **5 final
  insertClaim attempts per employee or session/hour**. Final intake submission also
  requires receipt fields plus confidence ≥ **0.70** for merchant/date/total/currency.
  Application draft inserts are excluded. Override thresholds and breach dispositions
  with `AGENTIC_GOV_POLICY_FILE`. `Escalate` is audited and blocked from real tool
  execution. Reasons are `exposure-exceeded`, `rate-exceeded`, and
  `evidence-insufficient`.
- **A10 trusted input boundary** — `trustedServers` resolves the exact rag/db/currency
  endpoints; any other URL denies as `untrusted-server`. Every A5-allowlisted pair has a
  strict schema in `schemas`; malformed/missing/wrong-type/extra fields deny as
  `schema-invalid`. Unknown tools on trusted servers defer to A5 `tool-not-allowed`.
- **Escalation handoff contract** — governance returns:
  ```json
  {"error":"exposure-exceeded","decision":"Escalate","reason":"exposure-exceeded",
   "reasons":["exposure-exceeded","evidence-insufficient"],
   "escalation":{"source":"governance","reason":"exposure-exceeded"}}
  ```
  `reason` and nested `escalation.reason` remain the stable primary-reason contract;
  top-level `reasons` is the canonical ordered list of every disposition reason (primary
  first). The host app must route this marker to human review. It records governance
  escalation metadata as `source="governance"` plus the exact reason; its pre-existing
  validator/loop paths record `source="internal"` plus their internal reason.
- **Audit** — each run writes a new file `./.agentic_governance/audit-<UTC>-<hex>.jsonl`
  (previous runs preserved). Declared arguments persist only as
  `paramsRef: {"payloadSha256":"<canonical deterministic SHA-256>"}`; the raw field tree
  and scalar values are retained only in non-serialized memory for controls. Trusted
  receipt/provider content likewise persists only through opaque receipt/snapshot refs.
  A7/A9 audit diagnostics retain policy thresholds and coarse outcomes, not raw monetary
  amounts or confidence values; A8 action counts remain readable. Passing an explicit
  `.jsonl` path to `JsonlAuditSink` overrides the per-run file.
- **Explicitly deferred** — canonical corrected/FX facts, durable cross-process counters,
  cited-policy evidence, and tamper-evident audit storage remain unchanged and are not
  implemented by the v0.6.1 privacy/compatibility patch.

---

## Install & test

```bash
pip install -e .
pytest
```

## Versioning

Semantic-ish: **+minor per slice**, **+major per completed group**, patch for fixes.
Current: **0.6.1**. See `CHANGELOG.md`.

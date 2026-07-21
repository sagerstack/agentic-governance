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

Remaining Group A slices: agent identity + mandate (A3/A4), envelope integrity (A2),
exposure/rate/evidence knobs (A7/A8/A9), input hardening (A10). See
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
    # engine / audit_sink / identity_registry / mandate_store are optional overrides
)
# returns: async governedMcpCallTool(serverUrl, toolName, arguments)
```

The providers supply **trusted context** — data the agent cannot forge because it is set
upstream (session, framework state), never from the agent's own tool arguments. The
governance decision is made from this trusted context; the agent's arguments are recorded
but treated as untrusted claims to be verified.

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

- **Least-privilege allowlist** — governance-owned in
  `agentic_governance.adapters.tool_allowlist`; MCP server URLs are read from
  `RAG_MCP_URL`, `DB_MCP_URL`, `CURRENCY_MCP_URL` (with sensible defaults).
- **Demo deny toggle** — subtract normally-allowed tools without any app change:
  ```bash
  AGENTIC_GOV_DENY_TOOLS="convertCurrency"   # comma-separated wire tool names; empty by default
  ```
- **Audit** — each run writes a new file `./.agentic_governance/audit-<UTC>-<hex>.jsonl`
  (previous runs preserved). Sensitive values are stored as SHA-256 hashes; raw payloads
  never enter the log. Passing an explicit `.jsonl` path to `JsonlAuditSink` overrides the
  per-run file.

---

## Install & test

```bash
pip install -e .
pytest
```

## Versioning

Semantic-ish: **+minor per slice**, **+major per completed group**, patch for fixes.
Current: **0.2.1**. See `CHANGELOG.md`.

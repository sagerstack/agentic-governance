# Group A POC Build Plan — App-Agnostic Runtime Governance Layer

> **Status:** DRAFT for team-lead / plan-reviewer sign-off · **Author:** planner · **Date:** 2026-07-20
> **Scope:** Group A (action-time authorization & governance) controls **only**, as a small POC, built
> as an **independent, app-agnostic** governance layer in `/Users/sagarpratapsingh/dev/sagerstack/agentic-governance`,
> with its **first integration target** = the read-only LangGraph expense-claims app at
> `/Users/sagarpratapsingh/dev/sagerstack/agentic-expense-claims`.
> **This is a PLANNING artifact — no governance-layer code is written here. The Expense app is NOT modified.**

**Grounding:** Every design choice below cites the research corpus:
`docs/research/governance-layer-research.md` (§1 controls, §2 framework landscape, §3 reference architecture),
`docs/research/gap-assessment.md` (Group A table), `docs/research/APP-INTEGRATION-PROFILE.md` (integration seams),
and direct reads of the Expense app choke points.

---

## 0. Established facts this plan is built on (verified by direct code read)

| Fact | Evidence |
|---|---|
| Single client-side tool choke point routing **every** MCP call | `agentic-expense-claims/src/agentic_claims/agents/intake/utils/mcpClient.py:37` `mcpCallTool(serverUrl, toolName, arguments)` — pure pass-through logger, no authz (gap-assessment Group A) |
| `mcpCallTool` is imported at **15 modules** via **BOUND import** (`from ...mcpClient import mcpCallTool`), **not** qualified `mcpClient.mcpCallTool(...)` | grep of `import mcpCallTool` in `src/`: graph.py:16, web/routers/chat.py:14, advisor/{tools/searchPolicies,tools/updateClaimStatus,tools/sendNotification,node}, fraud/{tools/queryClaimsHistory,node}, compliance/node, intake/{tools/searchPolicies,tools/submitClaim,tools/getClaimSchema,tools/convertCurrency,nodes/humanEscalation,auditLogger} |
| **CRITICAL — bound imports break a naive boot monkeypatch:** patching `mcpClient.mcpCallTool` will NOT reach these 15 modules (each holds its own module-level bound name) | verified import style above; feeds R-2 / Decision (iii) |
| `async mcpCallTool(serverUrl, toolName, arguments) -> list \| dict` — the boundary is **async**; callers pass **no** call-context | `intake/utils/mcpClient.py:37`; the wrapper must match this exact async signature |
| Server URLs are **config-driven** → a network proxy can be inserted with no code change | `core/config.py:55-58` `rag_mcp_url / db_mcp_url / currency_mcp_url` (+ `email_mcp_url`, **OUT OF POC SCOPE** — email MCP not built/functional; not a governed server) |
| **Wire tool names ≠ app-action labels.** The wrapper sees the MCP **wire** name + `serverUrl`, never the LangChain `@tool` label | **In-scope high-impact wire actions = TWO (db only):** **`insertClaim`** (db; via `intake/tools/submitClaim.py:261` — the `submitClaim` @tool wraps it) and **`updateClaimStatus`** (db; `advisor/tools/updateClaimStatus.py:57` **and** `intake/nodes/humanEscalation.py:109`). Other in-scope wire names: `executeQuery`/`exactDuplicateCheck`/`recentClaimsByEmployee`/`claimsByMerchantAndEmployee` (fraud→db), `getPolicyByCategory`/`searchPolicies` (rag), `getClaimSchema`, `convertCurrency`, `insertAuditLog` (db, many callers). **`sendClaimNotification` (email) is OUT OF POC SCOPE** — email MCP not built. |
| **`serverUrl` alone cannot identify the calling agent** — multiple agents hit `db_mcp_url` (`insertClaim`+intake, `updateClaimStatus`+advisor/humanEscalation, `executeQuery`+fraud, `insertAuditLog`+all) | grep of `toolName=` + `serverUrl=` across `src/` |
| All 4 FastMCP servers use Streamable HTTP → network proxy is drop-in viable | `mcp_servers/db/server.py` `mcp.run(transport="streamable-http")` (+ research §3.4 RESOLVED) |
| Identity today = free-text actor strings; **no** verifiable identity flows to `mcpCallTool` | `advisor/tools/updateClaimStatus.py:57` `actor=f"advisor_agent:{decision}"`; gap-assessment Group A "agent identity = Absent" |
| **Ambient trusted state IS available in-process via contextvars** (no caller change needed) | `employeeIdVar` (`web/employeeIdContext.py:10`), `imagePathVar` (`web/imagePathContext.py:12`), `extractedReceiptVar` + `sessionClaimIdVar` (`intake/extractionContext.py:12-13`) — set upstream, readable by the wrapper |
| **NO per-node / agent-identity contextvar exists** — nothing ambient says "advisor is calling now" | only an OFFLINE `GRAPH_NODE_AGENT_MAP` / `_agentFromGraphNode()` in `web/sseHelpers.py:420-440` (SSE display), not a runtime contextvar; this gates R-1/R-3 identity derivation |
| Group A is **0% Present / 17% Partial / 83% Absent** | gap-assessment summary table |

---

## 1. Recommended POC architecture

### 1.1 Component shape (app-agnostic core + injected adapters)

Per research §3.1 (integration contract) and Profile §6 (nodes never import infra; adapters injected at the
composition root), the governance layer is **its own component in this repo**, split into a pure decision core
and pluggable adapters:

```
agentic-governance/  (THIS repo — the independent layer)
  core/                      pure, app-agnostic decision pipeline (no app imports)
    envelope.py              GovernanceEnvelope domain type (built from TRUSTED state)
    disposition.py           Disposition domain type {Deny|Escalate|Auto-Execute|Observe}
    engine.py                GovernanceEngine.evaluate(envelope) -> Disposition  (deterministic)
    controls/                one deterministic control-check per Group-A knob
  ports/                     abstract interfaces (the "contract")
    identity_registry.py     verify(agentId) -> AgentIdentity | reject
    mandate_store.py         mandateFor(identity) -> Mandate
    policy_decision_point.py evaluate(input) -> decision      (pure-Python engine NOW; OPA adapter drop-in LATER, Decision ii)
    counter_store.py         async-atomic exposure/rate counters (atomic-per-key)
    evidence_evaluator.py    confidence/evidence sufficiency
    audit_sink.py            append(envelope, disposition) -> durable event
  adapters/                  concrete implementations (injected)
    pdp_python.py            pure-Python deterministic PDP (POC; Decision ii). OPA REST/sidecar adapter = drop-in later (research §2.3)
    inmemory_registry.py     POC identity + mandate stores (JSON/YAML seed)
    inmemory_counters.py     POC atomic counters
    jsonl_audit.py           POC append-only JSONL audit sink (dashboard-ready events)
  integrations/langgraph_mcp/
    governed_mcp_call.py     the wrapper around the app's mcpCallTool boundary
    call_context.py          how trusted agent identity + graph-state snapshot are captured
```

### 1.2 The integration contract (what the app depends on)

The app integrates at **one seam** — the `mcpCallTool()` tool boundary. Because existing call sites pass **no**
call-context and **cannot be modified** (read-only app), the wrapper is a **drop-in async replacement with the
IDENTICAL signature** and derives everything it needs from **ambient in-process state**, not a new parameter:

```
async governedMcpCallTool(serverUrl, toolName, arguments) -> result | Denial | EscalationHandle
```

**R-1 — how the wrapper gets trusted identity + state without a `callContext` param:** it reads **ambient
contextvars** already set upstream (`employeeIdVar`, `imagePathVar`, `extractedReceiptVar`, `sessionClaimIdVar`)
plus the `(serverUrl, wire-toolName, arguments)` tuple it is handed. A `CallContext` object is **assembled
inside the wrapper** from these ambient sources — callers never construct or pass it.

**R-1 / R-3 — determining WHICH agent is calling (no node-identity contextvar exists):** resolved by
Decision (iii) = **mechanism (B), precise.** The approved minimal composition-root DI edit wraps each node
callable at graph construction in the app's `core/graph.py`, setting an authoritative **`nodeIdentityVar`** at
node entry that the wrapper reads. Because no node-identity contextvar exists today (§0), this DI wrap is what
creates it.
- **(A) coarse `(serverUrl, wire-toolName)`-derived identity = documented FALLBACK only, not the POC path.** It
  is unambiguous for the two in-scope high-impact actions (`insertClaim`→intake,
  `updateClaimStatus`→advisor/humanEscalation) but coarse for shared reads (`searchPolicies`); retained only as
  a degraded alternative if the DI edit were ever disallowed.
- **Rejected: call-stack/frame inference** — fragile across async tasks and refactors; explicitly NOT used.

Flow (SAFR-style checkpoint, research §1.2 / §3.1), **fully async**:
1. **Build GovernanceEnvelope from TRUSTED ambient state** (contextvars above + `(serverUrl, wire-toolName)` +
   derived caller identity) — **never from agent-authored text** (control 1).
2. **Verify agent identity** against the registry; reject+log unverified before any other check (control 3).
3. **Retrieve mandate/controls** for that identity (control 4).
4. **Deterministic (async) Disposition Engine** → exactly one of Deny / Escalate / Auto-Execute / Observe
   (control 6). PDP backend = the **pure-Python deterministic engine** (Decision (ii), resolved; OPA adapter
   drop-in later); covers least-privilege/schema (controls 5, 10) + custom checks for
   integrity/exposure/rate/evidence (2, 7, 8, 9).
5. **Emit to audit sink** (dashboard-ready structured event) BEFORE a high-impact side effect is acknowledged.
6. Dispatch: **Deny** → return denial, do NOT `await` the real `mcpCallTool`; **Escalate** → route to the app's
   existing `humanEscalation` path; **Auto-Execute / Observe** → `await` the real `mcpCallTool` and record.

**Agnostic guarantee:** `core/` and `ports/` import nothing from the app. Only `integrations/langgraph_mcp/`
knows about LangGraph/MCP/contextvars. A different agentic app integrates by writing its own thin
`CallContext` assembler (which ambient sources map to identity/state) + installing the wrapper; the core is
untouched.

### 1.3 Deployment pattern

= **Gateway / hybrid trusted wrapper** (research §1.2 control 12; §3.4). The POC's primary boundary is the
**in-process wrapper at `mcpCallTool()`** (the only place with trusted graph state to build/authenticate the
envelope). A **network proxy** (agentgateway) in front of the Streamable-HTTP servers is a viable
**later defence-in-depth** layer (identity/JWT, rate, schema at the wire), **deferred** per Decision (i,
resolved). This is Gateway/hybrid, **not** SAFR "Native" (the agents do not emit their own envelopes).

---

## 2. Thin vertical slices (ordered tracer bullets)

Each slice is **independently shippable** and **end-to-end demoable against the Expense app**. Each is a full
tracer through *build → integrate → test*. Slices are ordered so each builds on the prior; a reviewer may
re-order or split Slice 4.

> **e2e harness (shared across slices):** the governance wrapper runs in front of the app's **real**
> Streamable-HTTP MCP servers. A demo drives the relevant graph/tool path; assertions check (a) the
> **disposition**, (b) whether the **side effect actually happened** (DB row), and (c) that the
> expected **audit event** was emitted. A lighter, hermetic CI test **sets the ambient contextvars** (e.g.
> `employeeIdVar`, `extractedReceiptVar`) before calling `governedMcpCallTool` — the wrapper assembles its
> CallContext internally from those (R-1) — for deterministic control-unit coverage.

---

### Slice 0 — Walking skeleton: async wrapper + envelope + audit spine (Observe-only) + fail-closed floor
- **Scope / what it builds:** the **async** `core/engine.py` pipeline + `GovernanceEnvelope` + `Disposition`
  types, the **async** `governedMcpCallTool` (identical signature to the real boundary), and the `jsonl_audit`
  sink. Policy is trivial: every call → **Observe** (execute + record), nothing blocked yet. The envelope shell
  is assembled from **ambient contextvars** + `(serverUrl, wire-toolName)` (R-1), not a passed `callContext`.
- **How the app integrates:** wrapper installed via **composition-root dependency injection** in the app's
  `core/graph.py` (Decision iii, approved), so all 15 bound-import call sites resolve `governedMcpCallTool`
  (this avoids the R-2 bound-import problem and is fail-closed by construction). Async end-to-end (R-4).
- **Controls covered:** 12 (Gateway/hybrid wrapper), 1 (envelope, partial), 6 (disposition engine scaffold —
  Observe/Auto-Execute), + establishes the dashboard event model (§3).
- **e2e test / demo:** run one full claim end-to-end; assert **every** MCP tool call produced exactly one
  `envelope`+`disposition` audit event, and **no** call was blocked (behavior identical to today).
- **e2e fail-closed test (R-5):** with the governance infra deliberately unreachable (audit sink / PDP /
  registry down), a high-impact call (`insertClaim`) is **Denied fail-closed** — the real `mcpCallTool` is
  **not** awaited, no DB row is written, and a `Deny (governance-unavailable)` audit event is emitted once the
  sink recovers (research §3.2 P1: reject-on-unavailable + kill switch).
- **Threat / defense tier:** **Tier 0 (structural — defines "defended").** Retires the **fail-open bypass** that
  otherwise enables **T1** (fraudulent payout), **T2** (agent hijack), **T4** (action abuse): with no floor,
  every downstream control can be skipped.

### Slice 1 — Least-privilege deny-unknown-tool (headline tracer)
- **Scope / what it builds:** a static **allowlist keyed on `(serverUrl, wire-toolName)`** (R-3) +
  **deny-by-default**; full **Deny** disposition path with a fail-closed denial return (research §1.7 "deny
  unknown action/tool"; gap-assessment: fail-closed authorization = single highest-leverage gap).
- **How the app integrates:** unchanged wrapper; disposition returns Deny for any `(serverUrl, wire-toolName)`
  pair not on the allowlist. The allowlist enumerates the **real wire names** (`insertClaim`,
  `updateClaimStatus`, `searchPolicies`, `getPolicyByCategory`, `executeQuery`,
  `getClaimSchema`, `convertCurrency`, `insertAuditLog`, `exactDuplicateCheck`, `recentClaimsByEmployee`,
  `claimsByMerchantAndEmployee`) — not `@tool` labels. (`sendClaimNotification`/email is OUT OF POC SCOPE — not
  on the allowlist because the email MCP is not built.)
- **Controls covered:** 5 (least privilege, structural), 6 (Deny disposition), 1 (envelope consumed), 12.
- **e2e test / demo:** the brief's example — a call whose wire tool is the submission action (`insertClaim`,
  i.e. the `submitClaim` @tool's underlying wire call) with a **fabricated/unknown wire-toolName** routed
  through the wrapper is **denied fail-closed**; assert the DB row was **not** written and a **Deny** audit
  event (reason `tool-not-allowed`, carrying the `(serverUrl, wire-toolName)`) was emitted.
- **Threat / defense tier:** **Tier 0 — the SINGLE HIGHEST attack-defense value.** Fail-closed deny of
  unauthorized high-impact actions retires the **core of T1/T2/T4** (unauthorized submit / status-change; the
  email leg of T4 is deferred with the out-of-scope email MCP — see §Risk-priority ordering).

### Slice 2 — Verified agent identity + machine-readable mandate
- **Scope / what it builds:** `identity_registry` (Intake/Compliance/Fraud/Advisor get distinct service
  identities bound to role/dept) + `mandate_store` keyed so each identity's mandate is a set of allowed
  **`(serverUrl, wire-toolName)`** pairs + thresholds + validity window (R-3). Reject+log **unverified**
  identity before other checks. Least-privilege now enforced **per-agent** via mandate, not a global allowlist
  (research §1.2 controls 3, 4; deepens 5).
- **How the app integrates:** the wrapper derives the **trusted caller identity** from the **precise
  `nodeIdentityVar`** set by the composition-root DI wrap (Decision iii, approved; mechanism B). Identity is
  **never** trusted from the app's free-text `actor` string.
- **Controls covered:** 3 (identity), 4 (mandate), 5 (least privilege deepened).
- **e2e test / demo:** Advisor's identity attempting the submission wire call (`insertClaim`, outside its
  mandate) → **Deny (mandate)**; Intake's identity attempting `updateClaimStatus` → **Deny (mandate)**; an
  unknown/unverified identity → **Deny (unverified identity)** + logged. Each side effect confirmed **not** to
  have occurred. (With precise `nodeIdentityVar`, even shared reads like `searchPolicies` are attributed to the
  correct caller — the coarse-fallback limitation does not apply to the POC path.)
- **Threat / defense tier:** **Tier 1 (critical).** Identity + mandate retire **T2** (scope-enlargement: an
  agent invoking tools outside its mandate) and **T4** (an out-of-mandate agent driving abusive actions).

### Slice 3 — Envelope integrity / authenticate-against-origin
- **Scope / what it builds:** compare the agent-**declared** action/params against **trusted graph/tool state**;
  Deny on mismatch (research §1.2 control 2 — a sophisticated injection can fabricate action *and* trace
  consistently, so authenticate against origin).
- **How the app integrates:** wrapper cross-checks envelope params vs trusted context: e.g. `submitClaim`
  `employeeId` must equal server-side `employeeIdVar`; claimed `totalAmount`/currency must match the
  VLM-extracted `extractedReceiptVar` facts; `updateClaimStatus` target claim must be owned by the in-flight
  claim.
- **Controls covered:** 2 (envelope integrity / origin authentication).
- **e2e test / demo:** inject a tampered argument (submit for a **different** employee than `employeeIdVar`, or
  an amount that **contradicts** trusted extracted state) → **Deny (integrity/origin-mismatch)**; assert no DB
  write and a Deny audit event carrying both declared vs trusted values (redacted/hashed).
- **Threat / defense tier:** **Tier 1 (critical).** Envelope integrity retires **T2** (sophisticated injection
  that fabricates a consistent action+trace) and **T1** (tampered amounts / wrong-employee submission).

### Slice 4 — Quantitative disposition knobs: exposure + rate + evidence-quality
- **Scope / what it builds:** three **distinct** SAFR knobs (research §1.2 controls 7, 8, 9; SAFR Table 1) on
  `counter_store` (atomic) + `evidence_evaluator`:
  - **Exposure limits (7):** per-action + aggregate value thresholds on wire actions `insertClaim` /
    `updateClaimStatus` (amount/category/currency from trusted state) → below = Auto-Execute, above =
    Escalate/Deny.
  - **Rate limits (8):** max `insertClaim` per employee/session/window → burst →
    Deny/Escalate. (Demo target is `insertClaim`; the email demo is dropped as the email MCP is out of scope —
    the A8 control itself is unchanged.) **Counter atomicity (O-2):** Compliance ‖ Fraud run as **parallel async branches on one
    event loop**; counters must use an **async-safe atomic increment** (e.g. `asyncio.Lock`-guarded or a
    single-writer atomic store) so concurrent branch calls cannot race the window/aggregate — a POC in-memory
    store suffices but MUST be atomic-per-key.
  - **Evidence-quality threshold (9):** minimum VLM confidence + required cited policy evidence for autonomous
    execution; weak evidence → Escalate regardless of value. (Note: `vlm_confidence_threshold` exists but is
    **dead config** in the app — gap-assessment; the governance layer supplies the enforcing check.)
- **How the app integrates:** thresholds read trusted state (amount from envelope, confidence from
  `extractedReceipt`/`intakeFindings`, cited evidence from graph state).
- **Controls covered:** 7, 8, 9 (all three, each independently demoable — reviewer may split into 4a/4b/4c).
- **e2e test / demo:** three separate breaches — (a) an over-ceiling amount → **Escalate**; (b) N+1 submissions
  (rapid `insertClaim` submissions) in the window → **rate-limited Deny**; (c) a low-confidence extraction → **Escalate (evidence)** — each with
  its firing control + observed vs threshold values in the audit event.
- **Threat / defense tier:** **Tier 1–2.** Exposure limits (Tier 1) retire **T1** (large fraudulent payout);
  rate limits (Tier 2) retire **T4** (demonstrated via **mass-`insertClaim`** rate-limiting; the bulk-email leg
  of T4 is deferred with the out-of-scope email MCP); evidence-quality (Tier 2) retires **T1**
  (autonomous payout on weak evidence).

### Slice 5 — Input hardening, trusted-MCP allowlist & Escalate→human handoff (completes the layer)
- **Scope / what it builds:** (a) strict **typed schema** validation of MCP `arguments` **before** disposition +
  **trusted-MCP server allowlist** (only the **3 in-scope** registered `serverUrl`s: `rag_mcp_url`, `db_mcp_url`,
  `currency_mcp_url`; **`email_mcp_url` is explicitly OUT OF POC SCOPE** — email MCP not built — so it is **not**
  a governed/allowlisted server and any call to it would itself be denied as non-allowlisted) (research §1.2
  control 10, IMDA "MCP-as-governance-layer"); (b) wire the
  **Escalate** disposition into the app's existing `humanEscalation` node so Escalate has somewhere to go
  (without building the full Group-C timeout contract — later group); (c) **control 11 — architectural
  conformance assertion, NOT a behavioral demo (R-6):** in a Group-A-only POC there is **no model-guardrail
  (Group-B) layer to "layer" against**, so control 11's "layered" property cannot be behaviorally demonstrated.
  Instead it is discharged as a **static/architectural assertion** that the action-authz layer is a
  **standalone deterministic layer** (its own module, no dependency on model-hook state, exercised
  independently), leaving the interface where a Group-B layer would compose in front of it. Also confirm
  **all four** dispositions fire across a run (completes control 6).
- **How the app integrates:** schema validation at the wrapper; Escalate returns an `EscalationHandle` routed
  to `humanEscalation`; Auto-Execute/Observe `await` the real `mcpCallTool`.
- **Controls covered:** 10 (input hardening + allowlist), 11 (Group-A action-authz layer — architectural
  assertion only), completes 6 (4-way disposition), reinforces 12. (Network-proxy defence-in-depth for control
  12 is **deferred** — Decision (i), resolved: deferred.)
- **e2e test / demo:** (a) malformed `arguments` (wrong type / missing required field for e.g. `insertClaim`)
  → **Deny (schema)**; (b) a call to a **non-allowlisted** `serverUrl` (e.g. a fabricated rogue URL, or
  `email_mcp_url` which is out of scope) → **Deny (untrusted-server)**; (c) a
  full claim run exercising Deny + Escalate + Auto-Execute + Observe, with Escalate observably reaching
  `humanEscalation`. Control 11 is verified by a **structural/unit assertion** (layer runs standalone), not an
  e2e behavioral case.
- **Threat / defense tier:** **Tier 2 + supporting.** Schema hardening + trusted-MCP allowlist retire **T2**
  (malformed/injected args, calls to a rogue server) and **T3** (PII exfiltration via an untrusted MCP
  endpoint); A11/A12 are supporting (completes the 4-way disposition + gateway pattern).

### Risk-priority ordering (build order is risk-driven)

App threat model (Group-A subset): **T1** fraudulent payout · **T2** agent hijack via injection (e.g. malicious
receipt) · **T3** PII exfiltration · **T4** action abuse (mass-approve / mass-submit; **the bulk/phish-email leg
of T4 is PARTIALLY DEFERRED** — the email MCP is not built / out of POC scope, so the POC demonstrates T4 defense
via **mass-`insertClaim` rate-limiting** instead) · **T5** audit tamper.
Group-A defense tiers: **Tier 0** = the structural floor that defines "defended" (A6 disposition, A5 least
privilege, A1 envelope, + Slice-0 fail-closed floor); **Tier 1 (critical)** = A2 integrity, A3 identity, A4
mandate, A7 exposure; **Tier 2 (high)** = A8 rate, A10 input hardening, A9 evidence; **Supporting** = A11
layered-assertion, A12 gateway pattern.

The existing slice/dependency order already front-loads the highest-value fail-closed deny, so build order = the
risk order below.

| Slice | Defense tier | Threats retired | Note |
|---|---|---|---|
| **0** — skeleton + fail-closed floor | **Tier 0** (structural) | T1, T2, T4* (removes the fail-open bypass) | Without this floor every later control is skippable |
| **1** — least-privilege deny-unknown-tool | **Tier 0** — **highest single value** | T1, T2, T4* (core) | Fail-closed deny of unauthorized high-impact actions |
| **2** — identity + mandate | **Tier 1** (critical) | T2 (scope-enlargement), T4* | Per-agent authority via precise `nodeIdentityVar` |
| **3** — envelope integrity / origin auth | **Tier 1** (critical) | T2 (sophisticated injection), T1 (tampered amounts) | Authenticate declared vs trusted state |
| **4** — exposure + rate + evidence | **Tier 1–2** | T1 (exposure, evidence), T4* (rate, via mass-`insertClaim`) | Quantitative SAFR knobs |
| **5** — input hardening + allowlist + escalate handoff | **Tier 2 + supporting** | T2, T3 | Schema/allowlist; completes 4-way disposition (A11/A12 supporting) |

> **\*T4 (action abuse)** in the POC = **mass-submit / mass-approve** only; the **bulk/phish-email leg is
> deferred** with the out-of-scope email MCP. The A8 rate-limit control is unchanged — only its demo target
> shifts from `sendClaimNotification` to `insertClaim`.
> **T5 (audit tamper)** is deliberately **out of Group-A/POC scope** — tamper-evidence is Group-D (the audit
> model here only leaves a `prevEntryHash` placeholder, §3).

---

## 3. Dashboard-oriented event / data model (design now, build dashboard LATER)

Emit structured, append-only JSON events so a future dashboard can render envelopes, disposition breakdown
(allow/deny/escalate/observe), per-control fire rates, and an audit timeline. **No dashboard is built now.**

**`GovernanceEnvelope`** — `{ envelopeId, correlationId (claimId/threadId), ts, agentIdentity {id, role, dept,
boundHuman}, actionType, toolName, mcpServer, paramsRef (redacted/hashed, PII-safe), actionTrace [prior tool
calls/data/checks], contextMetadata {mandateId, graphStateSnapshotRef, policyVersion} }`

**`Disposition`** — `{ envelopeId, decision: Deny|Escalate|Auto-Execute|Observe, reasons[], firedControls[
{controlId (A1..A12), name, result, threshold?, observedValue?} ], policyVersion, latencyMs }`

**`AuditEntry`** (append-only, dashboard source of truth) — `{ entryId, envelopeId, correlationId,
agentIdentity, disposition, controlVersions, timings, prevEntryHash (placeholder for later hash-chain / D1
tamper-evidence), evidenceRefs (PII-safe pointers, never raw receipt payloads) }`

**`CounterState`** (exposure/rate) — `{ key (agent|employee|window), aggregateValue, actionCount, windowStart }`

Design notes: PII-safe (log hashes/refs + redacted metadata, never raw receipt/secrets — research §1.5, §3.1);
`prevEntryHash` is a **placeholder only** so a later Group-D tamper-evident root can chain these without a data
migration; correlation IDs stitch a full claim's envelopes for the dashboard timeline.

---

## 4. Per-control coverage mapping (all 12 Group-A controls)

> **Decision (ii) RESOLVED — PDP = pure-Python engine NOW; OPA adapter = drop-in LATER.** Cells marked **(PDP)**
> are satisfied by the **pure-Python deterministic evaluator** for the POC, behind the `policy_decision_point`
> port; an OPA sidecar can replace it later with no core change. Control coverage is identical either way —
> only the backend differs. (No longer contingent/undecided.)

| # | Group-A control | Slice(s) | OSS/reference (research §2) or CUSTOM |
|---|---|---|---|
| 1 | Pre-execution governance envelope (from trusted state) | 0 (shell), 1–5 (consumed) | **CUSTOM** (no OSS; §2.2) |
| 2 | Envelope integrity / authenticate-against-origin | 3 | **CUSTOM** (§2.2 — injection scanning cannot authenticate origin) |
| 3 | Verified, accountable agent identity | 2 | **CUSTOM registry** (agentgateway JWT = later network option, §2.1) |
| 4 | Machine-readable mandate / capability authority | 2 | **CUSTOM store**; Cedar/OPA can *encode* (reference, §2.1) |
| 5 | Least privilege, structural at tool layer | 1 (static), 2 (per-agent) | **(PDP)** pure-Python evaluator now; OPA drop-in later (§2.2) |
| 6 | Deterministic per-action disposition (4-way) | 0 (Observe/Auto), 1 (Deny), 4 (Escalate), 5 (completes) | **(PDP)** pure-Python returns structured disposition; OPA later (§2.2) |
| 7 | Exposure limits (per-action + aggregate) | 4 | **(PDP)** pure-Python evaluates + **CUSTOM** async-atomic counters (§2.2) |
| 8 | Rate limits | 4 | **CUSTOM** async-atomic counters (agentgateway rate = later, §2.1) |
| 9 | Evidence-quality threshold | 4 | **CUSTOM** (needs app-normalized facts, §2.2) |
| 10 | Tool/protocol input hardening (typed schema + trusted-MCP allowlist) | 5 | **(PDP)** pure-Python schema check + **CUSTOM** allowlist (NeMo IORails = ref, §2.2) |
| 11 | Layered model-guardrails + action-authz (Group-A half) | 5 | architecture-level; **CUSTOM** standalone deterministic layer (§2.2) |
| 12 | Deployment pattern = Gateway/hybrid trusted wrapper | 0 (in-process); network proxy deferred | agentgateway (conditional, §2.1/§3.4) |

Every Group-A control is covered by at least one slice; Slices 0→5 collectively close the 83%-Absent gap.
**(PDP)** cells run on the pure-Python engine for the POC (Decision ii, resolved), with an OPA adapter as a
later drop-in.

> **Email-MCP scope change — NO control dropped.** Excluding the email MCP (`sendClaimNotification` /
> `email_mcp_url`) removes it only as a **governed-tool target**; **all 12 Group-A controls remain fully
> covered.** Specifically **A8 (rate limits)** stays — its demo target moves from `sendClaimNotification` to
> `insertClaim`; **A10 (input hardening + trusted-MCP allowlist)** stays — the allowlist simply shrinks to the
> 3 in-scope servers (`rag`/`db`/`currency`); **A12 (gateway pattern)** stays unchanged. The **governed
> high-impact action set shrinks from 3 to 2** (`insertClaim`, `updateClaimStatus`) — no control is lost.

---

## 5. RESOLVED DECISIONS — SIGNED OFF BY THE HUMAN LEAD

> All three forks are **APPROVED and locked** (human lead, 2026-07-20). The slices above are written to these
> resolutions. Rationale retained for the record.

### (i) POC integration mechanism = **in-process wrapper at `mcpCallTool()` (PRIMARY); network proxy DEFERRED** — RESOLVED
- **Decision:** the POC integrates **in-process** at the `mcpCallTool()` boundary. The network proxy
  (agentgateway) is **deferred** as later defence-in-depth, not built now.
- **Rationale:** the envelope MUST be built from **trusted graph state** and integrity **authenticated against
  origin** (research §1.2 controls 1–2, §3.1). Only the in-process choke point sees the trusted context
  (`employeeIdVar`, `extractedReceiptVar`, node identity, graph state); a pure network proxy sees only the HTTP
  request and cannot build a state-derived envelope or authenticate origin. The proxy remains viable later
  (transport = Streamable HTTP, §3.4) for JWT/rate/schema at the wire.

### (ii) PDP = **pure-Python deterministic engine for the POC (leaner); OPA adapter as a drop-in for LATER** — RESOLVED
- **Decision:** build the disposition PDP as a **pure-Python deterministic engine** now (fewer moving parts,
  faster POC). **Keep the `policy_decision_point` port abstraction** so an **OPA (Rego) sidecar adapter is a
  drop-in replacement later** with no core change. Envelope construction, identity/mandate registry,
  async-atomic exposure/rate counters, and audit sink remain custom Python.
- **Rationale:** app is Python-first and OpenRouter-based (Profile §2, §6). OPA is the surveyed best-fit PDP
  (research §2.1/§2.3) but adds a process/container; the POC does not need it, and the port keeps the door open.

### (iii) App edit = **APPROVED: minimal composition-root DI edit in the Expense app** — RESOLVED
- **Decision:** a **truly minimal composition-root change is APPROVED (Option 2, DI).** At graph construction in
  the Expense app's `core/graph.py`, inject the governed call so **all callers resolve `governedMcpCallTool`**.
  The edit is confined to the composition root — no changes to the 15 importing call sites' logic. This is the
  clean, fail-closed-by-construction path (avoids the fragile per-module rebind and the graph-state-blind
  network proxy). It **also unlocks the PRECISE per-agent identity mechanism (B)** — a node-entry
  `nodeIdentityVar` set at node construction — used by Slices 2/3.
- **Rationale / why the fragile options are NOT used:** verified fact (§0) — the app imports `mcpCallTool` via
  **BOUND import** at 15 modules, so a naive boot monkeypatch of `mcpClient.mcpCallTool` NO-OPS (R-2). The
  per-module rebind (mechanism 1) is fragile and fail-open on any new importer; the network proxy (mechanism 3)
  loses graph state. DI at the composition root avoids both. **Constraint held:** the app edit stays minimal
  and confined to the composition root; this plan only DESCRIBES it — no app code is changed by this document.
- **Fallback (documented, not the POC path):** if the DI edit were ever disallowed, the coarse
  `(serverUrl, wire-toolName)`-derived identity (mechanism A) + per-module rebind would be the degraded
  alternative. Not used here.

---

## 6. Risks & notes

- **R1 — Identity is derived, not asserted.** The app passes only free-text `actor` and has **no node-identity
  contextvar** today (§0). The approved composition-root DI wrap (Decision iii) creates a precise node-entry
  `nodeIdentityVar` that the wrapper reads — identity is derived from that, **never** from agent text. Residual
  note for production: `nodeIdentityVar` is a service-identity proxy, not a cryptographically verifiable
  credential; a signed token/registry is the production hardening (out of POC scope).
- **R2 — POC scope creep.** Group-D tamper-evidence (hash-chain), Group-B model guardrails, and Group-C
  timeout contract are **out of scope**; the audit model only leaves a `prevEntryHash` placeholder for later.
- **R3 — e2e demos need the running app stack** (Streamable-HTTP MCP servers + Postgres). CI uses the lighter
  direct-`governedMcpCallTool` harness to stay hermetic.
- **R4 — App edit scope (Decision iii, approved).** The composition-root DI edit MUST stay minimal and confined
  to the app's `core/graph.py` (inject the governed call + set `nodeIdentityVar` at node construction); it must
  not alter the 15 call sites' logic. This plan only DESCRIBES that edit — no app code is changed here.

---

## 7. Build execution model (how the build runs once authorized)

> Planning text only — describes HOW the build will be executed after the team-lead authorizes it. **No builders
> are spawned by this document; no code is written here.** Consistent with the resolved decisions: DI edit
> confined to the app's `core/graph.py` (§5-iii), governance layer = this independent repo, pure-Python PDP
> (§5-ii), email MCP out of scope (§4 note).

### 7.1 Two-builder execution model

**governance-builder** — cwd = `/Users/sagarpratapsingh/dev/sagerstack/agentic-governance`.
- Builds the whole governance package (`core/`, `ports/`, `adapters/`, `integrations/`) + each slice (0–5) +
  Level-1 hermetic tests.
- **Full write access to THIS (governance) repo only.**

**integrator** (dedicated expense-app builder) — cwd = `/Users/sagarpratapsingh/dev/sagerstack/agentic-expense-claims`.
- Does **ONLY** the cross-repo wiring + e2e/regression. **HARD SCOPE:**
  - Works **EXCLUSIVELY on a NEW branch `feature/agentic-guardrails`** (created from the current default
    branch). **NEVER commits to `main`.** No force-push, no merge to main.
  - May edit **ONLY TWO files**: `pyproject.toml` (add the `agentic-governance` path dependency) and
    `src/agentic_claims/core/graph.py` (the composition-root DI edit + set `nodeIdentityVar` at node entry).
  - **Any other app file is OFF-LIMITS.** If something else appears necessary, **STOP and report to
    coordinator** — do not touch it.
  - Runs Level-2 e2e (against the docker stack) + Level-3 regression (the app's existing pytest with
    governance in Observe-only → behavior unchanged).

### 7.2 Sequencing

- **integrator is BLOCKED until governance-builder has shipped an installable Slice-0 package.** The coordinator
  gates this: governance **Slice 0** package ready → integrator installs (path dep) + does the DI edit on
  `feature/agentic-guardrails` → runs e2e.
- **Slices 1–5:** governance-builder adds logic; integrator **mostly re-runs the e2e harness** — the
  expense-repo footprint does **NOT** grow beyond those two files.

### 7.3 Cross-repo install

- **Poetry path dependency** for the POC, in the expense app's `pyproject.toml`:
  `agentic-governance = { path = "../agentic-governance", develop = true }`.

### 7.4 Three-level test strategy

- **Level 1 — hermetic (governance repo):** direct `governedMcpCallTool` calls with **ambient contextvars set**
  (e.g. `employeeIdVar`, `extractedReceiptVar`); deterministic control-unit coverage. No app/docker needed.
- **Level 2 — e2e (vs the running app / docker stack):** assert (a) the **disposition**, (b) the **Postgres
  side-effect happened-or-not**, and (c) the **JSONL audit event emitted**.
- **Level 3 — regression:** run the **app's existing pytest** with governance in **Observe-only** → behavior
  unchanged (proves the wrapper is non-breaking when not enforcing).

---

## 8. Definition of done (POC)

The POC is done when Slices 0–5 are shipped and each slice's e2e demo passes against the Expense app: every MCP
call yields an envelope + deterministic disposition + dashboard-ready audit event; forbidden tools, mandate
violations, origin mismatches, over-exposure, rate bursts, weak evidence, malformed args, and untrusted servers
are each provably **denied or escalated fail-closed**; and all 12 Group-A controls map to a shipped slice
(§4). The three decisions (§5) are **signed off**: in-process wrapper (i), pure-Python PDP (ii), and the
minimal composition-root DI edit (iii).

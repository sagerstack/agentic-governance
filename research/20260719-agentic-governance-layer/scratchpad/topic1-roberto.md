# Research: Topic 1 — Mandated / Recommended RUNTIME Controls for a Financial-Adjacent Agentic App (IMDA + MAS SAFR + FEAT/Veritas)

**Date**: 2026-07-19
**Researcher**: Roberto (`claude-opus-4-8`)
**Status**: Draft (P1 independent artifact)
**Target app**: LangGraph expense-claims pipeline — Intake → [Compliance ‖ Fraud] → Advisor → Decision. Python/FastAPI, OpenRouter LLM/VLM, 4 FastMCP tool servers (rag/db/currency/email), high-impact side effects (`submitClaim`, `updateClaimStatus`, `sendNotification`/email). Interception seams: per-LLM-call hooks (`preModelHook`/`postModelHook`), `mcpCallTool()` choke point, graph decision gates + `humanEscalation` node, `logEvent`→Seq audit log.

---

## 1. Executive Summary

- **The primary source exists and was retrieved in full.** MAS **SAFR — "Safeguards for Agentic Finance at Runtime"**, White Paper v1.0, published **3 July 2026** under MAS's BuildFin.ai program with 8 industry members. It is the single most on-point source: it specifies a **runtime governance layer that sits between the agent and execution**, evaluating each proposed action *before* it executes. This maps almost 1:1 onto the app's `mcpCallTool()` choke point.
- **SAFR's spine = 4 runtime components + 4 dispositions + a Governance Envelope.** Components: **Agent Identity → Controls Repository → Disposition Engine → Audit Log**. Every proposed action is packaged in a **Governance Envelope** (action + action-trace + context) and resolved to one of **Deny / Escalate / Auto-Execute / Observe**. This is the recommended architecture for the layer.
- **IMDA MGF for Agentic AI (v1.5, 20 May 2026)** is the second pillar. Its four dimensions supply concrete, runtime-relevant technical controls: **deterministic tool-layer access controls > prompt-layer guardrails**, **least-privilege tools/data**, **input/output guardrails**, **human approval at high-stakes/irreversible checkpoints**, **deny-by-default when approval infra fails**, **rate limits + input validation as runtime controls**, **immutable multi-layer logging**, and **"MCP as a governance layer."**
- **Normative caveat (important):** As of the source dates, **all three instruments are ADVISORY, not binding regulation.** SAFR explicitly states it "does not constitute regulatory guidance or supervisory expectations." IMDA MGF is a voluntary "model" framework. FEAT/Veritas are principles + assessment methodology. The MAS *Guidelines on AI Risk Management* (Nov 2025) — the closest thing to hard supervisory expectation — is still in consultation. So in the catalogue, **"Mandatory" = the framework's own strong language ("must"/"should hold"/core component); "Recommended" = softer ("could"/"may"/"consider").** No item is hard-law mandatory yet.
- **FEAT/Veritas add little at runtime** (they are design/validation-time fairness-ethics-accountability-transparency methodology). Only **Accountability→audit trail** and **Transparency→disclose AI use** have a thin runtime angle; the rest are marked *skip*.

**Single recommended approach (one line):** Implement SAFR's 4-component / 4-disposition runtime layer as the governance engine, physically anchored at the `mcpCallTool()` choke point (Disposition Engine + Controls Repository + mandates), with IMDA-style deterministic input/output guardrails at the model hooks, a timeout-bounded deny-by-default `humanEscalation` path, and a tamper-evident SAFR Audit Log extending `logEvent`→Seq.

---

## 2. Problem Statement

Catalogue the defensive controls a financial-adjacent agentic app **must/should implement AT RUNTIME**, drawn from (1) Singapore IMDA Model AI Governance Framework incl. GenAI and agentic editions; (2) MAS SAFR; (3) MAS FEAT/Veritas **only where they add runtime controls** — then map each to a concrete interception seam in the target app and flag applicability (or "skip + reason"). Search-first, evidence-gated, live citations only.

---

## 3. Control Catalogue

Seam legend: **IN** = input guardrail (`preModelHook`); **OUT** = output guardrail (`postModelHook`); **TOOL** = tool-use authorization / action gating (`mcpCallTool()`); **HUMAN** = human-oversight (graph gates + `humanEscalation`); **AUDIT** = governance audit log (`logEvent`→Seq).

### 3A. MAS SAFR — the on-point runtime framework (source: SAFR White Paper v1.0, 3 Jul 2026)

| # | Control | Mandatory vs Recommended | App seam | Applicability note |
|---|---------|--------------------------|----------|--------------------|
| S1 | **Governance Envelope** — before execution, package every proposed action as {action type+params, action-trace (tool calls/data/checks), context metadata (agent id, mandate, state, policy)} | SAFR-core ("should hold for every proposed action") | TOOL (produced at `mcpCallTool`) + AUDIT | **Applicable.** Wrap `submitClaim`/`updateClaimStatus`/`sendNotification` in an envelope before the MCP call executes. |
| S2 | **Envelope integrity / authenticate against origin** — treat the agent-declared trace as a document to authenticate, not trust; a prompt-injection can fabricate action+trace consistently | SAFR-core (explicit integrity risk) | IN + OUT + TOOL | **Applicable.** Directly counters prompt-injection via receipt image/chat text; validate envelope against independent state rather than the agent's own account. |
| S3 | **Agent Identity verification against a registry** — bind each action to a registered agent; verify before any other check; reject+log on failure | SAFR-core (component 1) | TOOL + AUDIT | **Applicable (closed-loop).** Single-institution → internal registry lookup. Give Intake/Compliance/Fraud/Advisor distinct registered identities. |
| S4 | **Controls Repository** — configurable rulebook (org policy, regulatory, product rules, user mandates) retrieved per action | SAFR-core (component 2) | TOOL | **Applicable.** Home = policy engine fronting `mcpCallTool`; encode SUTD expense policy + thresholds (Qdrant policy embeddings can feed evidence, but rules must be deterministic). |
| S5 | **Mandate / capability-based authority** — machine-readable delegation; agent cannot self-extend scope via reasoning | SAFR-core ("authority is explicit… not inferred") | TOOL | **Applicable.** Define per-agent mandate (e.g., Advisor may `updateClaimStatus` ≤ threshold; Intake may `submitClaim` only after validation). |
| S6 | **Disposition Engine — 4 outcomes: Deny / Escalate / Auto-Execute / Observe**, deterministic evaluation per action | SAFR-core (component 3) | TOOL + HUMAN | **Applicable.** The central gate for all 3 high-impact side effects; Escalate routes to `humanEscalation`. |
| S7 | **Risk calibration factors** — reversibility, financial materiality, customer impact, regulatory sensitivity, novelty/anomaly; higher risk → Deny/Escalate | SAFR-recommended (design-time calibration, runtime evaluation) | TOOL | **Applicable.** Calibrate expense-claim thresholds; e.g., large/irreversible disbursement or anomalous vendor → Escalate. |
| S8 | **Exposure limits** — per-action + aggregate value thresholds; below→autonomous, above→human/blocked | SAFR-recommended (Controls Repository, Table 1) | TOOL | **Applicable.** Claim-amount thresholds drive auto-approve vs escalate; mirror existing delegated-authority limits. |
| S9 | **Rate limits** — max action rate per window; guards runaway agents / feed errors / injection-driven bursts | SAFR-recommended (Table 1) | TOOL | **Applicable.** Cap `submitClaim`/`sendNotification` rate per employee/session. |
| S10 | **Evidence-quality threshold** — min confidence + required evidence for autonomous execution; below→human review regardless of value | SAFR-recommended (Table 1) | OUT + TOOL + HUMAN | **Applicable.** Low-confidence VLM receipt extraction or borderline fraud score → route to human. |
| S11 | **Authorisation controls** — which agents act for which principals; which action types each agent class may initiate; delegation depth | SAFR-recommended (Table 1) | TOOL | **Applicable.** Enforced at `mcpCallTool` per agent identity. |
| S12 | **Human-reviewer escalation discipline** — (a) escalation *volume* sized to review capacity; (b) **timeout window → default to block or senior escalation**; (c) reviewer has real authority to approve/modify/decline | SAFR-recommended (implementation guidance) | HUMAN | **Applicable.** `humanEscalation` node must carry a timeout + default-deny, not an open-ended flag. |
| S13 | **Tamper-evident, append-only Audit Log** — capture envelope, mandate checked, outcome, specific rules applied, basis, time-elapsed per stage; immutable once written | SAFR-core (component 4) | AUDIT | **Applicable.** Extend `logEvent`→Seq into an immutable governance record (Seq alone is not tamper-evident — needs append-only/hash-chaining). |
| S14 | **Per-action independent evaluation** — no carry-forward authority in multi-step workflows; each step re-evaluated | SAFR-recommended | TOOL | **Applicable.** Each of Intake→Compliance→Fraud→Advisor actions gated independently; an earlier Auto-Execute confers no authority downstream. |
| S15 | **Layering principle** — SAFR operates *after* content filtering, *before* execution; model-output guardrails are NOT a substitute for runtime action governance | SAFR-core (architectural) | IN/OUT + TOOL | **Applicable.** Justifies keeping BOTH model-hook guardrails AND a `mcpCallTool` action gate — they are complementary, not interchangeable. |
| S16 | **Deployment pattern** — Native Integration (instrument agent to emit envelope; recommended for new builds) vs Gateway Integration (intercept outbound calls; for legacy) | SAFR-recommended (Native for new) | TOOL | **Applicable.** Greenfield app → **Native**: instrument `mcpCallTool` + hooks directly (tightest audit trail). |

### 3B. IMDA MGF for Agentic AI v1.5 (source: IMDA, published 20 May 2026, updated 5 Jun 2026) — runtime-relevant technical controls

| # | Control | Mandatory vs Recommended | App seam | Applicability note |
|---|---------|--------------------------|----------|--------------------|
| I1 | **Deterministic tool-layer access controls > prompt-layer** — prevent a tool from being called at all / allow only read; "bound by design," prefer structural/rule-based over prompt-layer for higher-risk actions | Recommended (strong "should"/"prefer") | TOOL | **Applicable.** `mcpCallTool` enforces allow/deny/read-only per agent — the framework explicitly favours this over instructing the LLM. |
| I2 | **Least-privilege tools & data per agent** — minimum tools/data to complete task; scope by functional boundary | Recommended (should) | TOOL | **Applicable.** Fraud→`queryClaimsHistory` only; Advisor→`updateClaimStatus`/`sendNotification`; Intake→`submitClaim` etc. Separate MCP scopes per agent. |
| I3 | **Guardrails — input** (detect unsafe instructions, prompt-injection, jailbreak, PII) | Recommended (core "Controls" component) | IN (`preModelHook`) | **Applicable.** Receipt text + chat are untrusted input surfaces. |
| I4 | **Guardrails — output** (policy violation, toxicity, PII leakage, action inconsistent with user intent) | Recommended (core component) | OUT (`postModelHook`) | **Applicable.** Screen Advisor/Compliance verdicts + emails before they act. |
| I5 | **Human approval at significant checkpoints** — high-stakes / irreversible (payments, **sending communications**, editing sensitive data); outlier behaviour; user-defined thresholds | Recommended (should) | HUMAN | **Applicable.** `submitClaim`, `updateClaimStatus`, `sendNotification` = irreversible/communications → approval gate at graph edge. |
| I6 | **Deny-by-default when approval infrastructure fails** — block when supervisors unreachable or no established approval policy exists | Recommended (should) | HUMAN + TOOL | **Applicable.** Failsafe for `humanEscalation` timeouts / unknown action types. |
| I7 | **Runtime controls** — monitor & intervene *during* execution: rate limits (excessive tool use) + input validation (catch harmful responses before acted upon) | Recommended (explicit "Runtime controls") | IN + TOOL | **Applicable.** Complements S9; validate tool inputs at `mcpCallTool`. |
| I8 | **Strict/structured tool input formats** — configure tools to require strict input schemas | Recommended | TOOL | **Applicable.** Enforce `getClaimSchema`-defined shapes on `submitClaim`. |
| I9 | **"MCP as a governance layer"** — filter sensitive data passing through servers; log all agent-to-system interactions; whitelist only trusted MCP servers | Recommended (explicit callout) | TOOL + AUDIT | **Applicable & high-leverage.** The 4 FastMCP servers are exactly this seam: whitelist, PII-filter, and log every call. |
| I10 | **Agent identity — unique, cryptographically verifiable, accounted-for, centrally catalogued** | Recommended (should) | AUDIT + TOOL | **Applicable.** Complements S3; central catalogue prevents "agent sprawl." |
| I11 | **Authorisation — scoped, least-privilege, non-transferable, time/session-bound; bounded by authorizing human's own permissions** | Recommended (should) | TOOL | **Applicable.** An agent must not exceed the initiating employee's entitlements. |
| I12 | **Logging & monitoring — real-time intervention** (stop workflow + escalate on unauthorized access), **multi-layer** (user-agent, agent-tool, model-reasoning), **immutable logs**, **alert thresholds** (unauthorized access, too many tool calls), **anomaly detection**, deny-by-default on infra failure | Recommended (should) | AUDIT + HUMAN | **Applicable.** Extend Seq into multi-layer + immutable; add threshold alerts. |
| I13 | **Sensitive-data handling** — no agent write access to sensitive tables unless strictly required; let user take over when keying sensitive data; structurally separate sensitive data from agent context | Recommended (should) | IN/OUT + TOOL | **Applicable.** Receipt images, employee IDs, bank/vendor data; restrict `db` MCP writes; PII redaction (currently absent). |
| I14 | **Output verification / reflection** — LLM-as-judge + faithfulness/RAGAS metrics; terminate trajectory after N failed iterations (IMDA "Cyber Sierra" case, implemented in **LangGraph**) | Recommended (case-illustrated) | OUT | **Applicable & directly transferable** (same stack): gate Compliance/Advisor verdicts; caps hallucination. |
| I15 | **Structured inter-agent schemas** — typed function calls not free text; limit shared memory between agents | Recommended | OUT + TOOL (+ graph state) | **Applicable.** Constrain LangGraph state passing between Intake/Compliance/Fraud/Advisor to typed schemas. |
| I16 | **Automation-bias mitigation** — track human **override rate** + **response times**, audit oversight effectiveness | Recommended (should) | AUDIT + HUMAN | **Partially applicable at runtime.** Runtime angle = log override rate/latency; effectiveness auditing itself is periodic/offline. |

### 3C. IMDA MGF for Generative AI (source: IMDA/AI Verify Foundation, 30 May 2024) — nine dimensions

Largely **ecosystem-level, not runtime enforcement** for this app; the Agentic edition (3B) supersedes it in relevance. Runtime-adjacent dimensions only:

| # | Dimension | Verdict | App seam / note |
|---|-----------|---------|-----------------|
| G1 | **Security** (guardrails against adversarial input) | Recommended | IN/OUT — subsumed by I3/I4. |
| G2 | **Incident reporting** (post-deployment monitoring/reporting structures) | Recommended | AUDIT — subsumed by I12/S13. |
| G3 | Accountability, Data governance, Trusted dev & deployment, Testing & assurance, Content provenance, User literacy, Safety/alignment R&D | **Skip for runtime** | Design/validation/ecosystem-time; content provenance (watermarking) not applicable to internal expense claims. |

### 3D. MAS FEAT Principles + Veritas (sources: MAS FEAT Principles; Veritas Toolkit v2.0, 26 Jun 2023) — runtime angle only

FEAT/Veritas are **design/validation-time fairness-ethics-accountability-transparency methodology**, not runtime enforcement.

| Principle | Runtime angle | Verdict for this app |
|-----------|---------------|----------------------|
| **Fairness** | Bias assessment is offline methodology; runtime angle = monitor Fraud/Advisor for biased outcomes across employee profiles | **Mostly skip** — weak runtime hook; note as monitoring signal only. |
| **Ethics** | Governance principle | **Skip** — no runtime enforcement. |
| **Accountability** (internal + external) | Data lineage / audit trail; who is accountable per decision | **Thin add** → reinforces S13/I12 (audit). |
| **Transparency** | Disclose AI use to affected individuals | **Thin add** → UI disclosure that claim is AI-processed (not a governance-engine runtime control). |

### 3E. Adjacent MAS material picked up during search (context, runtime-relevant)

- **MindForge Operationalisation Handbook (2025)** — cited by SAFR (p.5) as giving agentic practices: **least privilege for agent tool/data access, kill switches and timeouts for autonomous-action containment, traceability through searchable logging.** Runtime-relevant → reinforces I2, S9/S12, S13. *Kill-switch/circuit-breaker* also appears in SAFR's Ant International case ("Circuit breakers can halt agent activity at the agent, principal, or counterparty level"). **Applicable**: a pipeline-level kill switch/circuit breaker + escalation timeout is a runtime control this catalogue should include (mapped HUMAN+TOOL).
- **MAS Guidelines on AI Risk Management (Nov 2025, consultation)** — closest to binding supervisory expectation (AI lifecycle controls, monitoring). Still *proposed*; informs the "mandatory" trajectory but not yet in force.

---

## 4. Recommendation

**Adopt SAFR's runtime layer as the reference architecture** for the app-agnostic governance engine, because it is (a) the only source purpose-built for *runtime, pre-execution* financial-action governance and (b) structurally isomorphic to the app's existing seams:

- **Disposition Engine + Controls Repository + Mandates** → anchor at `mcpCallTool()` (S4–S9, S11, S14; I1, I2, I8, I9, I11). Every high-impact side effect (`submitClaim`/`updateClaimStatus`/`sendNotification`) resolves to Deny/Escalate/Auto-Execute/Observe.
- **Governance Envelope + integrity auth** → constructed at the tool choke point, hardened by input/output guardrails at `preModelHook`/`postModelHook` (S1, S2, S15; I3, I4, I7, I13, I14).
- **Escalate disposition** → the `humanEscalation` node, upgraded with a **timeout window + default-deny** and a real-authority reviewer (S12, I5, I6; plus MindForge kill-switch/circuit-breaker).
- **Audit Log** → a tamper-evident, append-only extension of `logEvent`→Seq capturing envelope/mandate/outcome/rules/basis/timing (S13; I12, I16).
- **Agent Identity** → distinct registered identities per agent, centrally catalogued (S3; I10).

IMDA MGF supplies the **"prefer deterministic, system-level controls over prompt-layer"** discipline (I1) and the concrete guardrail/logging content; FEAT/Veritas and the GenAI edition add little at runtime and are mostly *skip*.

---

## 5. Disadvantages & Limitations

- **Nothing here is binding law yet.** Classifications rely on each framework's own normative language; a future MAS AIRG or SAFR revision could change strength. Flag as a freshness risk.
- **SAFR assumes deterministic disposition**; the app's risk signals (fraud score, VLM confidence, policy-match) are probabilistic — thresholding them deterministically requires careful calibration (S7).
- **Seq is not inherently tamper-evident**; S13/I12 require adding append-only/hash-chaining, not just more logging.
- **Envelope integrity (S2)** is hard: the paper itself notes a sophisticated injection can fabricate action+trace consistently — mitigation needs out-of-band state validation, not agent self-report.
- **FEAT fairness** has only a weak runtime hook; genuine bias control stays offline (aligns with DeepEval Safety category, not runtime enforcement).

---

## 6. Open Questions & Risks

- **Mandatory-vs-recommended is a strength-of-language judgment, not hard law.** If the team needs a strictly *legal* mandatory/optional split, that is a DECISION POINT for the manager (current classification documented and defensible, so not blocking).
- IMDA GenAI-edition nine dimensions: last dimension text was truncated in the retrieved snippet; treated as out-of-runtime-scope so not blocking.
- MindForge handbook items are cited **via SAFR** (secondary-within-primary); a direct fetch of the MindForge Operationalisation Handbook would harden S9/S12/S13 provenance if the team wants first-order citation.

---

## 7. References (all retrieved this session)

- [MAS SAFR — Safeguards for Agentic Finance at Runtime, White Paper v1.0 (PDF)](https://www.mas.gov.sg/-/media/mas-media-library/development/fintech/ai-safr/safr.pdf) — published 3 Jul 2026 — **primary**; full 4-component/4-disposition framework, Governance Envelope, Controls Repository (Table 1: Authorisation/Exposure/Rate/Evidence-quality), human-escalation discipline, deployment patterns, case studies.
- [MAS SAFR landing page](https://www.mas.gov.sg/publications/monographs-or-information-paper/2026/safeguards-for-agentic-finance-at-runtime) — 3 Jul 2026 — confirms scope: authorisation, human-oversight activation, point-of-decision recording.
- [MAS media release — "MAS Partners Industry to Develop Safeguards for AI Agents in Finance"](https://www.mas.gov.sg/news/media-releases/2026/mas-partners-industry-to-develop-safeguards-for-ai-agents-in-finance) — 3 Jul 2026 — BuildFin.ai, 8 industry members.
- [IMDA Model AI Governance Framework for Agentic AI v1.5 (PDF)](https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/mgf-for-agentic-ai.pdf) — published 20 May 2026, updated 5 Jun 2026 — **primary**; four dimensions, technical controls (deterministic > prompt-layer, least-privilege, guardrails, human approval, runtime controls, MCP-as-governance-layer, immutable logging, LangGraph reflection case).
- [IMDA — Updated Model AI Governance Framework for Agentic AI (factsheet)](https://www.imda.gov.sg/resources/press-releases-factsheets-and-speeches/factsheets/2026/updated-model-ai-governance-framework-for-agentic-ai) — 20 May 2026 — confirms four-pillar structure.
- [IMDA/AI Verify Foundation — Model AI Governance Framework for Generative AI (PDF)](https://aiverifyfoundation.sg/wp-content/uploads/2024/06/Model-AI-Governance-Framework-for-Generative-AI-19-June-2024.pdf) — 30 May/19 Jun 2024 — nine dimensions (accountability, data governance, trusted dev/deployment, incident reporting, testing & assurance, security, content provenance, user literacy, safety/alignment R&D).
- [MAS FEAT Principles (PDF)](https://www.mas.gov.sg/~/media/MAS/News%20and%20Publications/Monographs%20and%20Information%20Papers/FEAT%20Principles%20Final.pdf) — Fairness/Ethics/Accountability/Transparency for AIDA in the financial sector (design/validation-time methodology).
- [MAS — Veritas Toolkit v2.0 release](https://www.mas.gov.sg/news/media-releases/2023/toolkit-for-responsible-use-of-ai-in-the-financial-sector) — 26 Jun 2023 — open-source FEAT assessment methodology.
- [MAS — Consultation Paper on Guidelines on AI Risk Management](https://www.mas.gov.sg/publications/consultations/2025/consultation-paper-on-guidelines-on-artificial-intelligence-risk-management) — Nov 2025 (consultation) — AI lifecycle controls; closest to binding supervisory expectation, not yet in force.
- [MAS — MindForge AI Risk Management Operationalisation Handbook (PDF)](https://www.mas.gov.sg/-/media/mas-media-library/schemes-and-initiatives/ftig/project-mindforge/mindforge-ai-risk-management-operationalisation-handbook.pdf) — 2025 — agentic practices (least privilege, kill switches/timeouts, searchable-logging traceability); also referenced via SAFR p.5.

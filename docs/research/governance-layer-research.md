# Agentic Governance Layer — Research

> Canonical program deliverable. Target app: LangGraph expense-claims pipeline
> (Intake → [Compliance ‖ Fraud] → Advisor → Decision), Python/FastAPI, OpenRouter
> LLM/VLM, 4 FastMCP tool servers (rag/db/currency/email). High-impact side effects:
> `submitClaim`, `updateClaimStatus`, `sendNotification`/email. Governance-layer
> interception seams: per-LLM-call hooks (`preModelHook`/`postModelHook`), the
> `mcpCallTool()` tool choke point, graph decision gates + `humanEscalation` node,
> and the `logEvent`→Seq audit trail.

---

## 1. Mandated & Recommended Runtime Controls

**Date**: 2026-07-19 · **Authors**: Roberto (`claude-opus-4-8`) + Robin (`openai-codex/gpt-5.6-sol`) · **Status**: Final (Topic 1)

### 1.0 Executive summary

- **No legal mandate was established in this topic.** All three requested source families are **advisory/non-binding on the evidence retrieved**: MAS SAFR expressly states it "does not constitute regulatory guidance or supervisory expectations"; the IMDA Model AI Governance Frameworks (2020, GenAI 2024, Agentic 2026) are voluntary "model" frameworks; MAS FEAT is non-prescriptive and Veritas does not prescribe compliance steps. Genuine *mandates* would arise only from applicable law and any future **finalised** MAS AI Risk Management Guidelines — not established here and out of scope. (No final MAS AIRG instrument was located in a current-date search; retrieved MAS materials still call them *proposed*.)
- **SAFR is the runtime-architecture spine.** MAS's *Safeguards for Agentic Finance at Runtime* (v1.0, 3 Jul 2026) is the only source purpose-built for *runtime, pre-execution* governance of financial actions, and it maps almost 1:1 onto this app's `mcpCallTool()` choke point: a checkpoint of **four components** (Agent Identity → Controls Repository → Disposition Engine → Audit Log) that packages each proposed action in a **Governance Envelope** and resolves it to **Deny / Escalate / Auto-Execute / Observe**.
- **Recommended design = two complementary layers.** (1) Model input/output guardrails at `preModelHook`/`postModelHook`; (2) a deterministic SAFR-style action checkpoint at `mcpCallTool()`. SAFR is explicit that model-I/O guardrails and runtime action governance are **complementary, not interchangeable** — a "safe-looking" sentence can still request an unauthorised claim update.
- **Formal-scope caveat (applied consistently to SAFR *and* FEAT).** SAFR and FEAT/Veritas are scoped to *financial-institution* firms providing financial products/services; this is an *internal SUTD expense workflow*. The app therefore adopts **SAFR as a runtime architecture** and **IMDA/FEAT/Veritas as best-practice analogues by choice, not obligation**.
- **Highest-priority controls:** fail-closed authorization of `submitClaim`/`updateClaimStatus`/`sendNotification`; immutable, PII-safe decision evidence; human-review **timeouts + real authority**; and input/output guardrails for prompt-injection, sensitive-data leakage, unsupported decisions and malformed tool arguments.

### 1.1 Two-axis status key

Every control below is scored on **two independent axes** — never a bare "Mandatory":

- **Axis A — Binding force (legal/regulatory):** `Recommended (advisory)` for **every** control in the requested sources (all voluntary/non-binding on the evidence retrieved). No control is legally mandatory within this topic.
- **Axis B — Source-internal normative strength:** `core` = a core condition if adopting that framework (e.g., SAFR's four components; "must" within the reference architecture) · `should` = recommended practice · `may` = optional consideration · `illustrative` = drawn from a case study, not a framework-wide recommendation · `analogue` = a source practice adopted outside its formal target scope (used here for FEAT/Veritas, whose formal scope is financial-institution firms).

Seam legend: **IN** = input guardrail (`preModelHook`) · **OUT** = output guardrail (`postModelHook`) · **TOOL** = tool-use authorization (`mcpCallTool()`) · **HUMAN** = human-oversight (graph gates + `humanEscalation`) · **AUDIT** = governance audit log (`logEvent`→Seq).

### 1.2 Group A — Action-time authorization & governance (SAFR + IMDA Agentic MGF)

| Control | Source (with page) | Axis A / Axis B | Seam | Applicability to this app |
|---|---|---|---|---|
| **Pre-execution governance envelope** — package {action type+params, action-trace of tool calls/data/checks, context metadata (agent id, mandate, state, policy)} and validate completeness/coherence **before** execution. Build it from **trusted framework state, not solely agent-authored text**. | SAFR pp.8–10 | Recommended (advisory) / **core** | TOOL + AUDIT | Construct at `mcpCallTool()` before every MCP invocation; apply to all three high-impact tools. |
| **Envelope integrity / authenticate-against-origin** — a sophisticated injection can fabricate action *and* trace consistently; authenticate the envelope against its origin rather than trusting the agent's self-report. | SAFR pp.9–10 | Recommended (advisory) / **core** | **TOOL + AUDIT** (primary) | Compare agent declaration vs trusted graph/tool state; model hooks reduce injection risk but cannot *authenticate* an envelope. |
| **Verified, accountable agent identity** — unique, cryptographically verifiable identity bound to a human/department and acting capacity; centrally catalogued; reject+log unverified identities before any other check. | SAFR p.10; IMDA Agentic MGF §2.1.2 pp.23–24 | Recommended (advisory) / **core** (SAFR) · **should** (IMDA) | TOOL + AUDIT | Give Intake/Compliance/Fraud/Advisor distinct service identities so submission/status-change/email are attributable; closed-loop → internal registry lookup. |
| **Machine-readable mandate / capability authority** — allowed action types, thresholds, conditions, validity window, delegation hierarchy, revocation; the agent cannot infer or enlarge scope. | SAFR pp.10–11; IMDA §2.1.2 pp.23–24 | Recommended (advisory) / **core** (SAFR) · **should** (IMDA) | TOOL | e.g., Intake may submit only the current user's draft; Advisor may set only permitted status transitions; email only to policy-approved recipients/templates. |
| **Least privilege enforced structurally at the tool layer** — scoped, time/session-bound, non-transferable; restrict tools/data/read-write/calling-modes with deterministic controls, **not prompts**. | IMDA §§2.1.2, 2.3.1 pp.19, 24, 33–34 | Recommended (advisory) / **should** | TOOL | Enforce in the `mcpCallTool()` wrapper + MCP servers; split read vs write DB capability; deny tools not assigned to the calling agent. A system-prompt prohibition alone is insufficient. |
| **Deterministic per-action disposition** — evaluate each action against applicable controls → one binding result **Deny / Escalate / Auto-Execute / Observe**; re-authorize **every** step (prior approval carries no authority forward). | SAFR pp.11–13 | Recommended (advisory) / **core** | TOOL + HUMAN + AUDIT | A successful policy search must not authorize a later `submitClaim`; each call gets its own disposition + reason. |
| **Exposure limits** — per-action + aggregate value thresholds; below→autonomous, above→human/blocked. *(Distinct knob.)* | SAFR Table 1 pp.16–17 | Recommended (advisory) / **should** | TOOL | Amount/category/currency thresholds guard submission and approval; mirror existing delegated-authority limits. |
| **Rate limits** — max action rate per window; guards runaway agents, feed errors, injection-driven bursts. *(Distinct knob.)* | SAFR Table 1 pp.16–17 | Recommended (advisory) / **should** | TOOL | Cap `submitClaim`/`sendNotification` per employee/session; stop loops or bulk email. |
| **Evidence-quality threshold** — minimum confidence + required evidence for autonomous execution; weak evidence → review regardless of value. *(Distinct knob.)* | SAFR Table 1 pp.16–17 | Recommended (advisory) / **should** | TOOL + HUMAN | Low-confidence VLM extraction or borderline fraud score → route to human; Compliance/Advisor verdicts need cited policy evidence. |
| **Tool/protocol input hardening** — strict typed input schemas; trusted-MCP allowlist; sandbox code execution; filter sensitive data at MCP; structured schemas for inter-agent messages; limit shared memory. IMDA notes **"MCP as a governance layer"** (it sits between agent and systems). | IMDA §2.3.1 p.34 | Recommended (advisory) / **should** | IN + TOOL + AUDIT | Validate MCP args before policy eval; allow only the four registered servers; validate Intake→Compliance/Fraud→Advisor state at graph boundaries. **No code-exec MCP exists → sandboxing = skip unless one is later added.** |
| **Layered model-guardrails + action authorization** — content moderation / prompt-injection defences / output filtering run *before* SAFR-style action authorization; neither layer substitutes for the other. | SAFR pp.14–15; IMDA §§1.1.1, 2.3.1 pp.6–7, 33–34 | Recommended (advisory) / **core** (SAFR) · **should** (IMDA) | IN + OUT + TOOL | Justifies keeping BOTH model-hook guardrails AND the `mcpCallTool` gate. |
| **Deployment pattern = Gateway / hybrid trusted wrapper** — a wrapper at the shared `mcpCallTool()` choke point that derives the envelope from framework state is **Gateway/hybrid**, *not* SAFR "Native" (Native = the agent itself emits the envelope). Project rule forbids nodes importing infrastructure, favouring a boundary wrapper. | SAFR pp.15–16 (integration patterns) | Recommended (advisory) / **should** | TOOL | Implement as a trusted shared wrapper/gateway; move to Native only if agents themselves emit envelopes. |

### 1.3 Group B — Model input/output controls (IMDA GenAI + Agentic + 2020 MGF)

| Control | Source (with page) | Axis A / Axis B | Seam | Applicability to this app |
|---|---|---|---|---|
| **Runtime input validation & prompt-attack detection** — domain-tailored input filters detect unsafe/adversarial instructions and malformed data; validate before acted upon. GenAI "Security" dimension explicitly recommends **input filters** tailored to domain risks. | IMDA GenAI MGF, Security dimension (p.22) + Trusted Dev (pp.13–14); IMDA Agentic §2.3.1 p.34 | Recommended (advisory) / **should** | IN + TOOL | `preModelHook` inspects chat text, receipt OCR/VLM content and retrieved tool content for direct/indirect prompt injection; **treat the receipt image as untrusted multimodal input**. |
| **Sensitive-data minimisation & leakage guardrails** — restrict data/tool access, filter sensitive data through MCP, block inappropriate disclosure in output. | IMDA Agentic §§2.1.1, 2.3.1 pp.15–17, 34–35; GenAI Trusted Dev pp.13–14 | Recommended (advisory) / **should** | IN + OUT + TOOL | Minimise receipt images/employee IDs/claim history/vendor data sent through OpenRouter; redact/block PII in SSE/chat/email output; prevent cross-claim retrieval. |
| **Evidence-grounded output validation** — trusted retrieval (RAG), input/output filters, confidence/uncertainty signals; require policy evidence, flag uncertainty rather than treating fluent output as fact. GenAI notes RAG + confidence-assessment reduce hallucination. | IMDA GenAI Trusted Dev pp.13–15; SAFR evidence-quality p.17 | Recommended (advisory) / **should** | OUT + HUMAN | `postModelHook` checks Compliance/Advisor findings cite current RAG evidence and that amounts/currency/vendor facts match state; low-confidence/unsupported → `humanEscalation`. |
| **LLM-as-judge reflection loop** (LLM judge + faithfulness/RAGAS metrics; terminate trajectory after N failed iterations) — implemented in **LangGraph** in IMDA's *Cyber Sierra* case. | IMDA Agentic §2.3.1, Cyber Sierra case p.36 | Recommended (advisory) / **illustrative** | OUT | **Illustrative optional pattern** (same stack), *not* a framework-wide recommendation. LLM-as-judge is probabilistic and adds latency/cost — must **not** replace deterministic evidence/schema/policy checks. |
| **Robust exception handling / graceful failure** — detect invalid/unexpected inputs, identify non-repeatable exceptions, keep handling policy-aligned, surface new variables to a human, actively monitor deployed models. | IMDA 2020 MGF §§3.30–3.35 pp.46–48 | Recommended (advisory) / **should** | IN + OUT + HUMAN | On OCR ambiguity, unknown currency, missing schema fields, provider timeout or conflicting agent results — return a structured failure and escalate/return the claim; do not improvise or silently continue. |
| **Material-decision explanations** — understandable reasons for material decisions, salient data used, consequences; withhold fraud logic where disclosure enables gaming (retain full reason in audit). | IMDA 2020 §§3.26–3.29, 3.46–3.48 pp.44–45, 53–54; FEAT principles 13–14 (p.6, detail pp.10–13) [analogue] | Recommended (advisory) / **should** (IMDA) · analogue (FEAT) | OUT + HUMAN | Advisor output explains approve/return/escalate + remediation; less detail on fraud flags externally, full internal reason in audit. |

### 1.4 Group C — Human oversight, failsafes & recourse

| Control | Source (with page) | Axis A / Axis B | Seam | Applicability to this app |
|---|---|---|---|---|
| **Risk-calibrated human checkpoints** — require approval for high-stakes/irreversible/anomalous/user-threshold actions; the **disposition engine decides** (calibrated by reversibility, materiality, impact, regulatory sensitivity, novelty) — *not* a blanket gate on all side effects. Approval requests concise, contextual, expose risk/confidence; written justification for high risk. | IMDA Agentic §2.2.2 pp.29–31; IMDA 2020 §§3.14–3.18 pp.30–31; SAFR calibration p.12 | Recommended (advisory) / **should** | HUMAN + TOOL | A low-risk in-policy notification may Auto-Execute/Observe; a high-risk/novel status change or external email Escalates. `humanEscalation` shows proposed action + evidence + policy/risk result + editable decision, not a raw trace dump. |
| **Substantive escalation contract** — size review capacity; set a response **timeout**; on timeout **default to block or senior escalation**; reviewers hold explicit approve/modify/decline authority. | SAFR p.17 (Activating Human Reviewer Escalation) | Recommended (advisory) / **should** | HUMAN + AUDIT | Persist an escalation task in graph state with deadline + named role; "no reply" must never become implicit approval. |
| **Audit effectiveness of human oversight** — track override/modify rates + review response times; detect outlier reviewers; train reviewers on failure modes; ensure domain expertise. | IMDA Agentic §2.2.2 pp.29–30 | Recommended (advisory) / **should** | HUMAN + AUDIT | Emit reviewer decisions + latency to Seq; very low override rates / implausibly fast reviews trigger oversight-quality investigation, not "success." |
| **Fail closed & contain malfunction** — deny by default when approval infra is unavailable or an action has no established policy; circuit-break/halt on severe anomalies; use fallback procedures. | IMDA Agentic §§2.2.2, 2.3.3 pp.30, 43–44; MindForge Operationalisation Handbook (via SAFR p.5: kill switches/timeouts) | Recommended (advisory) / **should** | TOOL + HUMAN + AUDIT | Deny-by-default for unknown tools/actions; circuit-break repeated calls; halt the affected graph run → manual processing. No `submitClaim`/email during governance/Seq dependency failure. |
| **Employee recourse & correction** — a channel to query/appeal/request human review and submit verified supplementary information; retain decision context. | FEAT principles 10–11 (p.6, detail pp.10–11) [analogue]; IMDA 2020 §§3.52–3.54 pp.56–57 | Recommended (advisory) / analogue (FEAT) · **should** (IMDA 2020) | OUT + HUMAN + AUDIT | In the claim UI, let the employee correct extracted receipt facts and appeal a return/denial; verified corrections feed a human review, not model self-reaffirmation. |

### 1.5 Group D — Audit, monitoring & incident

| Control | Source (with page) | Axis A / Axis B | Seam | Applicability to this app |
|---|---|---|---|---|
| **Immutable, tamper-evident governance log** — append at decision time: submitted envelope, mandate, disposition, specific rules, reason, stage timings; reconstruction independent of the agent's own account. | SAFR pp.12–13 | Recommended (advisory) / **core** | AUDIT | `logEvent`→Seq is only a foundation — add an **external append-only/tamper-evident control (WORM / ledger / hash-chain as implementation *options*, not prescribed)**, plus stable correlation IDs, agent/principal identity, control versions. **PII-safe: log hashes/references + minimum redacted metadata with controlled access/retention — never raw receipt payloads/secrets in Seq.** |
| **End-to-end trace / black-box recorder** — record decisions, model/tool inputs, data sources, processes; retain securely for an appropriate duration, protected against alteration. | IMDA 2020 §§3.36–3.38 pp.48–49 | Recommended (advisory) / **should** | AUDIT | Correlate receipt upload → model calls → rag/db/currency/email tools → parallel agents → final disposition; store enough to replay governance without hoarding raw personal data. |
| **Multi-layer real-time monitoring + alert-specific intervention** — monitor user-agent, agent-tool and reasoning/output layers; threshold repeated/unauthorized tool calls; detect anomalous trajectories; specify review/halt/terminate/fallback by severity; keep failure logs immutable. | IMDA Agentic §2.3.3 pp.43–44 | Recommended (advisory) / **should** | AUDIT + HUMAN + TOOL | Seq alerts must trigger actual graph/tool interventions, not dashboards alone; prioritise DB writes, submissions, email; correlate across parallel Compliance/Fraud branches. |
| **Continuous accuracy / bias / drift monitoring + fallback** — review data/models/decisions for accuracy, relevance, unintended bias and intended behaviour; detect abnormal operation / model or data drift; preserve live explanations; define fallback/mitigation. | FEAT principles 3–4 (p.6, detail p.8) [analogue]; Veritas Doc 3 "Deploy & Monitor" (Step 4) pp.44–45 [analogue] | Recommended (advisory) / analogue | OUT + AUDIT + HUMAN | Monitor error/return/approval/fraud-escalation rates + extraction accuracy over time (incl. group disparities where lawful); trigger manual processing / model rollback on drift. |
| **Incident detection, reporting & remediation** — vulnerability-reporting channel; ongoing monitoring to catch malfunctions before end-users; internal notification + remediation; define materiality ("severe AI incident") threshold; proportionate external reporting only where independently required. | IMDA GenAI MGF, Incident Reporting dimension (pp.17–18) | Recommended (advisory) / **should** | AUDIT + HUMAN | Route material PII leakage, unauthorized DB writes, bad bulk emails, systematic claim errors from Seq alerts to an incident workflow. The framework itself creates **no** external reporting mandate; applicable law/policy must supply one. |

### 1.6 Explicit skips / non-runtime material

| Source item | Disposition |
|---|---|
| IMDA GenAI dimensions: Data (training-data/copyright), Content Provenance (watermarking/C2PA), Safety & Alignment R&D, **AI for Public Good** (#9), Testing & Assurance | **Skip** — ecosystem/development/R&D policy, not an enforcement control at a runtime seam. Content provenance is irrelevant to internal expense claims. |
| Pre-deployment third-party assurance & evaluation | **Skip here, retain in assurance workstream** — valuable, not a runtime control (IMDA Agentic pp.38–41; GenAI Testing & Assurance). Aligns with the app's offline DeepEval Safety category, which is *not* runtime enforcement. |
| IMDA Agentic: gradual rollout, end-user training, change-management governance | **Skip here, retain for deployment governance** — shape risk but don't enforce a live request/action (pp.42, 45–47). |
| FEAT internal approval/board-awareness/organisational-ethics structures | **Skip here, retain for governance process** — not runtime enforcement. |
| FEAT/Veritas as a *direct obligation* | **Not applicable as a mandate** — their stated scope is firms providing financial products/services; this internal SUTD expense app adopts the labelled analogues by choice only. |
| SAFR/IMDA "Mandatory" status | **Not applicable** — no legal mandate identified; all controls are Axis-A `Recommended (advisory)`. |

### 1.7 Recommended implementation order

1. **Wrap `mcpCallTool()` as a SAFR-style gateway/hybrid:** trusted envelope → identity → controls/mandate → deterministic disposition → append-only audit.
2. **First policies:** deny unknown action/tool; least privilege by agent; strict typed schemas; claim ownership + status-transition rules (authorize status changes by allowed-transition + ownership + evidence/compliance state + reviewer role — *not* a monetary threshold); amount/currency/evidence/rate thresholds for submission/approval; mandatory review for anomalous/high-impact cases.
3. **Model-hook guardrails:** prompt-injection/PII/input checks in `preModelHook`; grounding/PII/schema/decision-evidence checks in `postModelHook` — kept separate from tool authorization.
4. **Turn `humanEscalation` into an escalation contract:** persisted evidence, named authority, timeout, fail-closed default, reviewer-effectiveness metrics.
5. **Upgrade Seq into a tamper-evident, correlated, PII-safe governance record** and wire alert types to concrete observe/escalate/deny/halt/fallback actions.
6. **Add employee-facing explanation/correction/appeal flow** and continuous accuracy/drift/fairness monitoring as non-binding FEAT/Veritas analogues.

### 1.8 References (all retrieved this session)

- **[SAFR]** MAS, [*Safeguards for Agentic Finance at Runtime (SAFR), White Paper v1.0*](https://www.mas.gov.sg/-/media/mas-media-library/development/fintech/ai-safr/safr.pdf) — published 2026-07-03. Primary: 4 components, Governance Envelope (pp.8–10), Agent Identity (p.10), Disposition Engine + lifecycle (pp.11–13), Audit Log (pp.12–13), control categories Table 1 (pp.16–17), human-reviewer escalation (p.17), integration patterns (pp.15–16), MindForge kill-switch/timeout reference (p.5).
- **[SAFR-release]** MAS, [*MAS Partners Industry to Develop Safeguards for AI Agents in Finance*](https://www.mas.gov.sg/news/media-releases/2026/mas-partners-industry-to-develop-safeguards-for-ai-agents-in-finance) — 2026-07-03 (BuildFin.ai, 8 industry members).
- **[IMDA-Agentic]** IMDA, [*Model AI Governance Framework for Agentic AI, v1.5*](https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/mgf-for-agentic-ai.pdf) — published 2026-05-20, updated 2026-06-05. Primary: four dimensions; agent identity/authorization (§2.1.2 pp.23–24); technical controls incl. deterministic > prompt-layer, least privilege, MCP-as-governance-layer (§2.3.1 pp.33–34), Cyber Sierra LangGraph reflection (p.36); human oversight (§2.2.2 pp.29–31); monitoring/failsafes (§2.3.3 pp.43–44).
- **[IMDA-GenAI]** IMDA & AI Verify Foundation, [*Model AI Governance Framework for Generative AI*](https://aiverifyfoundation.sg/wp-content/uploads/2024/06/Model-AI-Governance-Framework-for-Generative-AI-19-June-2024.pdf) — 2024-06-19 (launched 2024-05-30). Nine dimensions verified on-screen: Accountability, Data, Trusted Development & Deployment, Incident Reporting, Testing & Assurance, Security, Content Provenance, Safety & Alignment R&D, **AI for Public Good**. Runtime hooks: Security→input filters (p.22); Trusted Dev→input/output filters + RAG (pp.13–14); Incident Reporting→vulnerability channel + monitoring + materiality threshold (pp.17–18).
- **[IMDA-2020]** IMDA/PDPC, [*Model Artificial Intelligence Governance Framework, Second Edition*](https://www.imda.gov.sg/-/media/imda/files/infocomm-media-landscape/sg-digital/tech-pillars/artificial-intelligence/second-edition-of-the-model-ai-governance-framework.pdf) — 2020-01-21. Runtime-relevant: risk-based human involvement (§§3.14–3.18 pp.30–31); decision explanations (§§3.26–3.29, 3.46–3.48 pp.44–45, 53–54); exception handling/graceful failure (§§3.30–3.35 pp.46–48); traceability/black-box recording (§§3.36–3.38 pp.48–49); review/recourse channel (§§3.52–3.54 pp.56–57). *(Granular cites verified on-screen by Robin.)*
- **[FEAT]** MAS, [*Principles to Promote Fairness, Ethics, Accountability and Transparency (FEAT)*](https://www.mas.gov.sg/-/media/mas/news-and-publications/monographs-and-information-papers/feat-principles-updated-7-feb-19.pdf) — updated 2019-02-07. Non-prescriptive; runtime-adjacent analogues: principles 3–4 (review), 10–11 (appeal/review + supplementary data), 13–14 (explanations) — p.6, detail pp.8, 10–13. *(Verified on-screen by Robin.)*
- **[Veritas]** MAS/Veritas Consortium, [*Veritas Document 3: FEAT Principles Assessment Methodology*](https://www.mas.gov.sg/-/media/mas-media-library/news/media-releases/2022/veritas-document-3---feat-principles-assessment-methodology.pdf) — 2022-02-04. Non-prescriptive; "Deploy & Monitor" (Step 4) pp.44–45 drift/abnormal-operation monitoring + fallback analogues.
- **[MAS-AIRG]** MAS, [*Consultation Paper on Guidelines on AI Risk Management*](https://www.mas.gov.sg/publications/consultations/2025/consultation-paper-on-guidelines-on-artificial-intelligence-risk-management) — Nov 2025 (consultation). Proposed MAS supervisory expectations for FIs; **no final instrument located in a current-date search** — retrieved MAS materials still call the guidelines *proposed*. Out of scope for this topic's classification.

---

## 2. Framework & Prior-Implementation Landscape

**Status**: Final (Stage 1 survey) · **Authors**: Roberto + Robin · **Date**: 2026-07-19

**Evaluation frame**: each candidate is scored against §1's **named** controls as **direct / partial / enabling / unsupported** (never whole-group over-crediting), with exact app seam, license, version/activity, and Python+LangGraph+MCP+OpenRouter fit. Two evidence rules: (a) **"covers ≠ compliant"** — supplying a mechanism is not the same as making the app compliant; (b) **OpenAI-wire-compatibility does NOT imply OpenRouter compatibility** — per-integration verification of `base_url`/auth/prompt-format/hard-coded endpoints is required. Seam legend: IN=`preModelHook`, OUT=`postModelHook`, TOOL=`mcpCallTool()`, HUMAN=`humanEscalation`, AUDIT=`logEvent`→Seq.

### 2.1 Comparison matrix

| Candidate | Coverage (IN / OUT / tool-authz / PII / HITL / audit) | License | Integration fit (Py+LangGraph+MCP+OpenRouter) | Best attach-point |
|---|---|---|---|---|
| **LangGraph / LangChain native** (middleware + `interrupt()`) | Y / Y / P / Y(built-in types) / Y / E(checkpoint/state trace) | MIT [LG-repo] | Native to the app's own stack; provider-agnostic; `interrupt()` needs durable checkpointer + stable thread_id [LG-interrupts] | IN/OUT/HUMAN; TOOL/AUDIT only via custom adapters |
| **Guardrails AI** (+Hub) | Y / Y / — / Y(Presidio) / — / E(validation history) | Apache-2.0 [GR-repo] | Python-native; LiteLLM/custom-LLM/OpenAI-compatible server → OpenRouter per-validator [GR-llms] | IN, OUT |
| **NVIDIA NeMo Guardrails** | Y / Y / P(IORails schema) / Y / — / E(OTel) | Apache-2.0 [NEMO-overview] | Python; **IORails** OpenRouter-ok but OpenAI-Chat-shape + structural only + NO multimodal; **LLMRails** = separate multimodal path [NEMO-railtypes, NEMO-io] | IN, OUT (tool schema only) |
| **Meta LlamaFirewall / Prompt Guard / Llama Guard** | Y / Y / — / P(privacy class) / — / — | Code MIT; **weights = Llama-4 Community License** (not OSI) [LFW-pypi, LG4-license] | PromptGuard/Llama Guard local or LG4-via-OpenRouter; **AlignmentCheck NOT OpenRouter-drop-in** (constructor takes only `scanner_name` → use CustomCheckScanner) [LFW-src] | IN, OUT |
| **Presidio** (community-owned) | — / — / — / Y / — / E | **MIT**, community-owned `data-privacy-stack` [PRES-license, PRES-transition] | Python, provider-agnostic; **image redactor beta** [PRES-image] | IN, OUT, AUDIT (pre-log redaction) |
| **protectai DeBERTa prompt-injection** | Y / — / — / — / — / — | **Apache-2.0** (HF model, local) [PI-deberta-license] | Local classifier, provider-agnostic | IN |
| **OPA (Rego)** | — / — / **Y** / — / E(disposition can request escalation) / E(decision logs) | Apache-2.0, CNCF-graduated [OPA-cncf, OPA-repo] | Provider-agnostic PDP (REST sidecar); Python via HTTP | TOOL |
| **AWS Cedar** | — / — / **Y** / — / — / — | Apache-2.0 (Rust + cedar-go) [Cedar-repo] | Delegation-scope authz ≈ SAFR mandate; Python fit weaker than OPA [Cedar-aws] | TOOL |
| **agentgateway v1.3.1** | P / P / **Y(JWT/CEL)** / P / — / E(trace/OTel) | Apache-2.0, Linux Foundation [AGW-repo] | **CONDITIONAL — transport-dependent**: drop-in only for HTTP/SSE/Streamable HTTP; else reuse logic in `mcpCallTool()` | TOOL (network boundary) |
| **Invariant Guardrails / (ex-)MCP-scan** | Y / Y / Y(contextual) / Y / — / E(trace) | Apache-2.0 [INV-repo] | **Reference PATTERN only**: `mcp-scan`→Snyk `agent-scan` (preflight, not runtime); old gateway hard-codes `api.openai.com`; repos stale [INV-snyk, INV-gw] | TOOL (in-process LocalPolicy adapter) |
| **Microsoft AGT** (Agent Governance Toolkit) | P / P / Y(wrapper) / P / Y(approval) / E(hash-chain) | MIT, **Public Preview** [AGT-repo] | Reference only — source-level interception/audit/expression gaps [AGT-limits] | TOOL, HUMAN |
| **OpenAI Agents SDK guardrails** | Y / Y / Y(tool tripwire) / — / — / — | OSS (non-LangGraph) [OAI-guardrails] | **Reference PATTERN only** (different agent framework) | — |
| **LangSmith / OpenEvals** | eval / eval / — / eval / — / E(trace/eval, not D1) | SDK MIT; LangSmith platform commercial [OE-repo] | Monitoring/eval **substrate**, not enforcement/authorization/audit-root | AUDIT (monitoring) |
| **Rebuff** | Y / — / — / — / — / — | Apache-2.0 but **ARCHIVED** (stale; gpt-3.5 default) [REBUFF-repo] | Skip — historical | — |
| **Protect AI LLM Guard** | Y / Y / — / Y(Presidio) / — / — | MIT but **ARCHIVED** (models unmaintained) [LLMG-repo] | Skip — historical | — |

_Matrix cell scale: **Y** = direct (= **D** in §2.2) · **P** = partial · **E** = enabling · **—** = unsupported._

### 2.1a Maturity / activity (per retrieved release/repo metadata, as of 2026-07-19)

- LangGraph 1.2.9 (2026-07-10, MIT, active) [LG-repo].
- Guardrails AI v0.10.2 (2026-06-04), repo active [GR-repo]; NeMo Guardrails 0.23.0 (2026-07-01), IORails experimental/opt-in [NEMO-io].
- Meta PurpleLlama active; LlamaFirewall v1.0.3; Llama Guard 4 / Prompt Guard 2 weights = Llama-4 Community License (not OSI) [LFW-pypi, LG4-license].
- Presidio v2.2.363 (2026-06-28), community-owned; image redactor beta [PRES-transition, PRES-image]; protectai DeBERTa Apache-2.0 [PI-deberta-license].
- OPA 1.18.2 (2026-07-02), CNCF-graduated [OPA-repo, OPA-cncf]; Cedar active (Rust + cedar-go) [Cedar-repo]; agentgateway v1.3.1 (2026-06-22, LF) [AGW-repo].
- Invariant STALE (`invariant` last push 2026-01-12; gateway 2025-11-06; `mcp-scan`→Snyk) [INV-repo, INV-snyk, INV-gw]; Rebuff ARCHIVED (last push 2024-08-07) [REBUFF-repo]; Protect AI LLM Guard ARCHIVED [LLMG-repo].
- Microsoft AGT Public Preview v4.1.0 (2026-06-09) [AGT-repo]; OpenEvals 0.2.0 / LangSmith SDK MIT, platform commercial [OE-repo].

### 2.2 Coverage map vs §1 Groups A–D (per named control)

Scoring: **D**=direct, **P**=partial, **E**=enabling component, **—**=unsupported. No candidate covers a full group; every entry below traces to the cited capability basis in §2.1 / References.

**Group A (action-time authorization)** — best OSS = OPA (deterministic disposition/least-privilege/schema) [OPA-docs]; Cedar (mandate/delegation-scope) [Cedar-aws]; agentgateway (identity/least-privilege/rate, conditional) [AGW-repo]; NeMo IORails (schema only, E) [NEMO-io]; Invariant LocalPolicy (dataflow/toxic-flow, reference) [INV-repo].
- Governance envelope → **—** (CUSTOM). Envelope integrity → **—** (CUSTOM origin authentication; per §1, injection/alignment scanning cannot authenticate an envelope against its trusted origin — AlignmentCheck [LFW-align] is at most a defence-in-depth signal elsewhere, not this control). Agent identity → **P** (agentgateway JWT [AGW-auth]; else CUSTOM registry). Mandate/capability → **P** (Cedar/OPA can *encode*, registry is CUSTOM) [Cedar-aws]. Least-privilege (structural) → **D** (OPA/Cedar/agentgateway; deterministic tool-layer) [OPA-docs]. Deterministic disposition → **D** (OPA returns structured disposition) [OPA-docs]. Exposure limits → **P** (OPA evaluates but atomic counters CUSTOM). Rate limits → **P** (agentgateway rate-limit [AGW-repo]; OPA needs external counters). Evidence-quality → **P** (needs app-normalized facts). Tool input hardening / MCP-as-governance → **P** (compound control: NeMo IORails typed-schema [NEMO-io] + agentgateway/Invariant allowlist & dataflow rules [AGW-repo, INV-repo] cover parts; trusted-MCP allowlist + sensitive-data filter + structured inter-agent messages + shared-memory limits + conditional sandbox = CUSTOM composition). Layered guards+action-authz → architecture-level. Gateway/hybrid pattern → architecture-level.

**Group B (model I/O)** — input attack → **D** (Prompt Guard 2 / DeBERTa local [PI-deberta]; selected NeMo/Guardrails input checks [NEMO-railtypes, GR-hub]) — signals, not sole authority. **Llama Guard 4 = broad multimodal CONTENT-SAFETY classification, NOT a direct prompt-injection detector** — optional content signal only; published limits: English output-filter recall 69% / FPR 11%, single-image recall 41% / FPR 9%, plus self-injection susceptibility → never sole authority [OR-catalog, LG4-card]. Sensitive-data/PII → **D** (Presidio [PRES-anon]; LangChain PIIMiddleware built-ins [LC-pii]). Grounded output validation → **P** (RAG/groundedness evaluators are shadow/monitor; blocking check = CUSTOM deterministic tie to graph state) [OE-repo]. LLM-as-judge reflection → **E/illustrative** (OpenEvals/NeMo; probabilistic, latency/cost) [OE-repo]. Graceful failure → **P** (NeMo fail-closed rails [NEMO-io]; else CUSTOM). Material-decision explanations → **—** (CUSTOM).

**Group C (human oversight)** — risk-calibrated checkpoints → **P** (LangGraph HITL/interrupt host [LC-hitl]; disposition decides). Substantive escalation contract (timeout→default-deny, authority, one-time binding) → **—** (CUSTOM; `interrupt()` waits indefinitely [LG-interrupts]). Oversight-effectiveness metrics → **E** (Seq/LangSmith capture override-rate/latency). Fail-closed & contain → **P** (deny-by-default + kill-switch, partly CUSTOM). Employee recourse → **—** (CUSTOM).

**Group D (audit/monitoring/incident)** — immutable tamper-evident log → **—** (CUSTOM; OPA decision logs / Seq / OTel are NOT WORM/ledger) [OPA-decisionlogs]. End-to-end trace → **E** (LangGraph state + Seq + OTel). Multi-layer monitoring + intervention → **P** (agentgateway/Invariant monitor; **alerts must call a control-plane adapter**, not dashboards) [AGW-repo]. Drift/fairness monitoring → **E** (LangSmith/OpenEvals substrate; datasets/metrics CUSTOM) [OE-repo]. Incident detection/reporting → **—** (playbooks CUSTOM).

**Controls with NO good OSS option (must be CUSTOM):** authoritative agent-identity/mandate registry; governance envelope + origin authentication; ownership/state/evidence-sufficiency & business-transition facts; atomic exposure/rate counters; disposition orchestration; approver authority + timeout + one-time action-hash binding; tamper-evident PII-safe audit ledger (D1 root); employee recourse workflow; fairness/drift-linked intervention; incident-response playbooks.

### 2.3 Shortlist of closest references to leverage

- **OPA** — most mature deterministic PDP; the Disposition Engine/least-privilege backbone at `mcpCallTool()` [OPA-docs].
- **LangGraph `interrupt()`** — durable pause/resume host for the escalation contract at `humanEscalation` [LG-interrupts].
- **Presidio** — strongest focused PII detector/anonymizer for IN/OUT + pre-log redaction (text; image redactor beta) [PRES-anon, PRES-image].
- **Prompt Guard 2 / DeBERTa (local)** for input-attack signals; **Llama Guard 4** (present in the current OpenRouter catalog) as an optional multimodal *content-safety* signal — not injection detection, low published recall → never sole authority [PI-deberta, OR-catalog, LG4-card].
- **agentgateway v1.3.1** — conditional network MCP defence-in-depth (JWT/CEL) if transport is HTTP/SSE [AGW-repo].
- **Invariant LocalPolicy / toxic-flow** — in-process reference for cross-step dataflow / indirect-injection rules [INV-repo].
- **Cedar** — reference for mandate/delegation-scope authz semantics ≈ SAFR mandate [Cedar-aws].
- **Microsoft AGT** — reference for action-bound approval objects (Public Preview; do not adopt as core) [AGT-repo].

---

## 3. Reference Architecture & Incremental Implementation Plan

**Status**: Final (Stage 2 skeleton) · **Authors**: Roberto + Robin · **Date**: 2026-07-19

### 3.1 App-agnostic integration contract

The governance layer is an **integration contract over two boundaries + decision gates + an audit adapter**, honoring the Profile §6 rule (**nodes import only governance *contracts/domain types*, never concrete infra; adapters are injected by the composition root**). The governance engine is a pure decision/pipeline; detectors and the PDP are pluggable adapters.

- **Model boundary** (`preModelHook`/`postModelHook`) → input/output guardrail pipeline (Group B).
- **Tool boundary** (`mcpCallTool()`) → SAFR-style checkpoint: build a **Governance Envelope from TRUSTED graph/tool state** (not agent-authored text) → verify agent identity → retrieve controls/mandate → **deterministic Disposition Engine (Deny / Escalate / Auto-Execute / Observe)** via the OPA PDP → emit to audit.
- **Decision gates + `humanEscalation`** → the **Escalate** disposition routes here under a **timeout→default-deny escalation contract** (approver identity/authority, deadline, one-time action-hash binding, fail-closed expiry).
- **Audit adapter** behind `logEvent()` → callers use **one audit-adapter API**. The **durable append to the tamper-evident D1 root (external append-only sink or externally-anchored hash chain; WORM/ledger = options) is authoritative**: a high-impact action must **fail closed if it cannot first be durably recorded** to that root (write-to-root-before-ack). The **redacted, correlation-rich Seq** (searchable sink) fan-out is delivered from a **durable outbox** — so an action never executes after only the non-tamper-evident Seq write succeeds. Raw receipt/PII is stored OUTSIDE Seq as access-controlled evidence references. Framework status = CUSTOM (no surveyed OSS component alone satisfies D1).

### 3.2 Four-phase incremental roadmap

| Phase | §1 Group(s) & named controls | Stage-1 framework(s) / reference | Attach-point(s) |
|---|---|---|---|
| **1 — Audit foundation + PII + fail-closed floor** | **D** (immutable tamper-evident log, black-box trace) + **B** (sensitive-data/PII) + minimal **C** (fail-closed) | Presidio (text; image redactor beta → deferred) [PRES-image]; CUSTOM dual-sink audit adapter (write-to-tamper-evident-root before ack; durable Seq outbox fan-out) (Seq + external tamper-evident root); minimal static high-impact-tool **allowlist + reject-on-missing/unavailable-governance + kill switch** | IN, OUT (PII); AUDIT (dual-sink); TOOL (fail-closed floor) |
| **2 — Input/output guardrails** | **B** (input-attack validation, grounded output, optional bounded judge/reflection, graceful structured failure, material-decision explanations) | IN: DeBERTa/Prompt Guard 2 local for injection [PI-deberta] + Llama Guard 4 as optional content-safety signal (present in current OpenRouter catalog; not injection detection) [OR-catalog, LG4-card]; OUT: NeMo IORails schema [NEMO-io] + Guardrails AI [GR-hub] + **CUSTOM deterministic checks** tying amounts/currency/vendor/status + cited RAG evidence to trusted graph state; evaluators (OpenEvals/LangSmith) = **shadow/monitor, escalate-only** [OE-repo] | IN, OUT |
| **3 — Tool-use authorization / action gating** | **A** (all Group-A controls; direct focus: envelope, integrity, identity, mandate, least-privilege, disposition, exposure, rate, evidence, schema) | **OPA = baseline PDP** at `mcpCallTool()` invoked with the trusted envelope [OPA-docs]; **Cedar = alternative** (not a simultaneous 2nd PDP) [Cedar-aws]; **agentgateway = viable** network defence-in-depth — transport CONFIRMED Streamable HTTP for all 4 servers (see §3.4), so proxy-in-front is available in addition to in-process [AGW-repo]; Invariant toxic-flow = in-process reference [INV-repo]; **CUSTOM identity/mandate registry + atomic exposure/rate counters** | TOOL (+ disposition→AUDIT) |
| **4 — Human oversight / escalation** | **C** (risk-calibrated checkpoints, substantive escalation contract, oversight-effectiveness metrics, fail-closed [inherited], employee recourse/correction) | LangGraph `interrupt()` via `humanEscalation` = durable host [LG-interrupts]; **CUSTOM escalation-contract** (approver identity/authority, deadline, one-time action-hash binding, fail-closed expiry); AGT action-bound approval = reference only [AGT-repo] | HUMAN + TOOL (Escalate routes here) + AUDIT (C3 metrics) |

### 3.3 Cross-phase monitoring & incident (D3–D5)

- **D3 intervention-linked monitoring (Phases 3–4):** Seq alerts MUST call a control-plane adapter to **review / halt / terminate / fallback** — not dashboards alone [AGW-repo].
- **D4 drift/fairness + D5 incidents (cross-phase):** LangSmith/OpenEvals are **substrates only** [OE-repo]; labelled datasets, fairness metrics, intervention rules, and incident playbooks are **CUSTOM**.

### 3.4 Prerequisites & unresolved gaps

- **RESOLVED — MCP transport confirmed: all four FastMCP servers (rag/db/currency/email) run `mcp.run(transport="streamable-http")`, and the client connects via `streamablehttp_client()` in `mcpClient.py`** (verified 2026-07-19 in the `agentic-expense-claims` repo; servers exposed as separate containers on the Docker network — mcp-rag:8001, mcp-db:8002, mcp-currency:8003, mcp-email:8004). Because every tool call is a proxiable HTTP request, **network-proxy tooling (agentgateway; Invariant proxy mode) is drop-in viable** — the stdio/in-process-only fallback does NOT apply. Recommended Phase 3 design uses **both** boundaries: a network proxy in front of the MCP servers (identity/JWT, rate, schema, defence-in-depth) PLUS in-process disposition at `mcpCallTool()` (the single client choke point) for state-aware decisions that need the trusted graph-state governance envelope.
- **UNRESOLVED — raw receipt-IMAGE governance.** Presidio's image redactor is **beta / not production-ready** [PRES-image]; OCR-derived *text* can be sanitized, but governance of the raw receipt image (PII in the image itself) — the **surveyed set identified no production-ready OSS option** (the survey did not exhaust every image-redaction project) — treat as an open gap requiring a tested replacement or an explicit risk-acceptance decision.
- **D1 audit root is CUSTOM** — no surveyed OSS component provides a tamper-evident ledger; Seq/OPA-decision-logs/OTel are searchable/observability layers, not WORM/ledger assurance.

---

## References — Sections 2 & 3 (all retrieved this session; on-screen-verified facts noted)

- [LG-repo] LangGraph repo (MIT) — https://github.com/langchain-ai/langgraph
- [LG-interrupts] LangGraph Interrupts (durable pause; waits indefinitely) — https://docs.langchain.com/oss/python/langgraph/interrupts
- [LC-hitl] LangChain Human-in-the-loop middleware — https://docs.langchain.com/oss/python/langchain/human-in-the-loop
- [LC-pii] LangChain PIIMiddleware (built-in detectors) — https://github.com/langchain-ai/langchain/blob/master/libs/langchain_v1/langchain/agents/middleware/pii.py
- [GR-repo] Guardrails AI repo (Apache-2.0) — https://github.com/guardrails-ai/guardrails
- [GR-hub] Guardrails Hub (validators incl. PII/prompt) — https://guardrailsai.com/hub
- [GR-llms] Guardrails supported LLMs (LiteLLM) — https://guardrailsai.com/guardrails/docs/how-to-guides/using_llms
- [NEMO-overview] NeMo Guardrails overview (Apache-2.0) — https://docs.nvidia.com/nemo/guardrails/about-nemo-guardrails-library/overview
- [NEMO-railtypes] NeMo rail types (input/retrieval/dialog/execution/output) — https://docs.nvidia.com/nemo/guardrails/about-nemo-guardrails-library/rail-types
- [NEMO-io] NeMo v0.23 IORails tool-calling (schema/structural, OpenAI-shape, no multimodal) — https://github.com/NVIDIA-NeMo/Guardrails/blob/v0.23.0/docs/configure-rails/guardrail-catalog/tool-calling.mdx *(Robin-retrieved)*
- [LFW-align] LlamaFirewall AlignmentCheck (reasoning audit) — https://meta-llama.github.io/PurpleLlama/LlamaFirewall/docs/documentation/scanners/alignment-check
- [LFW-src] AlignmentCheck scanner source, commit-pinned (constructor = `scanner_name` only → CustomCheckScanner is the endpoint-configurable class) — https://github.com/meta-llama/PurpleLlama/blob/27d52f20fc3f4b9310f1cc0c241c3e6b92029df2/LlamaFirewall/llamafirewall/scanners/alignment_check_scanner.py *(Robin-retrieved permalink)*
- [LFW-pypi] llamafirewall v1.0.3 (code MIT; weights community-licensed) — https://pypi.org/project/llamafirewall/1.0.3/
- [OR-catalog] OpenRouter model catalog `/api/v1/models` (retrieved 2026-07-19; 338 models): `meta-llama/llama-guard-4-12b` PRESENT, NO `llama-guard-3` entry (authoritative present/absent proof) — https://openrouter.ai/api/v1/models
- [OR-LG4] Llama Guard 4 12B on OpenRouter (product page) — https://openrouter.ai/meta-llama/llama-guard-4-12b
- [LG4-card] Meta Llama Guard 4 12B model card — recall/FPR metrics + self-injection warning + Llama-4 Community License — https://github.com/meta-llama/PurpleLlama/blob/b71c6350a2acf2fb62c2328a734cbf440ecac386/Llama-Guard4/12B/MODEL_CARD.md *(Robin-retrieved)*
- [LG4-license] Llama Guard 4 12B Community License (not OSI-OSS) — https://github.com/meta-llama/PurpleLlama/blob/b71c6350a2acf2fb62c2328a734cbf440ecac386/Llama-Guard4/12B/LICENSE *(Robin-retrieved)*
- [OR-LG3] (superseded by [OR-catalog]) Llama Guard 3 8B OpenRouter page shows no activity; catalog confirms absence — https://openrouter.ai/meta-llama/llama-guard-3-8b
- [OR-quickstart] OpenRouter Quickstart (OpenAI-compatible) — https://openrouter.ai/docs/quickstart
- [PRES-anon] Presidio anonymizer (text redact/replace/mask) — https://github.com/microsoft/presidio/tree/main/presidio-anonymizer
- [PRES-license] Presidio LICENSE = MIT (verified on-screen) — https://github.com/microsoft/presidio/blob/main/LICENSE
- [PRES-transition] Presidio community-ownership transition (`data-privacy-stack`) — https://github.com/data-privacy-stack/presidio/blob/main/docs/project_transition.md *(Robin-retrieved)*
- [PRES-image] Presidio Image Redactor — beta / not production-ready — https://github.com/data-privacy-stack/presidio/blob/main/docs/image-redactor/index.md *(Robin-retrieved)*
- [PI-deberta] protectai deberta-v3 prompt-injection (local) — https://huggingface.co/protectai/deberta-v3-base-prompt-injection-v2
- [PI-deberta-license] protectai deberta-v3 model card — License Apache-2.0 (verified on-screen) — https://huggingface.co/protectai/deberta-v3-base-prompt-injection-v2/blob/main/README.md
- [REBUFF-repo] Rebuff (Apache-2.0; ARCHIVED/stale — verified gpt-3.5 default) — https://github.com/protectai/rebuff
- [OPA-repo] OPA repo (Apache-2.0) — https://github.com/open-policy-agent/opa
- [OPA-cncf] OPA CNCF Graduated — https://www.cncf.io/projects/open-policy-agent-opa/
- [OPA-docs] OPA official documentation — general-purpose PDP, policy language + REST API + arbitrary structured decisions — https://www.openpolicyagent.org/docs/latest/
- [OPA-decisionlogs] OPA decision logs + masking (not a tamper-evident ledger) — https://www.openpolicyagent.org/docs/latest/management-decision-logs/ *(Robin-retrieved)*
- [Cedar-repo] cedar-policy/cedar (Apache-2.0; Rust + cedar-go) — https://github.com/cedar-policy/cedar
- [Cedar-aws] AWS least-privilege multi-agent Cedar (delegation-scope) — https://aws.amazon.com/blogs/security/enforce-least-privilege-authorization-in-multi-agent-ai-chains-using-cedar/
- [AGW-repo] agentgateway v1.3.1 (Apache-2.0, LF; JWT/CEL MCP authz, external guardrail hooks, OTel) — https://github.com/agentgateway/agentgateway/blob/v1.3.1/README.md *(Robin-retrieved)*
- [AGW-auth] agentgateway v1.3.1 authorization example — https://github.com/agentgateway/agentgateway/blob/v1.3.1/examples/authorization/README.md *(Robin-retrieved)*
- [INV-repo] Invariant Guardrails (in-process LocalPolicy/toxic-flow reference) — https://github.com/invariantlabs-ai/invariant
- [INV-snyk] Snyk agent-scan (ex-`mcp-scan`; preflight, not runtime) — https://github.com/snyk/agent-scan/blob/main/README.md *(Robin-retrieved)*
- [INV-gw] Invariant Gateway (hard-codes api.openai.com) — https://github.com/invariantlabs-ai/invariant-gateway *(Robin-retrieved)*
- [AGT-repo] Microsoft Agent Governance Toolkit (MIT, Public Preview) — https://github.com/microsoft/agent-governance-toolkit *(Robin-retrieved)*
- [AGT-limits] AGT Known Limitations (reasoning/injection/audit gaps) — https://github.com/microsoft/agent-governance-toolkit/blob/main/docs/LIMITATIONS.md *(Robin-retrieved)*
- [OAI-guardrails] OpenAI Agents SDK guardrails (tripwire; reference pattern) — https://openai.github.io/openai-agents-python/guardrails/
- [OE-repo] OpenEvals (MIT) / LangSmith (SDK MIT, platform commercial) — https://github.com/langchain-ai/openevals *(Robin-retrieved)*
- [LLMG-repo] Protect AI LLM Guard (MIT; ARCHIVED) — https://github.com/protectai/llm-guard *(Robin-retrieved)*

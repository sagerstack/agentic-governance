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
| **3 — Tool-use authorization / action gating** | **A** (all Group-A controls; direct focus: envelope, integrity, identity, mandate, least-privilege, disposition, exposure, rate, evidence, schema) | **OPA = baseline PDP** at `mcpCallTool()` invoked with the trusted envelope [OPA-docs]; **Cedar = alternative** (not a simultaneous 2nd PDP) [Cedar-aws]; **agentgateway = conditional** network defence-in-depth IF transport is HTTP/SSE [AGW-repo]; Invariant toxic-flow = in-process reference [INV-repo]; **CUSTOM identity/mandate registry + atomic exposure/rate counters** | TOOL (+ disposition→AUDIT) |
| **4 — Human oversight / escalation** | **C** (risk-calibrated checkpoints, substantive escalation contract, oversight-effectiveness metrics, fail-closed [inherited], employee recourse/correction) | LangGraph `interrupt()` via `humanEscalation` = durable host [LG-interrupts]; **CUSTOM escalation-contract** (approver identity/authority, deadline, one-time action-hash binding, fail-closed expiry); AGT action-bound approval = reference only [AGT-repo] | HUMAN + TOOL (Escalate routes here) + AUDIT (C3 metrics) |

### 3.3 Cross-phase monitoring & incident (D3–D5)

- **D3 intervention-linked monitoring (Phases 3–4):** Seq alerts MUST call a control-plane adapter to **review / halt / terminate / fallback** — not dashboards alone [AGW-repo].
- **D4 drift/fairness + D5 incidents (cross-phase):** LangSmith/OpenEvals are **substrates only** [OE-repo]; labelled datasets, fairness metrics, intervention rules, and incident playbooks are **CUSTOM**.

### 3.4 Prerequisites & unresolved gaps

- **PREREQUISITE — confirm the MCP transport of all four FastMCP servers** (rag/db/currency/email). External network-proxy tooling (agentgateway; Invariant proxy mode) is **drop-in only for HTTP/SSE/Streamable HTTP**; for stdio/in-process FastMCP, reuse the policy/scanning logic **in-process inside `mcpCallTool()`**. The Profile does not specify transport, so this must be confirmed before Phase 3 tooling is chosen.
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

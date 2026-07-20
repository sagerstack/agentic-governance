# Stage 1 Landscape Survey — OSS Guardrail Frameworks & Agentic-Guardrail Reference Architectures

**Date**: 2026-07-19 · **Researcher**: Roberto (`claude-opus-4-8`) · **Status**: Draft (Stage 1 P1, independent)

**Grounding**: Aligned to `docs/research/governance-layer-research.md` §1 control rows (Groups A–D) and the app seams from `APP-INTEGRATION-PROFILE.md`: `preModelHook` (IN), `postModelHook` (OUT), `mcpCallTool()` (TOOL), `humanEscalation` node (HUMAN), `logEvent`→Seq (AUDIT). Every capability claim below carries a live-retrieved citation; no capability is asserted without one.

§1 control shorthand used below — **A** = action-time authorization/governance (envelope, identity, mandate, least-privilege, deterministic disposition Deny/Escalate/Auto-Execute/Observe, exposure/rate/evidence limits, tool input hardening, MCP-as-governance-layer); **B** = model I/O (input prompt-injection/PII validation, output/leakage validation, evidence-grounded output, exception handling); **C** = human oversight/failsafes/recourse (risk-calibrated checkpoints, escalation contract w/ timeout→default-block, fail-closed/kill-switch, recourse); **D** = audit/monitoring/incident (immutable tamper-evident log, black-box trace, multi-layer monitoring+intervention, drift monitoring, incident reporting).

---

## 0. Executive summary

- **The stack is favourable.** OpenRouter is **OpenAI-API-compatible** (`/api/v1/chat/completions`, swap base URL) [OR-quickstart], so every LLM-based guardrail here works via LiteLLM / OpenAI-compatible `base_url`. Crucially, **Llama Guard 3 8B and Llama Guard 4 12B are hosted on OpenRouter directly** for input+output safety classification [OR-LG3, OR-LG4] — a provider-native content-moderation option with zero extra infra.
- **Best integration fit = LangChain/LangGraph native middleware**, because it is the app's own framework: `guardrails`/`PIIMiddleware`/HITL middleware + `interrupt()` cover much of Groups B and C at the exact seams (`preModelHook`/`postModelHook`/`humanEscalation`) [LC-guardrails, LC-pii, LC-hitl, LG-interrupts].
- **Best tool-boundary (Group A) fit = a policy-as-code PDP (OPA/Rego or Cedar) wired into `mcpCallTool()`**, plus **Invariant Guardrails / MCP-scan** which is purpose-built to sit *between the app and MCP servers* and guardrail tool calls/responses (incl. toxic-flow / indirect-injection analysis) [OPA-agents, Cedar-aws, INV-repo, INV-mcpscan].
- **Best-in-class detectors are drop-in and provider-agnostic**: Microsoft Presidio (PII detect+anonymize) [PRES-entities], protectai `deberta-v3` prompt-injection models (local HF) + Rebuff [PI-deberta, REBUFF], Meta LlamaFirewall (PromptGuard local + AlignmentCheck reasoning-audit) [LFW-about, LFW-align].
- **Note (manager ruling)**: external MCP-proxy/agent-firewall tools (Invariant/MCP-scan) are framed as **in-process guardrail logic inside `mcpCallTool()`** by default; network-proxy deployment is **CONDITIONAL — transport-dependent** (only if MCP transport is HTTP/SSE).
- **What NOTHING off-the-shelf provides** (must be custom, as §1 already flags): SAFR's **Governance Envelope + envelope-integrity authentication**, an **Agent-Identity registry + machine-readable mandate**, an **immutable tamper-evident audit ledger**, and a **timeout→default-deny escalation contract** (LangGraph `interrupt()` waits *indefinitely* [LG-interrupts]).

---

## A. OSS guardrail frameworks

### A1. LangChain / LangGraph native (middleware + interrupts) — **highest integration fit**
- **Capability coverage**: IN + OUT + PII + partial TOOL-authz + HUMAN. `guardrails` middleware validates/filters content at execution points — explicitly for "Preventing PII leakage, Detecting and blocking prompt injection attacks, Blocking inappropriate/harmful content, Enforcing business rules and compliance" [LC-guardrails]. `PIIMiddleware` detects email/credit_card/IP/MAC/URL in **user input and agent output**, with `before_model`/`after_model` hooks and **in-flight stream redaction** [LC-pii, LC-pii-pr]. HITL middleware "checks each tool call against a configurable policy… issues an `interrupt` that halts execution" for actions like writing to a file or executing SQL [LC-hitl]. `interrupt()` pauses the graph, persists state, and waits for human approval [LG-interrupts].
- **§1 controls satisfied (cited)**: **B** input prompt-injection + PII validation [LC-guardrails, LC-pii]; **B** output/leakage validation [LC-pii]; **C** risk-calibrated human checkpoints on tool calls [LC-hitl]; **C** human approval via persisted interrupt [LG-interrupts]; **A** (partial) per-tool-call policy gating [LC-hitl].
- **License + maturity**: MIT (LangChain/LangGraph); the app's own framework; middleware + interrupt APIs are first-class and current [LC-middleware-overview].
- **OpenRouter/LangGraph/MCP fit**: native LangGraph; models via OpenAI-compatible `base_url` (OpenRouter) [OR-quickstart]; MCP tool calls flow through the graph.
- **Attach-point**: `preModelHook`/`postModelHook` (middleware), `humanEscalation`/graph interrupt (HITL), `mcpCallTool()` (tool-call policy).
- **Gaps**: no immutable audit ledger; no agent-identity/mandate registry; PII is regex-based over fewer entity types than Presidio [LC-pii]; not a Rego/Cedar deterministic policy engine; `interrupt()` has **no built-in timeout/default-deny** [LG-interrupts].

### A2. Guardrails AI (+ Hub validators)
- **Capability coverage**: IN + OUT + PII. "Validators… apply quality controls to the outputs of LLMs" with pass/fail + on-fail actions [GR-validators]. Hub includes **Detect PII** (uses Microsoft Presidio; Input+Output; anonymizing fix) [GR-detectpii], **Guardrails PII** (Presidio+GLiNER) [GR-pii], and prompt-hardening validators (e.g., "Unusual Prompt" for trickery) [GR-hub].
- **§1 controls satisfied (cited)**: **B** input validation incl. prompt trickery [GR-hub]; **B** output validation w/ corrective actions [GR-validators]; **B** PII minimisation/leakage (Presidio-backed, in+out, anonymize) [GR-detectpii].
- **License + maturity**: Apache-2.0; ~7.2k★, 80 contributors, last push 2026-07-17 (active) [GR-repo].
- **OpenRouter fit**: LiteLLM integration (100+ LLMs) + custom-LLM wrapper + OpenAI-SDK-compatible Guardrails Server → OpenRouter via `base_url` works [GR-llms, GR-customllm, GR-server].
- **Attach-point**: `preModelHook` (input validators), `postModelHook` (output/PII validators).
- **Gaps**: no tool-call authorization/disposition engine; no audit ledger; no HITL/escalation; validators are per-message, not per-action.

### A3. NVIDIA NeMo Guardrails
- **Capability coverage**: IN + OUT + retrieval + **execution** + dialog. Five rail categories: **input** (validate/sanitize user input before the LLM), **retrieval** (filter retrieved knowledge), **dialog** (constrain multi-turn flow), **execution** (around tool/action calls), **output** [NEMO-railtypes, NEMO-config].
- **§1 controls satisfied (cited)**: **B** input validation/sanitization [NEMO-railtypes]; **B** output validation [NEMO-railtypes]; **A** (partial) execution rails around tool/action calls [NEMO-railtypes]; **B** retrieval-context trust filtering → supports evidence-grounding [NEMO-railtypes].
- **License + maturity**: OSS Python (Apache-2.0 per repo); actively maintained by NVIDIA; Colang flow language [NEMO-overview].
- **OpenRouter fit**: supports non-NIM providers; microservice docs note "Only OpenAI compatible" endpoints for custom providers → OpenRouter fits (OpenAI-compatible) [NEMO-customllm, OR-quickstart].
- **Attach-point**: `preModelHook`/`postModelHook` (input/output rails); execution rails could wrap `mcpCallTool()`.
- **Gaps**: not a deterministic per-action policy engine with envelopes/identity; Colang learning curve; audit is logging-level, not tamper-evident.

### A4. Meta LlamaFirewall (PromptGuard + AlignmentCheck + CodeShield) & Llama Guard
- **Capability coverage**: IN (prompt-injection) + reasoning-audit (goal-hijack/misalignment) + code-output scanning. "Extensible AI guardrail framework… direct and indirect jailbreaking, goal hijacking, insecure coding agent outputs, malicious code injection via prompt injection" — a **policy engine orchestrating scanners** [LFW-about, LFW-arch]. **AlignmentCheck** audits the agent's chain-of-thought in real time for injection-induced misalignment [LFW-align]. Separately, **Llama Guard 3/4** classify both prompt (input) and response (output) safety [OR-LG3, OR-LG4].
- **§1 controls satisfied (cited)**: **B** input prompt-injection/jailbreak detection (PromptGuard) [LFW-workflow]; **A/S2 envelope-integrity-adjacent** runtime detection of goal-hijack/injection-induced misalignment in reasoning (AlignmentCheck) [LFW-align]; **B** output content safety (Llama Guard in/out) [OR-LG3]; **B** code-output scanning (CodeShield) [LFW-workflow].
- **License + maturity**: open-source (Meta PurpleLlama); LlamaFirewall v1.0.3 on PyPI [LFW-pypi]; paper published by Meta AI [LFW-paper].
- **OpenRouter fit — CONSTRAINT (configurable, not blocking)**: PromptGuard runs **locally** (HF cache `~/.cache/huggingface`) → provider-agnostic. **AlignmentCheck defaults to requiring `TOGETHER_API_KEY`** [LFW-howto], but the scanner exposes `model_name`, `api_base_url`, `api_key_env_var` params [LFW-src] → can be pointed at OpenRouter/another endpoint. Llama Guard 3/4 are on OpenRouter directly [OR-LG3, OR-LG4].
- **Attach-point**: `preModelHook` (PromptGuard/Llama Guard input), `postModelHook`/around reasoning (AlignmentCheck, Llama Guard output).
- **Gaps**: no tool-call authorization policy engine, no identity/mandate, no audit ledger, no HITL; AlignmentCheck is experimental + adds an LLM call (latency/cost).

### A5. Microsoft Presidio (PII)
- **Capability coverage**: PII detect + anonymize across text/images/structured data; predefined + custom recognizers (rule-based, ML, or hybrid); anonymizers (replace/redact/mask/encrypt) + deanonymizer [PRES-entities, PRES-concepts, PRES-anon].
- **§1 controls satisfied (cited)**: **B** sensitive-data minimisation/leakage (in+out) [PRES-anon]; supports **D** PII-safe logging (redact before Seq) [PRES-anon].
- **License + maturity**: **MIT License** (verified on-screen: repo LICENSE = "The MIT License (MIT)", repo metadata = MIT) [PRES-license]; Microsoft-maintained, widely adopted (underpins Guardrails AI Detect PII and LangChain PII options) [GR-detectpii].
- **OpenRouter fit**: local library, provider-agnostic (no LLM dependency for rule/NLP recognizers).
- **Attach-point**: `preModelHook`/`postModelHook` (redact PII in/out), `logEvent`→Seq (redact before audit).
- **Gaps**: PII only — no injection detection, no tool authz, no audit/monitoring.

### A6. Prompt-injection detectors: Rebuff + protectai `deberta-v3-*-prompt-injection`
- **Capability coverage**: IN prompt-injection detection. Rebuff = multi-layered self-hardening PI detector [REBUFF, REBUFF-pypi]. `protectai/deberta-v3-base-prompt-injection-v2` = fine-tuned classifier (0=clean, 1=injection), local HF model [PI-deberta, PI-deberta-v1].
- **§1 controls satisfied (cited)**: **B** input prompt-injection detection [PI-deberta, REBUFF].
- **License + maturity**: Rebuff Apache-2.0 (~1.5k★) [REBUFF-repo]; deberta models on HF (small/base variants, latency/accuracy trade-off) [PI-deberta-small].
- **OpenRouter fit**: deberta runs locally (provider-agnostic); Rebuff uses an LLM layer (OpenAI-compatible → OpenRouter).
- **Attach-point**: `preModelHook`.
- **Gaps**: injection only; no output/PII/tool/audit coverage.

---

## B. Prior agentic-guardrail implementations / reference architectures

### B1. Invariant Guardrails + MCP-scan — **closest reusable reference for the MCP tool boundary**
- **What it is**: "a comprehensive rule-based guardrailing layer for LLM or MCP-powered AI applications… deployed **between your application and your MCP servers or LLM provider**… without invasive code changes" [INV-repo]. MCP-scan `proxy` provides **live runtime guardrailing of MCP tool calls and responses** with default + custom rules at client/server/tool levels [INV-mcpscan, INV-guardrails].
- **Deployment framing for THIS app (manager ruling)**: use the **guardrail LOGIC in-process, invoked inside `mcpCallTool()`** by default (Profile §4.2 makes `mcpCallTool()` the in-process choke point; §6 forbids nodes importing infra / prefers wrapping the in-process boundaries). The **network-proxy deployment is CONDITIONAL — transport-dependent**: drop-in external proxy only if the app's MCP transport is HTTP/SSE; otherwise use the library in-process. MCP transport is unspecified in the profile, so do not assume HTTP/SSE. Rule reference covers Tool Calls, Loop Detection, Dataflow Rules, PII Detection, Jailbreaks/Prompt Injections, Moderated/Toxic Content, Secret Tokens/Credentials [INV-ref]. **Toxic-flow analysis (TFA)** is a principled method to reduce attack surface from indirect prompt injection / MCP attack vectors [INV-tfa].
- **§1 controls satisfied (cited)**: **A** tool-call guardrailing + MCP-as-governance-layer [INV-mcpscan]; **A** least-privilege/dataflow + loop detection (rate-abuse) [INV-ref]; **B** PII + jailbreak/injection + toxic content [INV-ref]; **A/S2** indirect-injection (toxic-flow) mitigation [INV-tfa]; **D** live runtime monitoring of MCP traffic [INV-mcpscan].
- **License + maturity**: OSS (`invariantlabs-ai/invariant`); MCP-scan actively developed; research-backed (Tool Poisoning, TFA) [INV-repo, INV-tfa].
- **OpenRouter/MCP fit**: designed for MCP; guardrail logic maps to the app's in-process `mcpCallTool()` choke point (see deployment framing above — proxy mode is transport-conditional); LLM-provider-agnostic.
- **Attach-point**: `mcpCallTool()` (tool-call/response guardrails), `logEvent`→Seq (monitoring).
- **Gaps**: rule DSL learning curve; not a legally tamper-evident ledger; identity/mandate not native; probabilistic content checks still need deterministic policy backing.

### B2. Policy-as-code PDP — Open Policy Agent (OPA/Rego)
- **What it is**: a general-purpose policy engine used as a **Policy Decision Point in front of every tool call**: "given this principal, this tool, these arguments, this context, is the action allowed? The agent runtime never gets to vote" [OPA-agents].
- **§1 controls satisfied (cited)**: **A** deterministic per-action authorization = SAFR Disposition Engine/Controls Repository [OPA-agents]; **A** least-privilege + exposure/rate rules encodable [OPA-agents].
- **License + maturity**: Apache-2.0; **CNCF Graduated** (2021); ~12k★, Go [OPA-cncf, OPA-repo].
- **OpenRouter/LangGraph/MCP fit**: language/provider-agnostic; runs as a service/sidecar → callable from Python `mcpCallTool()` via REST.
- **Attach-point**: `mcpCallTool()` → OPA allow/deny before side effect; decisions to `logEvent`→Seq.
- **Gaps**: Rego learning curve; not Python-native (separate process); no PII/injection detection; decision logs ≠ tamper-evident ledger.

### B3. Policy-as-code PDP — AWS Cedar
- **What it is**: open-source fine-grained authorization language/engine; AWS reference shows **least-privilege authorization in multi-agent chains**, preventing scope from silently expanding across multi-hop delegation (OWASP ASI03) [Cedar-aws]. Gateway-boundary Cedar "intercepts every tool call… evaluates against Cedar policies before the call runs" [Cedar-agentcore].
- **§1 controls satisfied (cited)**: **A** deterministic per-tool-call authorization at a gateway [Cedar-agentcore]; **A** least-privilege + delegation-scope control = maps to SAFR **mandate/identity** semantics [Cedar-aws].
- **License + maturity**: Apache-2.0; Rust core (`cedar`) + **`cedar-go`**; active (last push 2026-07-17) [Cedar-repo, Cedar-org].
- **OpenRouter/MCP fit**: provider-agnostic; embeddable at the tool boundary.
- **Attach-point**: `mcpCallTool()`.
- **Gaps**: mature bindings are Rust/Go (Python binding less mature) — integration consideration for this Python app; no detection/audit/monitoring.

### B4. OpenAI Agents SDK guardrails (reference pattern)
- **What it is**: input/output guardrails with a **tripwire** that halts execution when triggered, plus **ToolInputGuardrail/ToolOutputGuardrail** for per-tool checks [OAI-guardrails, OAI-guardrail-ref, OAI-toolguardrails].
- **§1 controls satisfied (cited)**: **B** input/output validation with hard-stop [OAI-guardrails]; **A** tool-input/output gating pattern [OAI-toolguardrails].
- **License + maturity**: OSS (`openai/openai-agents-python`), active.
- **Fit**: **different agent framework (not LangGraph)** → low direct-integration fit; value is the **design pattern** (tripwire + tool-level guardrails) transferable to LangGraph middleware / `mcpCallTool()`.
- **Gaps**: not LangGraph-native; no policy engine/identity/audit.

---

## C. Cross-cutting: OpenRouter fit (resolves the gateway constraint)

- OpenRouter exposes an **OpenAI-compatible** `/api/v1/chat/completions` endpoint; "most SDKs work by just swapping the base URL" [OR-quickstart, OR-overview]. Therefore Guardrails AI (LiteLLM/custom-LLM), NeMo Guardrails (OpenAI-compatible providers), LangChain/LangGraph (`base_url`), OpenAI Agents SDK, and Rebuff all interoperate with OpenRouter.
- **Llama Guard 3 8B / 4 12B are first-class OpenRouter models** for input+output safety classification [OR-LG3, OR-LG4] → a provider-native Group-B moderation option needing no local GPU.
- **Local/provider-agnostic detectors** (Presidio, deberta prompt-injection, LlamaFirewall PromptGuard) sidestep the gateway entirely.
- **Only real constraint found**: LlamaFirewall **AlignmentCheck** defaults to `TOGETHER_API_KEY` [LFW-howto] but is re-pointable via `api_base_url` [LFW-src] — not blocking.

## D. §1 → candidate coverage matrix (survey-level)

| §1 group | Strong OSS candidates (cited) | Residual gap (custom build) |
|---|---|---|
| **A** action-time authz/disposition, MCP-as-governance | OPA/Rego [OPA-agents]; Cedar [Cedar-aws]; Invariant/MCP-scan [INV-mcpscan]; LangGraph HITL tool-policy [LC-hitl] | Governance Envelope + integrity auth; Agent-Identity registry + machine-readable mandate; 4-way Deny/Escalate/Auto-Execute/Observe orchestration |
| **B** model I/O (injection, PII, grounding) | LangChain middleware/PIIMiddleware [LC-guardrails, LC-pii]; Guardrails AI [GR-detectpii]; NeMo [NEMO-railtypes]; Presidio [PRES-anon]; LlamaFirewall/Llama Guard [LFW-align, OR-LG3]; deberta/Rebuff [PI-deberta, REBUFF] | Evidence-grounded output validation tuned to expense-policy RAG state |
| **C** human oversight/failsafes | LangGraph HITL + interrupts [LC-hitl, LG-interrupts]; OpenAI tripwire pattern [OAI-guardrails] | **timeout→default-deny escalation contract**; kill-switch/circuit-breaker; recourse flow |
| **D** audit/monitoring/incident | Invariant runtime monitoring [INV-mcpscan]; Presidio for PII-safe logs [PRES-anon]; OPA decision logs [OPA-agents] | **immutable tamper-evident ledger** (WORM/hash-chain); black-box trace correlation; drift monitoring |

## E. Open questions / notes for P2

- Presidio license **verified on-screen = MIT** [PRES-license] (resolved).
- No DECISION-POINT stop was hit: every candidate attaches to a documented seam; the only provider constraint (AlignmentCheck→Together) is configurable.
- Stage 2 synthesis (choosing/combining these into the layer) is **NOT** started per the manager's gate.

## References (all retrieved this session)

- [OR-quickstart] OpenRouter Quickstart — https://openrouter.ai/docs/quickstart
- [OR-overview] OpenRouter API Reference (OpenAI-compatible) — https://openrouter.ai/docs/api/reference/overview
- [OR-LG3] Llama Guard 3 8B on OpenRouter — https://openrouter.ai/meta-llama/llama-guard-3-8b
- [OR-LG4] Llama Guard 4 12B on OpenRouter — https://openrouter.ai/meta-llama/llama-guard-4-12b
- [LC-guardrails] LangChain Guardrails (middleware) — https://docs.langchain.com/oss/python/langchain/guardrails
- [LC-pii] LangChain PIIMiddleware source — https://github.com/langchain-ai/langchain/blob/master/libs/langchain_v1/langchain/agents/middleware/pii.py
- [LC-pii-pr] LangChain PR #37616 in-flight PII redaction — https://github.com/langchain-ai/langchain/pull/37616
- [LC-hitl] LangChain Human-in-the-loop middleware — https://docs.langchain.com/oss/python/langchain/human-in-the-loop
- [LC-middleware-overview] LangChain Middleware overview — https://docs.langchain.com/oss/python/langchain/middleware/overview
- [LG-interrupts] LangGraph Interrupts — https://docs.langchain.com/oss/python/langgraph/interrupts
- [GR-repo] Guardrails AI repo (Apache-2.0, activity) — https://github.com/guardrails-ai/guardrails
- [GR-validators] Guardrails AI Validators concept — https://guardrailsai.com/guardrails/docs/concepts/validators
- [GR-hub] Guardrails Hub — https://guardrailsai.com/hub
- [GR-detectpii] Guardrails Detect PII (Presidio) — https://guardrailsai.com/hub/validator/guardrails/detect_pii
- [GR-pii] Guardrails PII (Presidio+GLiNER) — https://guardrailsai.com/hub/validator/guardrails/guardrails_pii
- [GR-llms] Guardrails supported LLMs (LiteLLM) — https://guardrailsai.com/guardrails/docs/how-to-guides/using_llms
- [GR-customllm] Guardrails custom LLM — https://guardrailsai.com/guardrails/docs/tutorials/using-llms/custom-llm
- [GR-server] Guardrails Server (OpenAI-compatible) — https://guardrailsai.com/guardrails/docs/guardrails-server
- [NEMO-railtypes] NeMo Guardrails rail types — https://docs.nvidia.com/nemo/guardrails/about-nemo-guardrails-library/rail-types
- [NEMO-config] NeMo Guardrails configuration — https://docs.nvidia.com/nemo/guardrails/configure-guardrails/yaml-schema/guardrails-configuration
- [NEMO-overview] NeMo Guardrails overview — https://docs.nvidia.com/nemo/guardrails/about-nemo-guardrails-library/overview
- [NEMO-customllm] NeMo custom LLM providers (OpenAI-compatible) — https://docs.nvidia.com/nemo/microservices/25.9.0/guardrails/tutorials/custom-llm-providers.html
- [LFW-about] LlamaFirewall about — https://meta-llama.github.io/PurpleLlama/LlamaFirewall/docs/documentation/about-llamafirewall
- [LFW-arch] LlamaFirewall architecture (policy engine + scanners) — https://meta-llama.github.io/PurpleLlama/LlamaFirewall/docs/documentation/llamafirewall-architecture/architecture
- [LFW-workflow] LlamaFirewall workflow/detection (PromptGuard, CodeShield) — https://meta-llama.github.io/PurpleLlama/LlamaFirewall/docs/documentation/llamafirewall-architecture/workflow-and-detection-components
- [LFW-align] AlignmentCheck (reasoning audit) — https://meta-llama.github.io/PurpleLlama/LlamaFirewall/docs/documentation/scanners/alignment-check
- [LFW-howto] LlamaFirewall how-to (TOGETHER_API_KEY) — https://meta-llama.github.io/PurpleLlama/LlamaFirewall/docs/documentation/getting-started/how-to-use-llamafirewall
- [LFW-src] AlignmentCheck scanner source (configurable api_base_url) — https://github.com/meta-llama/PurpleLlama/blob/main/LlamaFirewall/src/llamafirewall/scanners/experimental/alignmentcheck_scanner.py
- [LFW-pypi] llamafirewall v1.0.3 — https://pypi.org/project/llamafirewall/1.0.3/
- [LFW-paper] Meta AI LlamaFirewall paper — https://ai.meta.com/research/publications/llamafirewall-an-open-source-guardrail-system-for-building-secure-ai-agents/
- [PRES-entities] Presidio supported entities — https://github.com/microsoft/presidio/blob/53e9e520/docs/supported_entities.md
- [PRES-concepts] Presidio concepts (recognizers) — https://microsoft.github.io/presidio/learn_presidio/concepts/
- [PRES-anon] Presidio anonymizer — https://github.com/microsoft/presidio/tree/main/presidio-anonymizer
- [PRES-license] Presidio LICENSE (MIT) — https://github.com/microsoft/presidio/blob/main/LICENSE
- [PI-deberta] protectai deberta-v3-base-prompt-injection-v2 — https://huggingface.co/protectai/deberta-v3-base-prompt-injection-v2
- [PI-deberta-v1] protectai deberta-v3-base-prompt-injection — https://huggingface.co/protectai/deberta-v3-base-prompt-injection
- [PI-deberta-small] protectai deberta-v3-small-prompt-injection-v2 — https://huggingface.co/protectai/deberta-v3-small-prompt-injection-v2
- [REBUFF] Rebuff — https://www.rebuff.ai/
- [REBUFF-repo] Rebuff repo (Apache-2.0) — https://github.com/protectai/rebuff
- [REBUFF-pypi] Rebuff PyPI — https://pypi.org/project/rebuff/
- [INV-repo] Invariant Guardrails repo — https://github.com/invariantlabs-ai/invariant
- [INV-mcpscan] MCP-scan docs (proxy runtime guardrailing) — https://invariantlabs-ai.github.io/docs/mcp-scan/
- [INV-guardrails] MCP-scan guardrails — https://invariantlabs-ai.github.io/docs/mcp-scan/guardrails/
- [INV-ref] Invariant Guardrails rule reference — https://invariantlabs-ai.github.io/docs/mcp-scan/guardrails-reference/
- [INV-tfa] Invariant toxic-flow analysis — https://invariantlabs.ai/blog/toxic-flow-analysis
- [OPA-agents] Policy-as-Code for Agents (OPA/Rego PDP) — https://tianpan.co/blog/2026-04-25-policy-as-code-agent-permissions-opa-rego
- [OPA-cncf] OPA CNCF graduation — https://www.cncf.io/projects/open-policy-agent-opa/
- [OPA-repo] OPA repo (Apache-2.0) — https://github.com/open-policy-agent/opa
- [Cedar-aws] AWS least-privilege multi-agent Cedar — https://aws.amazon.com/blogs/security/enforce-least-privilege-authorization-in-multi-agent-ai-chains-using-cedar/
- [Cedar-agentcore] Bedrock AgentCore Policy (Cedar at gateway) — https://alatirok.com/bedrock-agentcore-policy/
- [Cedar-repo] cedar-policy/cedar (Apache-2.0) — https://github.com/cedar-policy/cedar
- [Cedar-org] cedar-policy org (cedar-go) — https://github.com/cedar-policy
- [OAI-guardrails] OpenAI Agents SDK guardrails — https://openai.github.io/openai-agents-python/guardrails/
- [OAI-guardrail-ref] OpenAI Agents SDK guardrail ref (tripwire) — https://openai.github.io/openai-agents-python/ref/guardrail/
- [OAI-toolguardrails] OpenAI Agents SDK tool guardrails — https://openai.github.io/openai-agents-python/ref/tool_guardrails/

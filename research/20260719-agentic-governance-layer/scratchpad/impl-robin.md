# Combined implementation research — Stage 1 P1 landscape survey (Robin)

**Researcher:** Robin  
**Date / freshness cut-off:** 2026-07-19  
**Scope:** Independent survey only. This does **not** choose the Stage-2 implementation architecture.  
**Grounding read first:** `docs/research/governance-layer-research.md` §1 and `docs/research/APP-INTEGRATION-PROFILE.md`.

## 0. Method, control IDs, and non-negotiable integration assumption

I searched current primary documentation, repository source, release metadata, and (where marketing claims mattered) implementation code. GitHub counts below are point-in-time indicators, not quality scores. “Covers” means the project supplies an evidenced mechanism that can implement all or part of a §1 control; it does **not** mean installing the package makes the app compliant.

### §1 control IDs used below

- **A1–A12:** trusted pre-execution envelope; origin/integrity; identity; mandate/capability; structural least privilege; per-action disposition; exposure limit; rate limit; evidence threshold; schemas/MCP hardening; layered model+action controls; gateway/hybrid wrapper.
- **B1–B6:** prompt/input attack validation; sensitive-data minimisation; grounded output validation; optional LLM-as-judge; graceful failure; explanations.
- **C1–C5:** risk-calibrated checkpoint; substantive timed escalation; oversight-effectiveness metrics; fail-closed containment; employee recourse.
- **D1–D5:** tamper-evident audit; end-to-end trace; intervention-linked monitoring; drift/fairness monitoring; incident workflow.

### Mandatory transport caveat

The intended authorization seam is the **in-process** `agents/intake/utils/mcpClient.py::mcpCallTool()` wrapper. The profile does not state how the four FastMCP servers are transported.

> **Prerequisite: confirm MCP transport of all four FastMCP servers.** External MCP gateways are **conditional / transport-dependent**. A drop-in network-proxy deployment applies only if the servers use HTTP, SSE, or Streamable HTTP. If they use stdio or in-process FastMCP, reuse relevant policy/scanning logic as an in-process library inside `mcpCallTool()` rather than claiming a drop-in network proxy.

OpenRouter is evaluated separately. Its API exposes an OpenAI-compatible Chat Completions endpoint and permits the OpenAI SDK to be pointed at OpenRouter; that does not make every OpenAI-dependent guardrail automatically compatible because models, structured-output behavior, headers, and hard-coded upstream URLs can still differ.[OR1]

---

## 1. At-a-glance candidate matrix

Legend: **Y** = direct evidenced capability; **P** = partial/building block; **—** = not supplied; **Cond.** = transport/deployment dependent.

| Candidate | Input | Output | Deterministic tool auth | PII | HITL | Audit/monitor | Best attach point | Preliminary fit |
|---|---:|---:|---:|---:|---:|---:|---|---|
| Guardrails AI + Hub | Y | Y | — | Y (validator) | — | P validation history | `preModelHook`, `postModelHook` | Optional validator composition |
| Meta Prompt Guard 2 + Llama Guard 4 / LlamaFirewall | Y | Y | — | P (privacy moderation, not entity redaction) | P (experimental alignment result) | — | model hooks | Focused defence-in-depth; licensing/model cost caveats |
| NVIDIA NeMo Guardrails 0.23 | Y | Y | P schema/allowlist; not business authorization | Y | — | P OTel | model hooks; tool wire boundary only in IORails | Strong pilot; engine/integration constraints |
| LangGraph/LangChain native middleware + interrupts | P (custom code) | P (custom code) | P (custom `wrap_tool_call`; app already has its own seam) | — | Y | P | all five seams | Keep as orchestration substrate, not policy engine |
| LangSmith + OpenEvals | P evaluator | P evaluator | — | P evaluator | — | Y tracing/evals | `logEvent`/monitoring; optional hook evaluator | Observability/eval, not enforcement or audit root |
| Presidio | — | — | — | Y text; image redactor beta | — | — | both model hooks; before outbound tool/model data | Strong focused PII component |
| OPA | — | — | Y | — | P returns escalation disposition | Y decision logs, not tamper-evident storage | `mcpCallTool()` | Strongest mature PDP building block |
| agentgateway | P guardrails | P guardrails | Y MCP JWT/CEL | P external guardrail | — | Y OTel | MCP boundary (Cond.) | Strong network-layer defence if transport fits |
| Invariant Guardrails + gateway | Y | Y | Y contextual/sequence rules | Y detectors | — | P trace | `mcpCallTool()` library or proxy (Cond.) | Valuable pattern; maintenance/product-transition risk |
| Microsoft Agent Governance Toolkit (AGT) | P | P | Y wrapper/policy | P regex/content features | Y approval protocol | P hash-chain/trace | `mcpCallTool()` facade; `humanEscalation` | Broad public-preview reference; validate before use |
| Protect AI LLM Guard | Y | Y | — | Y | — | — | model hooks | **Skip new adoption: archived/unmaintained** |

No candidate covers Groups A–D alone. Model scanners do not authenticate or authorize an action; policy engines do not detect multimodal injection or PII; trace stores are not automatically tamper-evident governance logs.

---

## 2. OSS guardrail frameworks

### 2.1 Guardrails AI and Hub validators

**Evidence-based capabilities**

- Core Guardrails composes validators into input/output Guards and supports pass/fail behavior plus configured failure actions. The project also supports structured output generation/validation.[GR1][GR2]
- Hub `DetectPII` uses Presidio and can reject or programmatically anonymize text; it is marked for both input and output.[GR3]
- Hub provides prompt/jailbreak detectors and provenance validators. `Provenance LLM` compares generated text against supplied contexts/query results; it is probabilistic and requires runtime metadata.[GR4][GR5]
- A Guard can run validation independently via `guard.validate`, avoiding provider coupling. Calling an LLM through Guardrails is more provider-specific, but the independent validation form fits existing hooks.

**§1 mapping**

- **B1:** prompt-injection/jailbreak validators at `preModelHook` (quality and license are validator-specific).
- **B2:** `DetectPII` or newer PII validators at both hooks. This is Presidio underneath, so direct Presidio may be simpler.
- **B3:** provenance/structured-output validators at `postModelHook`; requires app-supplied RAG context and deterministic claim-state checks alongside it.
- **B5:** on-fail actions provide exception, filter, fix, refrain, or re-ask behavior; the app must map these to its structured failure/escalation contract.
- **A10/A11 (partial):** Pydantic/JSON shape validation and a complementary model-I/O layer. It does **not** authorize MCP execution.
- **D2 (weak):** validation history is useful diagnostic evidence, not a complete or tamper-evident action trace.

**App / provider fit**

- **Python:** native. **LangGraph:** call `validate` in `preModelHook`/`postModelHook`; no graph rewrite needed.
- **OpenRouter:** provider-independent when only `guard.validate`/`parse` is used. Do not assume every LLM-backed Hub validator can use OpenRouter; inspect each validator’s client/model parameters.
- **MCP:** no native authoritative MCP identity/mandate/disposition control. It can validate serialized args inside `mcpCallTool()` but must not be the authorization decision point.

**Gaps / risks**

- Hub packages have separate dependencies, licenses, maintainers, model behavior, and activity. “Available in Hub” is not a maturity guarantee.
- PII is text-oriented; use Presidio’s image component or a multimodal guard for receipts.
- No A1–A9, C1–C5, D1/D3–D5 control plane.

**License / maturity:** core Apache-2.0; active, ~7.2k stars; v0.10.2 released 2026-06-04.[GR6][GR7] Individual validators must be separately checked (e.g. `DetectPII` is Apache-2.0).[GR3]

**Fit verdict:** useful optional composition layer, especially for schema/provenance validators; not a governance backbone. Direct use of selected underlying libraries may reduce indirection.

---

### 2.2 Meta Llama Prompt Guard 2, Llama Guard 4, and LlamaFirewall

**Evidence-based capabilities**

- Prompt Guard 2 (22M/86M) is a local Transformers classifier for jailbreak and explicit prompt-injection patterns. Both have a 512-token window; long input must be segmented. The 86M model is multilingual; the model card warns about adaptive attacks and application-specific distributions.[META1]
- Llama Guard 4 is a 12B multimodal input/output safety classifier for text plus multiple images. It includes privacy and non-violent financial-crime categories, but it is broad content moderation, not PII entity detection or claim-policy validation.[META2]
- Published Llama Guard 4 aggregate output-filtering metrics are not near-perfect: English recall 69% / FPR 11%, single-image recall 41% / FPR 9%; the card also warns that the guard itself may be prompt-injected.[META2]
- LlamaFirewall (MIT code) composes PromptGuard, CodeShield, regex/custom checks, and an **experimental** AlignmentCheck over an agent trace.[META3][META4]
- AlignmentCheck returns `HUMAN_IN_THE_LOOP_REQUIRED` on detected misalignment, but requires a full trace. Current subclass construction defaults its judge client to Together.ai and does not expose the base URL/model arguments advertised in its docstring without subclassing/modification.[META5][META6]

**§1 mapping**

- **B1:** Prompt Guard 2 at `preModelHook`; scan OCR/retrieved text in segments, not only the user message.
- **B2 (partial):** Llama Guard 4’s privacy category can flag unsafe disclosure, but Presidio is needed for deterministic entity-level minimization/redaction.
- **A9/B4/C1 (experimental partial):** AlignmentCheck can flag action/goal mismatch and request human review when a trusted trace is available; it cannot replace deterministic mandate/evidence policies.
- **A11:** clearly complementary model-layer defense.
- **B3/B6:** not supplied; safety classification is not evidence grounding or a decision explanation.

**App / provider fit**

- **Python/LangGraph:** local Transformers models or LlamaFirewall calls fit the model hooks. Receipt images make Llama Guard 4 relevant at the intake hook, subject to benchmark validation on actual receipt distribution.
- **OpenRouter:** local Prompt Guard/Llama Guard inference is independent of OpenRouter. LlamaFirewall’s experimental AlignmentCheck is **not** OpenRouter drop-in in current source; it defaults to Together.ai and needs code/subclass changes.[META6]
- **MCP:** no identity, capability, business-policy, or execution authorization.

**Gaps / risks**

- Prompt Guard’s 512-token segmentation loses some cross-chunk context; tune thresholds and test adaptive/receipt-specific attacks.
- Llama Guard 4 is large and general-purpose; its published vision recall argues against treating it as a sole blocking control.
- LlamaFirewall code is MIT, but the **model weights are not under MIT/Apache**. Prompt Guard 2 and Llama Guard 4 use the Llama 4 Community License plus acceptable-use policy, including attribution/commercial terms; record this as source-available/community-licensed rather than OSI-open-source.[META7][META8]

**License / maturity:** PurpleLlama active, ~4.3k stars, pushed 2026-07-01; no GitHub releases. LlamaFirewall code MIT; weights under Meta community licenses.[META9]

**Fit verdict:** Prompt Guard 2 86M is a credible, focused pilot for B1. Llama Guard 4 is an optional multimodal safety layer, not a PII or action-policy engine. AlignmentCheck is reference/pilot quality for this app.

---

### 2.3 NVIDIA NeMo Guardrails 0.23

**Evidence-based capabilities**

- NeMo defines input, retrieval, dialog, execution/tool, and output rails. Input can validate/sanitize; output can filter/edit/block; retrieval rails guard RAG; execution rails validate tool inputs/results.[NEMO1]
- v0.23 added the experimental opt-in **IORails** tool-calling rails. They fail closed and locally validate model-emitted tool names/arguments against declared JSON Schema and validate structural linkage of tool results.[NEMO2][NEMO3]
- Important limits: IORails tool rails only support OpenAI Chat Completions shape (`openai`/`nim` engines), do not execute tools, and validate tool results structurally—not content safety, response schema, or server provenance.[NEMO2]
- The LangChain agent middleware checks message `content` before/after each model call but explicitly does **not** inspect tool-call arguments, and tool results bypass input rails.[NEMO4]
- NeMo’s built-in OpenAI engine explicitly documents `parameters.base_url`/`api_key` for OpenAI-compatible providers **including OpenRouter**.[NEMO5]
- Multimodal input/output safety is available in LLMRails, but not IORails; multimodal configurations route to LLMRails.[NEMO6]

**§1 mapping**

- **B1/B2:** configurable injection, content-safety, PII/masking, and custom input/retrieval/output rails.
- **B3/B4:** RAG/fact-checking and custom/LLM rails can test groundedness; still probabilistic and needs deterministic field/evidence checks.
- **B5:** blocked/modified/passed results and fail-closed IORails errors support structured failure handling.
- **A10:** IORails allowlist + JSON Schema checking of model-emitted calls; it is **not** identity/mandate/ownership/status-transition authorization.
- **A11:** broad complementary model layer.
- **D2 (partial):** OpenTelemetry gives diagnostic traces. Content capture is opt-in and must remain PII-safe; it is not D1.

**App / provider fit**

- **Python:** native and active. **OpenRouter:** explicitly supported through the OpenAI-compatible engine.[NEMO5]
- **LangGraph:** for this custom graph, wrap individual LLM nodes or call the checks API in existing model hooks. Do not infer that the LangChain middleware secures `mcpCallTool()`; its own docs disclaim argument/result inspection.[NEMO4]
- **MCP:** IORails validates OpenAI-format tool calls between model and app, not MCP execution at the trusted choke point. The app still needs `mcpCallTool()` authorization.
- **Receipt VLM:** multimodal LLMRails and IORails tool rails cannot be assumed to operate together; validate chosen engine/configuration explicitly.[NEMO6]

**Gaps / risks**

- No A1–A9 identity/mandate/disposition, risk-calibrated HITL contract, employee recourse, or D1 audit.
- Colang/configuration and extra model calls add complexity, latency, and failure modes.
- The tool-calling feature is new/experimental even though v0.23 is released.

**License / maturity:** Apache-2.0 library licensing (with third-party notices); active, ~6.7k stars; v0.23.0 released 2026-07-01.[NEMO3][NEMO7]

**Fit verdict:** strongest broad OSS model-I/O framework surveyed and explicit OpenRouter fit. Pilot it for B-controls only; do not use it as the action authorization authority.

---

### 2.4 LangGraph/LangChain native primitives; LangSmith and OpenEvals

#### LangGraph/LangChain

**Evidence-based capabilities**

- Current middleware has `before_model`, `after_model`, `wrap_model_call`, and `wrap_tool_call`; wrap hooks can short-circuit, transform, retry, and update state.[LG1]
- `interrupt()` persists graph state via a checkpointer and waits for external input; production needs a durable checkpointer and stable `thread_id`. Nodes restart from the beginning on resume, so side effects before an interrupt must be idempotent or moved after it.[LG2]
- The existing app already exposes equivalent `preModelHook`/`postModelHook`, graph gates, and `humanEscalation`. These are the least invasive attach points.

**§1 mapping**

- **C1/C2:** interrupts are the durable pause/resume mechanism for approval/review/edit. The app must add approver identity, allowed actions, timeout, action binding, and fail-closed expiry.
- **B1–B6:** middleware/hooks can host validators, but LangGraph supplies the seam—not the detector or policy.
- **A6/A10/C4:** custom wrapper code can short-circuit a tool/model call, validate schema, and route to human. The app-specific `mcpCallTool()` remains the authoritative boundary.
- **D2:** checkpoint/state/event tracing is useful reconstruction input, not an immutable audit record.

**OpenRouter / MCP fit:** provider-agnostic orchestration. No native OpenRouter dependency is required if the app’s current model adapter works. No automatic MCP business authorization.

**License / maturity:** MIT, ~37.6k stars, v1.2.9 released 2026-07-10.[LG3][LG4]

**Fit verdict:** retain and deepen native seams; it is orchestration/HITL infrastructure, not the policy or guardrail implementation.

#### LangSmith / OpenEvals

- LangSmith provides traces, dashboards, alerts, rules/webhooks, online evaluation, and feedback workflows.[LS1][LS2]
- The client SDK is MIT and active, but the LangSmith platform is a hosted/commercial product with cloud/hybrid/self-hosted offerings and plan-dependent retention/limits; do not label the platform itself an OSS audit system merely because the SDK is open.[LS3][LS4]
- OpenEvals (MIT) provides exact/JSON/LLM judges, prompt-injection, PII-leakage, groundedness, fairness, multimodal, and trajectory/tool-selection evaluators.[OE1][OE2]

**§1 mapping:** **B3/B4**, **D2–D4**, and reviewer feedback metrics (**C3**) when configured. Online evaluators are monitoring signals unless application code consumes their verdict before release/execution. Neither LangSmith nor OpenEvals supplies D1 tamper evidence or A1–A9 authorization.

**Fit:** tracing is provider-agnostic when manually instrumented, but sending receipt/employee/claim traces introduces another data processor and retention surface. The app already uses Seq; duplication needs a purpose. OpenEvals’ quickstart defaults to OpenAI, but it accepts model/client customization; OpenRouter compatibility must be proven with the selected judge model rather than assumed.

**Maturity:** LangSmith SDK MIT, ~973 stars and active; OpenEvals MIT, ~1.1k stars, Python 0.2.0 published in the 2026-04 release.[LS3][OE2]

**Fit verdict:** useful optional evaluation/observability, not runtime authority or governance audit root.

---

### 2.5 Microsoft/Data Privacy Stack Presidio

**Evidence-based capabilities**

- Presidio detects and anonymizes PII in text with predefined/custom recognizers using NER, regex, rules, checksums, context, remote detectors, and multiple languages.[P1][P2]
- It supports Python, containers, and Kubernetes and can add recognizers for app-specific employee IDs, claim IDs, vendor/payment fields, and institutional formats.[P2]
- Presidio Image Redactor uses OCR to redact text PII from standard/DICOM images, but its own documentation says the image package is **beta and not production ready**.[P3]
- The project expressly says automated detection cannot guarantee all sensitive information is found and additional protections are required.[P1]

**§1 mapping**

- **B2:** detect/minimize/redact model input and output; use allowlists/context so policy-required claim fields are not indiscriminately removed.
- **A10/B1 (partial):** scan OCR/retrieved/tool payload text before sending to OpenRouter or external email. It does not detect semantic prompt injection.
- **D1/D2:** only as a preprocessing step so logs contain redacted metadata/references; it supplies no logging itself.

**App / provider fit:** pure Python and provider-independent. Attach to both model hooks and outbound email/tool payload construction. For receipts, OCR redaction before VLM could destroy evidence needed for extraction; prefer data-minimizing crops/fields, explicit entity policy, and store the original only in a controlled evidence system. Pilot the beta image path separately.

**Gaps:** no authorization, HITL, grounding, explanation, tracing, or audit. False negatives/positives require domain evaluation.

**License / maturity:** MIT; community-governed after transition from Microsoft; active, ~10.1k stars; v2.2.363 released 2026-06-28.[P4][P5][P6]

**Fit verdict:** strongest focused PII component. Text Analyzer/Anonymizer is adoptable after Singapore/app-specific evaluation; image redactor remains pilot status.

---

### 2.6 Protect AI LLM Guard — explicit skip

LLM Guard has useful input/output scanners for injection, anonymization/de-anonymization, secrets, toxicity, JSON, relevance, and factual consistency. Its PII scanner itself uses Presidio.[LLMG1][LLMG2] However, the repository is archived and its README states the code and associated Hugging Face models are no longer actively developed or maintained.[LLMG1][LLMG3]

- **Potential mapping if maintaining a fork:** B1–B3 and B5 at model hooks only.
- **Why skip new adoption:** unmaintained security classifiers are a poor dependency for an adversarial control surface; no tool authorization/HITL/audit; Presidio and Prompt Guard/NeMo provide maintained alternatives.
- **License/maturity:** MIT, ~3.2k stars, archived in July 2026.[LLMG3]

---

## 3. Agentic runtime-policy / reference implementations

### 3.1 Open Policy Agent (OPA)

**Evidence-based capabilities**

- OPA is a lightweight general-purpose policy decision point deployable as sidecar, daemon, or library. It evaluates arbitrary structured JSON input and can return arbitrary structured decisions—not just booleans.[OPA1]
- Signed bundles let policy/data update without application redeploy; OPA verifies signatures before activation and retains the last valid bundle on failure.[OPA2]
- Decision logs include decision/trace IDs, input, result, policy path, bundle revision, metrics, and rule annotations. A log-mask policy can erase or replace sensitive fields before export.[OPA3]

**§1 mapping**

- **A1/A2:** the wrapper constructs a trusted envelope from graph/auth/tool state and submits it to OPA. OPA does not attest that input’s origin; the wrapper/service identity must do that.
- **A3–A10:** policies can decide on authenticated principal/agent, mandate, tool/server, claim ownership, allowed status transition, amount/currency, evidence score, counters, schema-validation result, and argument fields.
- **A6:** return a structured object such as `{disposition, allow, reason_codes, obligations, policy_revision}` mapping to Deny/Escalate/Auto-Execute/Observe.
- **A7/A8:** OPA can evaluate supplied exposure/counter state, but it is not an atomic metering database; the app/gateway must maintain counters and reserve/commit usage safely.
- **A12/C1/C4:** natural PDP inside the gateway/hybrid `mcpCallTool()` wrapper; missing/undefined/error must map to deny/escalate in app code.
- **D2:** decision logs provide strong policy-decision evidence and revision IDs.
- **D1:** **not by itself**. Send redacted OPA decision records plus tool outcome to an independently append-only/tamper-evident store; OPA’s log delivery is not WORM/ledger assurance.

**App / provider fit**

- **Python:** call local OPA REST sidecar or another embedded/Wasm option after measuring complexity. **LangGraph/OpenRouter:** model-provider agnostic.
- **MCP:** put the call immediately before actual invocation in `mcpCallTool()` so there is no alternate execution path. Log requested decision, then separately log execution outcome/error.
- **Seq:** forward masked decision metadata/correlation ID and anchor to external immutable storage.

**Gaps / risks:** no injection/PII/grounding/HITL UI; no built-in action executor; policy correctness, input schema, bundle availability, and fail-closed client behavior remain application responsibilities.

**License / maturity:** Apache-2.0, CNCF-mature ecosystem, ~12k stars; v1.18.2 released 2026-07-02.[OPA4][OPA5]

**Fit verdict:** most mature reusable PDP surveyed for Group A. It is a component of the wrapper, not the wrapper or full governance layer.

---

### 3.2 agentgateway

**Evidence-based capabilities**

- Linux Foundation agentgateway supports MCP federation and stdio/HTTP/SSE/Streamable HTTP targets, OAuth, JWT/API-key authentication, CEL RBAC, rate limiting, TLS, and OpenTelemetry.[AGW1]
- Released v1.3.1 includes MCP authorization rules (`allow`/`deny`/`require`) over JWT identity, tool name/target, request headers, and at call time tool arguments. Unauthorized tools can be filtered from discovery and denied when called.[AGW2][AGW3]
- The release also includes external `mcpGuardrails` request/response policy hooks with configurable failure behavior; this is a useful extension point but requires a compatible policy service/adaptor.[AGW4]

**§1 mapping**

- **A3/A5:** authenticate caller and enforce per-tool/resource least privilege.
- **A8/A10:** rate limiting, tool filtering, CEL checks over arguments/headers, TLS.
- **A12:** network MCP enforcement layer if transport/topology fits.
- **A1/A4/A6/A7/A9 (partial):** CEL/external hook can consume trusted headers/arguments, but app graph state, evidence, current claim owner, and human escalation are not automatically available. Avoid trusting agent-supplied headers.
- **D2/D3:** OTel metrics/logs/traces and tool-call counters; not D1.

**App / provider / transport fit**

- **OpenRouter:** irrelevant if used only for MCP. Do not insert its LLM proxy into the current model path without a separate OpenRouter interoperability test.
- **MCP:** **conditional / transport-dependent per program ruling.** Network-proxy use is drop-in only for HTTP/SSE/Streamable HTTP. For stdio/in-process FastMCP, reuse authorization logic in `mcpCallTool()` rather than claiming drop-in fit.
- Even with a gateway, keep the in-process OPA/business-policy gate because agentgateway cannot infer all trusted LangGraph claim/evidence state unless explicitly conveyed through an authenticated channel.

**Gaps:** no model injection/PII/grounding, native LangGraph HITL, recourse, tamper-evident audit, or business-state source of truth. CEL policy distribution/governance needs design.

**License / maturity:** Apache-2.0, active Linux Foundation project, ~3.9k stars; v1.3.1 released 2026-06-22.[AGW5][AGW6]

**Fit verdict:** strong defence-in-depth candidate at an actual network MCP boundary; transport confirmation is prerequisite, and it does not replace the trusted application wrapper.

---

### 3.3 Invariant Guardrails / Invariant Gateway / former MCP-Scan

**Evidence-based capabilities**

- Invariant’s Python policy language matches messages, tool calls/outputs, and flows across a trace, enabling contextual sequence policies such as preventing external email after untrusted tool output; local `LocalPolicy` evaluation is available.[INV1]
- Its gateway historically intercepted LLM and MCP traffic and supported stdio, SSE, and Streamable HTTP. It has OpenAI/Anthropic/Gemini routes and trace storage.[INV2]
- The old `mcp-scan` repository now redirects to Snyk `agent-scan`, whose current scope is discovery and **preflight scanning** of agents, MCP servers, and skills. Its README warns CLI output is experimental and that scanning stdio configs executes their commands.[INV3]

**§1 mapping**

- **B1/B2:** prompt-injection, PII, secrets, and moderation detectors over trace elements.
- **A5/A6/A9/A10:** contextual allow/raise rules over tool names, arguments, outputs, and prior trace; especially valuable as a reference for toxic-flow policies.
- **D2/D3 (partial):** trace analysis/monitoring. No D1 guarantee.
- **A3/A4/C1–C5:** no complete identity/mandate/action-bound approval contract in the surveyed runtime.

**App / provider fit**

- **In-process path:** translate trusted graph/tool events to Invariant’s trace form and run `LocalPolicy` inside `mcpCallTool()`. This avoids transport dependence but needs an adapter and benchmark.
- **Proxy path:** conditional / transport-dependent as above.
- **OpenRouter:** the old LLM gateway’s OpenAI route is hard-coded to `api.openai.com`, so it is **not** an OpenRouter drop-in. The local policy library is model-provider independent.[INV2][INV4]

**Gaps / maturity risk**

- `invariant` is Apache-2.0 and not archived, but has no GitHub releases and was last pushed 2026-01-12 (~435 stars). `invariant-gateway` was last pushed 2025-11-06 (~77 stars). Runtime continuity after the MCP-Scan→Snyk Agent Scan transition is unclear.[INV5][INV6]
- Snyk Agent Scan is active and Apache-2.0, but it is not the old runtime action firewall; do not credit a static scanner with runtime enforcement.[INV3]

**Fit verdict:** excellent reusable policy-language/reference pattern for cross-step information-flow controls; pilot only unless maintenance and ownership roadmap are confirmed.

---

### 3.4 Microsoft Agent Governance Toolkit (AGT)

**Evidence-based capabilities**

- AGT is MIT, explicitly **Public Preview**, and presents action policy, identity, approval, MCP, and audit components. Its `govern()` wrapper evaluates a callable before execution and supports allow/deny/require-approval paths.[AGT1][AGT2]
- Current source includes action-bound approvals with digest, policy/chain version, expiry, fail-closed validation, and webhook/handler adapters.[AGT3]
- The toolkit’s own limitations say it does not govern reasoning, indirect injection, or sequences of individually allowed actions; audit logs record attempts rather than verified outcomes; no-policy/permissive initialization can allow everything.[AGT4]

**§1 mapping**

- **A3–A10/A12:** broad reference design for identity + policy-gated callable. `govern()` requires an app-specific facade: its generic context builder maps the first positional argument to `action.type` and wraps scalar kwargs as `{value: ...}`, which is not automatically the app’s canonical MCP envelope.[AGT2]
- **A6/C1/C2/C4:** allow/deny/require-approval plus action-bound approval protocol is close to §1; integrate with LangGraph’s durable `humanEscalation`, not a blocking in-process callback alone.
- **D1/D2:** source implements an in-memory hash/Merkle chain and optional sink, but do **not** treat it as the final audit root. In `govern()`, `AuditLog()` is created without an external sink; the wrapper logs policy evaluation before calling the wrapped function, so external outcome/error is not captured there. Several action assurance fields are explicitly outside the v1.0 canonical hash.[AGT2][AGT5]
- **B-controls:** AGT itself states it is action—not reasoning/model-safety—governance; pair with a dedicated model layer.[AGT4]

**Implementation-quality findings relevant to adoption**

1. The quickstart Python expression engine says a proper expression parser would be used “in production”; unsupported expressions return false rather than necessarily raising, which is hazardous with an allow default.[AGT6]
2. The LangGraph adapter defines `before_tool_call`, but graph wrapping only wraps node callables with `before_node_execution`; surveyed source contains no automatic call from the wrapper to `before_tool_call`. Its header also lists HITL governance, streaming, async durable checkpointers, and subgraphs as out of scope.[AGT7]
3. Application middleware shares a process/trust boundary with the agent; AGT’s security docs recommend external isolation for stronger enforcement.[AGT1][AGT4]

**App / provider fit:** action wrapper is OpenRouter-independent. Python/LangGraph integration exists but is public-preview and needs direct tests against this app/version. MCP wrapper mapping must be explicit. Do not adopt its audit chain as the only evidence store.

**License / maturity:** MIT; created 2026-03, ~4.9k stars; v4.1.0 released 2026-06-09; very active but young and explicitly pre-GA/public preview.[AGT8][AGT9]

**Fit verdict:** valuable broad reference and possible isolated pilot—especially action-bound approval objects—but not a sole production trust/audit root without resolving the source-level gaps above.

---

## 4. Control-coverage synthesis by §1 group (survey result, not Stage-2 design)

| §1 group | Strongest evidenced reusable mechanisms | Residual control work in this app |
|---|---|---|
| **A — action-time authorization** | OPA structured PDP; agentgateway JWT/CEL at network MCP boundary (conditional); AGT action-bound approval reference; Invariant sequence-policy reference; NeMo IORails schema validation only | Build trusted envelope in `mcpCallTool()`; authenticate origin; no bypass; atomic counters/exposure; tool outcome logging; canonical disposition contract |
| **B — model I/O** | NeMo; Prompt Guard 2; optional Llama Guard 4; Presidio; selected Guardrails Hub validators; OpenEvals for judge/grounding | Receipt/domain benchmark; OpenRouter selected-model tests; deterministic claim-state/RAG evidence validation; calibrated failure messages/explanations |
| **C — human oversight** | LangGraph durable interrupts/checkpointing; AGT action-bound approval schema/reference | Persisted role/identity, deadline, action digest, modify/deny/approve authority, one-time consumption, fail-closed timeout, reviewer metrics, recourse UI |
| **D — audit/monitoring** | OPA decision IDs/bundle revisions/masked logs; LangGraph/Seq correlation; agentgateway OTel; optional LangSmith/OpenEvals | External append-only/tamper-evident anchoring; tool outcomes; PII-safe evidence references; alert→deny/escalate/halt wiring; incident and drift/fairness processes |

### Findings that should survive cross-review

1. **Do not collapse model safety and action authorization.** Every surveyed model guard can miss attacks; none establishes mandate or claim ownership.
2. **Schema validation is not authorization.** NeMo IORails/Guardrails/Pydantic can prove shape, not entitlement or business validity.
3. **Tracing is not D1 audit.** OPA logs, OTel, LangSmith, Seq, and AGT in-memory chains need an externally controlled append-only/tamper-evident record and PII-safe evidence design.
4. **Use probabilistic scores as signals/obligations, not sole authority for irreversible actions.** Route uncertainty to deterministic policy or human review.
5. **OpenRouter must be tested per integration.** NeMo explicitly names it; local Meta/Presidio/OPA are independent; Invariant Gateway and LlamaFirewall AlignmentCheck contain provider-specific defaults that defeat a blanket compatibility claim.
6. **The MCP transport prerequisite remains open.** It controls whether agentgateway/other network proxies are deployable or merely sources of reusable logic.

---

## 5. Primary-source references

### OpenRouter
- **[OR1]** OpenRouter, [Quickstart — API and OpenAI SDK compatibility](https://openrouter.ai/docs/quickstart).

### Guardrails AI
- **[GR1]** Guardrails AI, [repository README — input/output Guards, Hub, structured data](https://github.com/guardrails-ai/guardrails/blob/1f1e5af5067bab8a6638ca06a2bbe4d063db634a/README.md).
- **[GR2]** Guardrails AI, [Validators concepts](https://www.guardrailsai.com/docs/concepts/validators).
- **[GR3]** Guardrails AI, [`detect_pii` README and license](https://github.com/guardrails-ai/detect_pii).
- **[GR4]** Guardrails Hub, [Prompt Injection Detector](https://guardrailsai.com/hub/validator/sainatha/prompt_injection_detector).
- **[GR5]** Guardrails Hub, [Provenance LLM](https://guardrailsai.com/hub/validator/guardrails/provenance_llm).
- **[GR6]** GitHub API, [`guardrails-ai/guardrails` repository metadata](https://api.github.com/repos/guardrails-ai/guardrails).
- **[GR7]** Guardrails AI, [v0.10.2 release](https://github.com/guardrails-ai/guardrails/releases/tag/v0.10.2).

### Meta
- **[META1]** Meta, [Llama Prompt Guard 2 86M model card](https://github.com/meta-llama/PurpleLlama/blob/b71c6350a2acf2fb62c2328a734cbf440ecac386/Llama-Prompt-Guard-2/86M/MODEL_CARD.md).
- **[META2]** Meta, [Llama Guard 4 model card, metrics and limitations](https://github.com/meta-llama/PurpleLlama/blob/b71c6350a2acf2fb62c2328a734cbf440ecac386/Llama-Guard4/12B/MODEL_CARD.md).
- **[META3]** Meta, [LlamaFirewall README](https://github.com/meta-llama/PurpleLlama/blob/b71c6350a2acf2fb62c2328a734cbf440ecac386/LlamaFirewall/README.md).
- **[META4]** Meta, [LlamaFirewall MIT license](https://github.com/meta-llama/PurpleLlama/blob/b71c6350a2acf2fb62c2328a734cbf440ecac386/LlamaFirewall/LICENSE).
- **[META5]** Meta, [AlignmentCheck source](https://github.com/meta-llama/PurpleLlama/blob/b71c6350a2acf2fb62c2328a734cbf440ecac386/LlamaFirewall/src/llamafirewall/scanners/experimental/alignmentcheck_scanner.py).
- **[META6]** Meta, [CustomCheckScanner provider defaults](https://github.com/meta-llama/PurpleLlama/blob/b71c6350a2acf2fb62c2328a734cbf440ecac386/LlamaFirewall/src/llamafirewall/scanners/custom_check_scanner.py).
- **[META7]** Meta, [Prompt Guard 2 licensing statement](https://github.com/meta-llama/PurpleLlama/blob/b71c6350a2acf2fb62c2328a734cbf440ecac386/Llama-Prompt-Guard-2/README.md#license).
- **[META8]** Meta, [Llama Guard 4 Community License](https://github.com/meta-llama/PurpleLlama/blob/b71c6350a2acf2fb62c2328a734cbf440ecac386/Llama-Guard4/12B/LICENSE).
- **[META9]** GitHub API, [PurpleLlama metadata](https://api.github.com/repos/meta-llama/PurpleLlama).

### NVIDIA NeMo Guardrails
- **[NEMO1]** NVIDIA, [Guardrail types](https://docs.nvidia.com/nemo/guardrails/latest/about/rail-types.html).
- **[NEMO2]** NVIDIA, [IORails tool calling](https://github.com/NVIDIA-NeMo/Guardrails/blob/v0.23.0/docs/configure-rails/guardrail-catalog/tool-calling.mdx).
- **[NEMO3]** NVIDIA, [v0.23.0 release](https://github.com/NVIDIA-NeMo/Guardrails/releases/tag/v0.23.0).
- **[NEMO4]** NVIDIA, [LangChain agent middleware limitations](https://github.com/NVIDIA-NeMo/Guardrails/blob/v0.23.0/docs/integration/langchain/agent-middleware.mdx#known-limitations).
- **[NEMO5]** NVIDIA, [Supported LLMs — OpenRouter through the OpenAI-compatible engine](https://docs.nvidia.com/nemo/guardrails/latest/about/supported-llms.html).
- **[NEMO6]** NVIDIA, [engine feature support — multimodal LLMRails vs IORails](https://github.com/NVIDIA-NeMo/Guardrails/blob/v0.23.0/docs/reference/engine-feature-support.mdx#feature-matrix).
- **[NEMO7]** GitHub API, [NeMo Guardrails metadata](https://api.github.com/repos/NVIDIA-NeMo/Guardrails).

### LangGraph, LangSmith, OpenEvals
- **[LG1]** LangChain, [Custom middleware hooks](https://docs.langchain.com/oss/python/langchain/middleware/custom).
- **[LG2]** LangGraph, [Interrupts, durable checkpointing, and idempotency rules](https://docs.langchain.com/oss/python/langgraph/interrupts).
- **[LG3]** GitHub API, [LangGraph metadata](https://api.github.com/repos/langchain-ai/langgraph).
- **[LG4]** LangGraph, [v1.2.9 release](https://github.com/langchain-ai/langgraph/releases/tag/1.2.9).
- **[LS1]** LangSmith, [Observability](https://docs.langchain.com/langsmith/observability).
- **[LS2]** LangSmith, [Evaluation](https://docs.langchain.com/langsmith/evaluation).
- **[LS3]** GitHub API, [LangSmith SDK metadata and MIT license](https://api.github.com/repos/langchain-ai/langsmith-sdk).
- **[LS4]** LangSmith, [administration, retention, plan, and self-hosted details](https://docs.langchain.com/langsmith/administration-overview).
- **[OE1]** OpenEvals, [README — evaluator families](https://github.com/langchain-ai/openevals/blob/d4a096b76c216feca6252cbdc277cf75c2b29a11/README.md).
- **[OE2]** GitHub API, [OpenEvals metadata](https://api.github.com/repos/langchain-ai/openevals).

### Presidio
- **[P1]** Presidio, [README — capabilities and no-guarantee warning](https://github.com/data-privacy-stack/presidio/blob/517d13eee659794ed3a55d188752d014be574c2a/README.MD).
- **[P2]** Presidio, [adding custom/local/remote recognizers](https://github.com/data-privacy-stack/presidio/blob/517d13eee659794ed3a55d188752d014be574c2a/docs/analyzer/adding_recognizers.md).
- **[P3]** Presidio, [Image Redactor beta warning](https://github.com/data-privacy-stack/presidio/blob/517d13eee659794ed3a55d188752d014be574c2a/docs/image-redactor/index.md).
- **[P4]** Presidio, [community-ownership transition](https://github.com/data-privacy-stack/presidio/blob/517d13eee659794ed3a55d188752d014be574c2a/docs/project_transition.md).
- **[P5]** GitHub API, [Presidio metadata](https://api.github.com/repos/data-privacy-stack/presidio).
- **[P6]** Presidio, [v2.2.363 release](https://github.com/data-privacy-stack/presidio/releases/tag/2.2.363).

### OPA
- **[OPA1]** OPA, [philosophy, deployment modes, arbitrary structured input/output](https://www.openpolicyagent.org/docs/latest/philosophy/).
- **[OPA2]** OPA, [bundles, live updates, persistence, and signatures](https://www.openpolicyagent.org/docs/latest/management-bundles/).
- **[OPA3]** OPA, [decision logs and sensitive-data masking](https://www.openpolicyagent.org/docs/latest/management-decision-logs/).
- **[OPA4]** GitHub API, [OPA metadata](https://api.github.com/repos/open-policy-agent/opa).
- **[OPA5]** OPA, [v1.18.2 release](https://github.com/open-policy-agent/opa/releases/tag/v1.18.2).

### agentgateway
- **[AGW1]** agentgateway, [v1.3.1 README — MCP transports/security/observability](https://github.com/agentgateway/agentgateway/blob/v1.3.1/README.md).
- **[AGW2]** agentgateway, [v1.3.1 authorization example](https://github.com/agentgateway/agentgateway/blob/v1.3.1/examples/authorization/README.md).
- **[AGW3]** agentgateway, [v1.3.1 MCP authorization tests including arguments/headers](https://github.com/agentgateway/agentgateway/blob/v1.3.1/crates/agentgateway/src/http/authorization_tests.rs).
- **[AGW4]** agentgateway, [v1.3.1 external MCP guardrail hook source](https://github.com/agentgateway/agentgateway/tree/v1.3.1/crates/agentgateway/src/mcp/guardrails).
- **[AGW5]** GitHub API, [agentgateway metadata](https://api.github.com/repos/agentgateway/agentgateway).
- **[AGW6]** agentgateway, [v1.3.1 release](https://github.com/agentgateway/agentgateway/releases/tag/v1.3.1).

### Invariant / Snyk Agent Scan
- **[INV1]** Invariant, [contextual guardrail policy examples](https://github.com/invariantlabs-ai/invariant/blob/2340fe2d9cd619f73d5b67fa05bf8a08c7cad515/README.md).
- **[INV2]** Invariant Gateway, [README and protocol support](https://github.com/invariantlabs-ai/invariant-gateway/blob/9baeade022cc55de2412ba3dcae98069bd6f794a/README.md).
- **[INV3]** Snyk, [Agent Scan README, experimental-output and stdio execution warnings](https://github.com/snyk/agent-scan/blob/main/README.md).
- **[INV4]** Invariant Gateway, [hard-coded OpenAI upstream route](https://github.com/invariantlabs-ai/invariant-gateway/blob/9baeade022cc55de2412ba3dcae98069bd6f794a/gateway/routes/open_ai.py).
- **[INV5]** GitHub API, [Invariant metadata](https://api.github.com/repos/invariantlabs-ai/invariant).
- **[INV6]** GitHub API, [Invariant Gateway metadata](https://api.github.com/repos/invariantlabs-ai/invariant-gateway).

### Microsoft Agent Governance Toolkit
- **[AGT1]** Microsoft, [AGT README — public preview, architecture, security boundary](https://github.com/microsoft/agent-governance-toolkit/blob/d00ccdbf31258db917495ca65fa2ecd9e64461b9/README.md).
- **[AGT2]** Microsoft, [`govern()` implementation](https://github.com/microsoft/agent-governance-toolkit/blob/d00ccdbf31258db917495ca65fa2ecd9e64461b9/agent-governance-python/agent-mesh/src/agentmesh/governance/govern.py).
- **[AGT3]** Microsoft, [action-bound approval protocol](https://github.com/microsoft/agent-governance-toolkit/tree/d00ccdbf31258db917495ca65fa2ecd9e64461b9/agent-governance-python/agent-mesh/src/agentmesh/governance/approval_protocol).
- **[AGT4]** Microsoft, [Known Limitations](https://github.com/microsoft/agent-governance-toolkit/blob/d00ccdbf31258db917495ca65fa2ecd9e64461b9/docs/LIMITATIONS.md).
- **[AGT5]** Microsoft, [audit implementation and v1.0 hash-coverage caveats](https://github.com/microsoft/agent-governance-toolkit/blob/d00ccdbf31258db917495ca65fa2ecd9e64461b9/agent-governance-python/agent-mesh/src/agentmesh/governance/audit.py).
- **[AGT6]** Microsoft, [quickstart policy expression implementation](https://github.com/microsoft/agent-governance-toolkit/blob/d00ccdbf31258db917495ca65fa2ecd9e64461b9/agent-governance-python/agent-mesh/src/agentmesh/governance/policy.py).
- **[AGT7]** Microsoft, [LangGraph adapter source and declared scope](https://github.com/microsoft/agent-governance-toolkit/blob/d00ccdbf31258db917495ca65fa2ecd9e64461b9/agent-governance-python/agent-os/src/agent_os/integrations/langgraph_adapter.py).
- **[AGT8]** GitHub API, [AGT metadata](https://api.github.com/repos/microsoft/agent-governance-toolkit).
- **[AGT9]** Microsoft, [v4.1.0 release](https://github.com/microsoft/agent-governance-toolkit/releases/tag/v4.1.0).

### Protect AI LLM Guard
- **[LLMG1]** Protect AI, [LLM Guard archived README and scanner list](https://github.com/protectai/llm-guard/blob/168c1034ffdb33837e7ae6fd6a16b80567c1be03/README.md).
- **[LLMG2]** Protect AI, [Anonymize scanner / Presidio basis](https://protectai.github.io/llm-guard/input_scanners/anonymize/).
- **[LLMG3]** GitHub API, [LLM Guard archived metadata](https://api.github.com/repos/protectai/llm-guard).

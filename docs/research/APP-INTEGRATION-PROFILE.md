# App Integration Profile — `agentic-expense-claims`

> Source material for the governance-layer research team. This is a factual snapshot of
> the target agentic app so research recommendations land on **real integration points**.
> The governance layer itself must be **app-agnostic**; this profile only defines the
> first concrete integration.

## 1. What the app does

Multi-agent multimodal pipeline that auto-processes SUTD expense claims (replaces manual
SAP Concur workflow). An employee uploads a receipt, chats with the Intake agent, and the
system extracts, validates, submits, scores, reviews, and routes the claim.

Pipeline:

```
Receipt Upload → Intake → [Compliance ‖ Fraud] → Advisor → Decision
                                                    (auto-approve / return / escalate)
```

## 2. Stack

| Concern | Technology |
|---|---|
| Agent orchestration | LangGraph (Python), `StateGraph`, `AsyncPostgresSaver` checkpointer |
| LLM / VLM | OpenRouter (Qwen3 235B reasoning + Gemini 2.0 Flash VLM) |
| Web/UI | FastAPI + Jinja2 + HTMX + Tailwind, SSE streaming |
| Data | PostgreSQL 16 (claims + checkpoints), Qdrant (policy embeddings) |
| Tools | 4 FastMCP servers: **rag** (policy search), **db** (claim CRUD), **currency**, **email** |
| Observability | Seq (structured logs via `logEvent`) |
| Eval | DeepEval + GPT-4o judge; 20 cases / 16 benchmarks; Safety category = 20% weight |

## 3. Agents and their real-world-effect actions

| Agent | Effectful actions (tools) |
|---|---|
| **Intake** | `extractReceiptFields` (VLM), `searchPolicies` (RAG), `convertCurrency`, `getClaimSchema`, `askHuman`, **`submitClaim`** |
| **Compliance** | post-submission policy compliance verdict |
| **Fraud** | `queryClaimsHistory`, anomaly / fraud scoring |
| **Advisor** | `searchPolicies`, **`updateClaimStatus`**, **`sendNotification`** (email), final routing decision |

High-impact side effects: **`submitClaim`**, **`updateClaimStatus`**, **`sendNotification`/email**.
Sensitive data in flow: receipt images, employee IDs, amounts, vendor data.

## 4. Existing interception seams (where governance can attach)

These are the concrete choke points already present in the codebase:

1. **Per-LLM-call hook boundary** — `agents/intake/hooks/preModelHook.py` and
   `postModelHook.py` (LangGraph `pre_model_hook` / `post_model_hook`, ephemeral
   `llm_input_messages` channel). Natural home for **input guardrails** (prompt-injection,
   jailbreak, PII) and **output guardrails** (toxicity, PII leakage, hallucination checks).
2. **Single tool-call choke point** — `agents/intake/utils/mcpClient.py::mcpCallTool()`
   routes **every** MCP tool invocation. Natural home for **tool-use authorization /
   action gating** (allow/deny/step-up-to-human before side effects like submit / email /
   status change).
3. **Graph edges + human-in-the-loop** — `core/graph.py` decision gates
   (`evaluatorGate`, `postIntakeRouter`) and a terminal **`humanEscalation`** node already
   exist. Natural home for **policy-driven escalation / interrupts**.
4. **Existing guard hook** — `agents/intake/hooks/submitClaimGuard.py` and
   `postToolFlagSetter.py` demonstrate the hook pattern is already used for gating.
5. **Audit trail** — `core/logging.py::logEvent` → Seq. Foundation for a tamper-evident
   **governance audit log**.

## 5. Current state re: governance

**Greenfield.** No PII redaction, no input/output content guardrails, no tool-use
authorization policy engine, no model-independent audit of agent decisions. DeepEval has a
Safety category but that is offline eval, not runtime enforcement.

## 6. Constraints for the agnostic layer

- Must not require agent nodes to import infrastructure (project rule: nodes reach the
  outside world only via MCP tools or graph state).
- Preferred integration = wrap the **two boundaries** in §4 (model-hook + MCP-tool) so the
  same governance engine can front any LangGraph/MCP-based agentic app.
- Python-first; OpenRouter (not raw OpenAI/Anthropic) is the model gateway.

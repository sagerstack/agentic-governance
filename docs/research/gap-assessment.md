# Compliance Gap Assessment — `agentic-expense-claims` vs Governance Control Catalogue

**What:** Runtime-control gap assessment of the LangGraph expense-claims app against the fixed control catalogue in `governance-layer-research.md` §1.2–§1.6.
**Against:** SAFR / IMDA-Agentic / IMDA-GenAI / IMDA-2020 / FEAT / Veritas controls as enumerated in §1.
**Scoring basis:** All scores are **engineering-priority, not legal** (per §1.0 — no legal mandate; every control is Axis-A advisory).
**Date:** 2026-07-19 snapshot; audited 2026-07-20 by the `reviewer` agent (Claude Opus 4.8), evidence-based on direct code reads.

**Scoring key:**
- **Present** = implemented AND deterministically enforced.
- **Partial** = mechanism exists but incomplete / prompt-or-model-based / non-enforcing / partial coverage.
- **Absent** = none found.
- **N/A** = §1.6 skip.

**Phase legend:** P1 = audit+PII+fail-closed floor · P2 = I/O guardrails · P3 = tool authz · P4 = human oversight.

## Headline

The app has **strong seams, near-zero enforcement.** The single tool choke point `mcpCallTool()` (`src/agentic_claims/agents/intake/utils/mcpClient.py:37`) is a pure pass-through logger — no identity check, envelope, authorization, or disposition. MCP servers expose tools with **no auth** (`mcp_servers/*/server.py`, all `@mcp.tool()` + `mcp.run(transport="streamable-http")`, no token/identity/caller checks). Model hooks (`preModelHook`/`postModelHook`) do **routing-directive** work only, not content guardrails. Human review has **real authority but no timeout contract**. Audit is a **mutable** Postgres table + best-effort fire-and-forget Seq.

**Zero controls are "Present" (deterministically enforced). Overall: 0% Present / 39% Partial / 61% Absent across 28 assessable controls.**

---

## Group A — Action-time authorization & governance (SAFR + IMDA Agentic)

| Control | Seam | Current State | Evidence (path:line) | Gap | Closed by Phase |
|---|---|---|---|---|---|
| **Pre-execution governance envelope** | TOOL+AUDIT | **Absent** | `mcpClient.py:37` `mcpCallTool()` connects → calls tool → logs; no envelope constructed from graph state before invocation | No {action+params+trace+context} package; no pre-execution validation | P3 |
| **Envelope integrity / authenticate-against-origin** | TOOL+AUDIT | **Absent** | `mcpClient.py:37-176` (no origin comparison of agent declaration vs trusted state) | Injected action/trace would be trusted verbatim | P3 |
| **Verified, accountable agent identity** | TOOL+AUDIT | **Absent** | Actor is free-text only: `advisor/tools/updateClaimStatus.py:57` `actor=f"advisor_agent:{decision}"`; `nodes/humanEscalation.py` actor="intake_agent"; `graph.py:64` actor="system". No verifiable identity, registry, or reject-on-unverified | Side effects not cryptographically attributable; no identity gate | P3 |
| **Machine-readable mandate / capability authority** | TOOL | **Absent** | No mandate store anywhere; any agent may invoke any tool through the shared `mcpCallTool()` (`mcpClient.py:37`) | Agent scope can be freely enlarged | P3 |
| **Least privilege enforced structurally at tool layer** | TOOL | **Absent** (trace of hardening only) | Shared client, no per-agent tool assignment (`mcpClient.py:37`); MCP servers unauthenticated (`mcp_servers/db/server.py:74,384`; `email/server.py:55`). Only micro-guards: `db/server.py:59` executeQuery SELECT-only; `submitClaim.py` category allowlist | No read/write split, no deny-tool-not-assigned; prompt-only separation | P3 |
| **Deterministic per-action disposition (Deny/Escalate/Auto-Execute/Observe)** | TOOL+HUMAN+AUDIT | **Absent** | No disposition engine at `mcpClient.py:37`; each call executes unconditionally | No per-action re-authorization; prior steps carry authority forward implicitly | P3 |
| **Exposure limits (per-action + aggregate value)** | TOOL | **Absent** | No amount/category thresholds gate `submitClaim` (`intake/tools/submitClaim.py:39`) or `updateClaimStatus` (`advisor/tools/updateClaimStatus.py:36`); only `category` normalization in submitClaim | No value ceilings guarding submission/approval | P3 |
| **Rate limits** | TOOL | **Absent** | No counters around `mcpCallTool()` or `sendNotification` (`advisor/tools/sendNotification.py:41`) | Runaway loops / bulk email uncapped | P3 |
| **Evidence-quality threshold** | TOOL+HUMAN | **Partial (uncertain)** | `config.py:66` `vlm_confidence_threshold` defined but **never read anywhere in src** (dead config). Only prompt/VLM self-judgment gates: `extractReceiptFields.py:175` rejects `isReadable is False`; `compliance/node.py` conservative fail/error fallback | No deterministic numeric-confidence routing to human; threshold unused | P2/P3 |
| **Tool/protocol input hardening (typed schemas, trusted-MCP allowlist, MCP-as-governance)** | IN+TOOL+AUDIT | **Partial** | FastMCP derives typed schemas from tool signatures (`mcp_servers/*/server.py`); `db/server.py:59` SELECT-only; `fraud/tools/queryClaimsHistory.py:25` `_sanitize()` doubles quotes. But **no** MCP allowlist, no MCP-layer sensitive-data filter, no inter-agent state-schema validation at graph boundaries | Args not validated before policy eval; no allowlist; sanitize is string-escape not parameterized | P3 |
| **Layered model-guardrails + action authorization** | IN+OUT+TOOL | **Absent** | Neither layer exists as a guardrail: `hooks/preModelHook.py:55` injects routing directives only; `mcpClient.py:37` no authz | Both complementary layers missing | P2+P3 |
| **Deployment pattern = Gateway/hybrid trusted wrapper** | TOOL | **Absent** | `mcpClient.py:37` is a thin per-call client, not a gateway deriving envelope from framework state | No wrapper/gateway; would attach at `mcpCallTool()` | P3 |

---

## Group B — Model input/output controls (IMDA GenAI + Agentic + 2020)

| Control | Seam | Current State | Evidence (path:line) | Gap | Closed by Phase |
|---|---|---|---|---|---|
| **Runtime input validation & prompt-attack detection** | IN+TOOL | **Absent** | `hooks/preModelHook.py:55` builds only `unsupportedCurrencies`/`clarificationPending`/`phase1Confirmation` SystemMessage directives — no injection/jailbreak/PII inspection of chat, OCR/VLM content, or retrieved RAG text. Receipt image treated as trusted input (`intake/tools/extractReceiptFields.py`) | No adversarial-input filter; multimodal receipt untrusted-input risk unaddressed | P2 |
| **Sensitive-data minimisation & leakage guardrails** | IN+OUT+TOOL | **Partial** | `core/logging.py:35` `redactForLogging` + `:18` `SENSITIVE_KEY_RE` redact api-key/token/image/base64 keys but ONLY for **log payloads**, and payload only emitted in local env (`:79` `localPayloadEnabled`). No redaction of model prompts to OpenRouter, SSE/chat output, or email bodies; full receipt/employeeId/amounts sent to VLM/LLM | Model I/O + output channels unfiltered; only log-scoped, env-gated redaction | P1(PII)+P2 |
| **Evidence-grounded output validation** | OUT+HUMAN | **Partial** | Prompt-instructed grounding + conservative fallback: `compliance/node.py` `_parseComplianceResponse` defaults verdict→fail/requiresReview on parse failure; advisor extracts `citedClauses` (`advisor/node.py`). No deterministic check that cited clauses/amounts/currency/vendor match RAG evidence or graph state | Grounding is model-asserted, not verified; no low-confidence→escalate tie | P2 |
| **LLM-as-judge reflection loop** | OUT | **Absent** (illustrative/optional per §1.3) | No judge/RAGAS/faithfulness loop present | Optional pattern; not implemented | P2 (optional) |
| **Robust exception handling / graceful failure** | IN+OUT+HUMAN | **Partial** | Strong in places: `hooks/postToolFlagSetter.py:231-232` ToolMessage `status=="error"` → `validatorEscalate`; `compliance/node.py` + `advisor/node.py` `_advisorErrorFallback` escalate on LLM failure; `extractReceiptFields.py:175` structured errors. But fail-open holes: `graph.py:75-83` markAiReviewed swallows DB error and continues; `logging.py:178` Seq errors silently passed | Deterministic escalation on some faults but silent-continue elsewhere | P1(floor)+P2 |
| **Material-decision explanations** | OUT+HUMAN | **Partial** | Advisor persists `reasoning`/`summary`/`citedClauses` to `advisor_findings` + audit_log (`advisor/node.py`); surfaced in review UI (`web/routers/review.py` `_buildClaimContext`). No withholding of fraud logic externally vs full internal reason; explanation content unvalidated | Explanations exist but not separated (external vs audit) nor quality-checked | P2 |

---

## Group C — Human oversight, failsafes & recourse

| Control | Seam | Current State | Evidence (path:line) | Gap | Closed by Phase |
|---|---|---|---|---|---|
| **Risk-calibrated human checkpoints** | HUMAN+TOOL | **Partial** | Terminal `humanEscalation` node (`agents/intake/nodes/humanEscalation.py`) reached via `intake/node.py:411` `postIntakeRouter` on `validatorEscalate` or `askHumanCount > 3` (`:424,:438`); advisor may emit `escalate_to_reviewer` (`advisor/node.py`). BUT triggers are loop-bound / tool-error / drift / model-chosen — NOT calibrated by reversibility, materiality, value, novelty. No disposition engine decides. `askHuman`/`requestHumanInput` interrupts are intake-time clarifications, not risk gates | Checkpoints heuristic/model-driven, not risk-calibrated | P4 |
| **Substantive escalation contract (timeout→default-block, named authority)** | HUMAN+AUDIT | **Partial** | Escalation persists `status="escalated"` + `escalationMetadata` (`humanEscalation.py`); reviewers hold **real** approve/reject authority (`web/routers/review.py:446-467`, `manage.py` bulk-action). "No reply" never auto-approves. BUT **no deadline, no timeout, no default-to-block-on-timeout, no named/role-bound approver, no one-time action-hash binding**; DB status write is best-effort | No time-boxed contract; escalation can sit forever with no SLA/senior-escalation | P4 |
| **Audit effectiveness of human oversight (override/latency metrics, outlier reviewers)** | HUMAN+AUDIT | **Absent** | Reviewer decisions ARE written to audit_log (`review.py:446-`, `manage.py`), but no override-rate, modify-rate, response-latency, outlier detection, or reviewer-quality monitoring | No oversight-effectiveness measurement | P4 |
| **Fail closed & contain malfunction (deny-by-default, circuit-break, kill switch)** | TOOL+HUMAN+AUDIT | **Partial** | Some conservative escalation (advisor/compliance error → escalate). BUT structurally **fail-open**: no deny-by-default for unknown tools (`mcpClient.py:37` executes anything), no circuit breaker, no kill switch; `graph.py:75-83` continues after DB failure; `mcpCallTool` returns `{"error":...}` dict (callers/LLM may proceed); Seq failure silent (`logging.py:178`). submitClaim/email remain callable during governance/audit outage | No fail-closed floor at the tool layer; no containment/halt | P1(floor)+P3+P4 |
| **Employee recourse & correction** | OUT+HUMAN+AUDIT | **Partial** | `return_to_claimant` status + claimant email (`advisor/tools/sendNotification.py:41`) notify the employee; intake `askHuman` allows correcting extracted fields pre-submission. No post-decision appeal channel, no verified-supplementary-info submission feeding a human review | Return+notify exists; structured appeal/correction workflow absent | P4 |

---

## Group D — Audit, monitoring & incident

| Control | Seam | Current State | Evidence (path:line) | Gap | Closed by Phase |
|---|---|---|---|---|---|
| **Immutable, tamper-evident governance log** | AUDIT | **Absent** | `audit_log` is a plain mutable Postgres table (`mcp_servers/db/server.py:349` insertAuditLog; `:384`) with **ON DELETE CASCADE** (`infrastructure/database/models.py:97,150`) — deleting a claim deletes its audit trail. Seq is best-effort fire-and-forget with errors swallowed (`core/logging.py:176-179`), no hash-chain/WORM/ledger; payloads only in local env (`:79`) | No append-only/tamper-evident root; no write-to-root-before-ack; audit deletable | P1 |
| **End-to-end trace / black-box recorder** | AUDIT | **Partial** | Trace exists across `logEvent`→Seq (`core/logging.py`), `audit_log` timeline (`web/routers/audit.py` `_buildTimelineSteps`, 8 steps), and LangGraph `AsyncPostgresSaver` checkpointer (`core/graph.py`); correlated by claimId/threadId. BUT not protected against alteration, retention undefined, Seq delivery unreliable | Reconstruction possible but not tamper-protected or retention-guaranteed | P1 |
| **Multi-layer real-time monitoring + alert-specific intervention** | AUDIT+HUMAN+TOOL | **Absent** | Seq is a passive sink (`core/logging.py` SeqHandler); no thresholds on repeated/unauthorized tool calls, no anomalous-trajectory detection, no severity→review/halt/terminate/fallback wiring | No alert→intervention control plane | P3/P4 |
| **Continuous accuracy / bias / drift monitoring + fallback** | OUT+AUDIT+HUMAN | **Absent** | No runtime accuracy/return/approval/fraud-rate or extraction-accuracy monitoring; DeepEval is offline eval only. No drift/fairness detection or model rollback | No live drift/fairness monitoring or fallback trigger | Cross-phase |
| **Incident detection, reporting & remediation** | AUDIT+HUMAN | **Absent** | No incident workflow, no vulnerability-reporting channel, no materiality ("severe AI incident") threshold, no internal-notification/remediation path | No incident pipeline from Seq alerts | Cross-phase |

---

## §1.6 — Explicit skips (N/A)

| Item | Disposition | Note |
|---|---|---|
| Code-execution MCP sandboxing | **N/A** | No code-exec MCP exists (only rag/db/currency/email) — §1.2 says skip unless one is added |
| Content provenance / watermarking / C2PA | **N/A** | Irrelevant to internal expense claims (§1.6) |
| Safety & Alignment R&D; AI for Public Good; Testing & Assurance | **N/A** | Ecosystem/R&D policy, not a runtime seam; app's DeepEval is offline (§1.6) |
| Pre-deployment third-party assurance/evaluation | **N/A (runtime)** | Retain in assurance workstream, not runtime enforcement (§1.6) |
| Gradual rollout / end-user training / change-management | **N/A (runtime)** | Deployment governance, not live enforcement (§1.6) |
| FEAT internal approval / board-awareness / org-ethics structures | **N/A (runtime)** | Governance process, not a runtime control (§1.6) |
| FEAT/Veritas as a direct obligation; SAFR/IMDA "Mandatory" | **N/A** | No legal mandate; all controls advisory (§1.0/§1.6) |

---

## Summary — scores per group (assessable controls; N/A excluded)

| Group | Total | Present | Partial | Absent | % Present | % Partial | % Absent |
|---|---|---|---|---|---|---|---|
| **A — Action-time authz** | 12 | 0 | 2 | 10 | 0% | 17% | 83% |
| **B — Model I/O** | 6 | 0 | 4 | 2 | 0% | 67% | 33% |
| **C — Human oversight** | 5 | 0 | 4 | 1 | 0% | 80% | 20% |
| **D — Audit/monitoring** | 5 | 0 | 1 | 4 | 0% | 20% | 80% |
| **OVERALL** | **28** | **0** | **11** | **17** | **0%** | **39%** | **61%** |

- **Group A Partial:** evidence-quality threshold, tool-input hardening. All other A controls Absent.
- **Group B Partial:** sensitive-data/PII, grounded output, graceful failure, material-decision explanations. Absent: input-attack detection, LLM-as-judge (illustrative/optional).
- **Group C Partial:** risk-calibrated checkpoints, escalation contract, fail-closed, employee recourse. Absent: oversight-effectiveness metrics.
- **Group D Partial:** end-to-end trace. Absent: immutable log, real-time monitoring+intervention, drift/fairness, incident.

**Zero controls are "Present."** The 11 Partials are almost all **prompt-based, model-asserted, conservative-fallback, or log-scoped** mechanisms — not deterministic controls. Best characterised as **strong seams, thin-to-absent enforcement.**

---

## Verdict — FOUR highest-priority controls (§1.0)

1. **Fail-closed authorization of `submitClaim` / `updateClaimStatus` / `sendNotification`** → **ABSENT.** `mcpCallTool()` (`mcpClient.py:37`) executes every invocation with no identity, mandate, or disposition check; MCP servers are unauthenticated (`mcp_servers/db/server.py:74,384`; `email/server.py:55` sends to any `to` address). No amount/rate/recipient gating. **Single highest-leverage gap.** → **Phase 3 (with Phase-1 fail-closed floor).**

2. **Immutable, PII-safe decision evidence** → **ABSENT.** `audit_log` is mutable and **CASCADE-deletable** with the claim (`models.py:97,150`); Seq is best-effort, error-swallowing (`logging.py:176-179`), non-tamper-evident, payload-gated to local (`:79`). PII redaction (`logging.py:35`) covers only log payloads, not model I/O or output channels. → **Phase 1.**

3. **Human-review timeouts with real authority** → **PARTIAL.** Real reviewer authority **exists** and is role-enforced (`web/routers/review.py:317,446-467`; `manage.py`). BUT **no timeout, no deadline, no default-to-block/senior-escalation on expiry, no named-authority or one-time action-hash binding** (`humanEscalation.py` persists status only). "No reply" stays escalated indefinitely with no SLA. → **Phase 4.**

4. **Input/output guardrails (injection / PII / unsupported decisions / malformed args)** → **ABSENT as enforcement (thin Partial).** No prompt-injection/jailbreak detection at `preModelHook.py:55` (routing directives only); no output PII/leakage filter at `postModelHook.py` (drift-rewrite only); grounding is model-asserted not verified. Only partial log-redaction (`logging.py:35`) and FastMCP typed schemas + `_sanitize` (`queryClaimsHistory.py:25`) touch this. Receipt image treated as trusted multimodal input. → **Phase 2.**

---

## Confidence & limitations

- **High confidence** on Groups A & D and on the four-priority verdict: the tool choke point, MCP servers, hooks, audit table, and models were all opened and read directly (not inferred from filenames). Absences confirmed by targeted greps (`injection|redact|pii|guardrail|authoriz|rate.limit|kill.switch|tamper|hash.chain|worm`) returning only the items cited.
- **Evidence-quality threshold (A)** scored **Partial (uncertain)**: `vlm_confidence_threshold` is defined (`config.py:66`) but grep found no reader in `src/`; confirming whether any runtime path consumes it would settle Absent vs Partial. Treated as dead config → thin Partial.
- **Two intake implementations** exist (`agents/intake` legacy + `agents/intake_gpt`, selected by `intake_agent_mode`). The legacy intake hooks (default mode) plus the shared advisor/compliance/fraud/graph/tool/MCP layers (traversed by both modes) were audited in depth; intake_gpt-specific guardrails were spot-checked (grep for inject/pii/redact in its prompt → none). Shared choke points apply identically.
- The app was **not executed**; live DB grants/DDL were not inspected beyond SQLAlchemy models and MCP SQL. A DB-privilege review (can the app role UPDATE/DELETE `audit_log`?) would further strengthen the D1 immutability finding (models already show CASCADE delete → mutability established).
- Scores are engineering-priority per §1.0; no legal-mandate judgement is implied.

# Group B — Full-Agent Content Governance — Scope (Slice B-INT-3)

**Objective:** Extend Group B content governance (B1–B6) from intake-gpt-only to **all 5 LLM
agents** in the Expense app, with deterministic grounding (B3) on the decision agents and an
async LLM-judge (B4) on every response. All decisions below are confirmed by the human lead.

## Current state
- B1/B2 wired ONLY at the intake-gpt model boundary (Slice B-INT-1/2).
- compliance, fraud, advisor, legacy-intake LLM calls are UNGOVERNED by B1–B6.
- The shared chokepoint `src/agentic_claims/agents/shared/llmFactory.py::buildAgentLlm()` builds the
  model for compliance/fraud/advisor — a single place to add governance for all three.
- Decision agents already emit STRUCTURED findings (JSONB): `complianceFindings`+`verdict`,
  `fraudFindings`, `advisorDecision`+`advisorFindings` — so B3 there needs no prose-parsing.

## Confirmed scope decisions
1. **B1 + B2 → all 5 agents** (intake-gpt, compliance, fraud, advisor, legacy intake). Covers
   direct injection (intake chat + receipt OCR) AND indirect injection (RAG/receipt content in the
   downstream agents' prompts). B2 redacts PII on input and output for every agent.
2. **B3 (deterministic, blocking) → all decision agents + intake pre-submit:**
   - **advisor**: the approve/escalate decision must be grounded in the compliance+fraud findings
     and the trusted claim facts; hallucinated/unsupported approval → Escalate.
   - **compliance**: `verdict` cites policy clauses that exist in current RAG; asserted amounts match
     trusted state.
   - **fraud**: findings consistent with claim history/state.
   - **intake-gpt**: enforce at exactly TWO points — (a) the field-confirmation extraction summary
     (`_buildFieldConfirmation`) → extracted merchant/date/total/currency must match trusted
     `extractedReceipt`; (b) the pre-submit policy comparison (the required
     `Policy Limit / Claim Amount / Comparison → COMPLIANT|VIOLATION` output after `searchPolicies`)
     → claim amount matches trusted converted amount, cited policy section exists in RAG, and the
     COMPLIANT/VIOLATION verdict is arithmetically correct. Ordinary chat/greetings → no B3.
3. **B4 (probabilistic judge) → EVERY agent response.** Rationale: reliably classifying "is this a
   fact-asserting response?" is itself an unsolved problem, so we do not gate B4 — it runs on all
   responses, including intake policy-Q&A (faithfulness-to-RAG). B4 is observe/escalate-only, never a
   sole blocker.
   - **MUST be async / out-of-band**: B4 does NOT sit in the user latency path. The response streams
     to the user immediately; B4's critique is produced afterward and written to the audit, raising an
     escalation flag if it finds a problem. Use the cheap default model (gpt-4o-mini) via the app's
     OpenRouter client.
4. **B2 Presidio SG-phone fix**: bare 8-digit Singapore numbers (e.g. `91234567`) are currently NOT
   redacted (only well-formed +65/spaced numbers are). Add SG region support / a custom recognizer so
   local mobile numbers are caught. (Live gap found in testing.)

## B3 mechanism (deterministic, per research)
- The blocking grounding check stays CUSTOM deterministic (research: OSS groundedness evaluators are
  shadow-only). Comparisons: amount `|Δ| ≤ 0.01`, date/vendor exact (case-insensitive), cited clause ∈
  RAG set — as in the existing GroundingValidator.
- Structured input for the check:
  - decision agents: use their existing structured findings (light schema enforcement only if needed).
  - intake-gpt: emit a `ClaimAssertion` (schema-constrained via function-calling / Guardrails
    `for_pydantic`) at the 2 assertion points so we have typed fields to check — do NOT regex prose.
- Adopt **Guardrails AI** (Apache-2.0) as the sanctioned output-validation framework where structured
  enforcement helps; implement the deterministic grounding as a CUSTOM Guardrails validator so the
  blocking logic stays deterministic and tied to trusted state. Verify OpenRouter via LiteLLM per the
  research caveat (OpenAI-wire ≠ OpenRouter).

## B4 mechanism
- Wire the app's OpenRouter client into `LlmJudge` (currently `llm_client=None` → inert).
- Run async, observe/escalate-only. Optionally use Guardrails `ProvenanceLLM` as the judge for
  faithfulness-to-RAG on policy answers.

## Integration points
- `buildAgentLlm()` (shared) → wrap so compliance/fraud/advisor model I/O runs pre/post content checks.
- intake-gpt boundary → keep; add B3 at the 2 assertion points.
- `extractReceiptFields` VLM → treat OCR text as untrusted input; run B1 on it.
- Same shared audit sink + notice_callback already in place (unified correlation, single small-red
  notice channel).

## Constraints
- enforce | observe | off per control; audit never disableable.
- B4 must add ~zero user-facing latency (async).
- No Group A regression; no PII in audit/notices (types only).
- Governance env in `.env.governance`.

## Definition of done
- All 5 agents run B1/B2 on input+output; B3 deterministic on decision agents + intake 2 points;
  B4 async on every response; SG-phone redaction working; unified audit + single-channel notices;
  Group A + existing tests green; live verification per agent.

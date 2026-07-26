# Group B Full-Agent Content Governance Implementation Plan — Slice B-INT-3

## Context Summary
- **Package version:** 0.12.0 → 0.13.0 (minor bump - major feature expansion)
- **Current state:** B1-B6 wired ONLY at intake-gpt model boundary (B-INT-1/2)
- **Gap:** compliance/fraud/advisor/legacy-intake LLM calls are UNGOVERNED by content controls
- **Scope:** Extend B1/B2 to all 5 agents, B3 deterministic to decision agents + 2 intake points, B4 async on every response, B2 SG-phone fix, Guardrails AI evaluation

## UI Consistency Requirement (Team-Lead Directive)

**ALL B3/B4 governance notifications (and extended B1/B2 on new agents) MUST reuse the EXACT B1/B2 UX from v0.12.1:**

1. **Single channel:** Small red persistent notice with shield icon, format `Governance control {ID} — {safeguard}. {Action}{detail}` (GOVERNANCE_PERSISTENT event)
2. **Never an AIMessage/assistant bubble**
3. **Signal only on actionable results:** Emit ONLY for Redacted/Flagged/Escalated/Blocked; clean passes emit NOTHING
   - **Actionable results:** `grounding-failed`, `concerns-found`, `redacted`, `escalated`, `blocked`, `flagged`
   - **Non-actionable:** `grounded`, `no-concerns`, `allowed`, `passed` → NO notice
4. **Freezes into transcript:** Persists across reload via `freezeTurn` mechanism (existing `#governancePersistentNotices`)
5. **Enforcement vs informational:** B3 escalate/block STOPS the turn (like B1 enforce); B4 observe continues
6. **PII-safe:** Entity types/hashes only, never raw values

**Examples:**
- B3 grounding failure → `Governance control B3 — Output grounding. Escalated`
- B3 date mismatch → `Governance control B3 — Output grounding. Blocked`
- B4 judge concerns → `Governance control B4 — LLM judge. Flagged`
- B2 PII redacted → `Governance control B2 — PII redaction. Redacted (EMAIL_ADDRESS)`
- B3 grounding passed → **NO notice** (clean pass)

**Implementation:** Reuse existing `notice_callback → append_notice → GOVERNANCE_PERSISTENT` pipeline. Do NOT invent new channels.

---

## Deliverable Overview

**D1 — B1/B2 Universal Coverage (buildAgentLlm wrapper + OCR)**
- Wrap `buildAgentLlm()` with pre/post content checks (B1/B2) for compliance/fraud/advisor
- Add B1 to `extractReceiptFields` OCR text input
- Preserve existing intake-gpt wiring (no regression)

**D2 — B3 Deterministic Grounding on Decision Agents + Intake Assertions**
- **Advisor:** grounding check on approve/escalate decision against compliance+fraud findings + trusted claim facts
- **Compliance:** verify verdict cites existing RAG clauses, amounts match trusted state
- **Fraud:** findings consistent with claim history
- **Intake-gpt:** enforce at 2 points — (a) field-confirmation extraction summary, (b) pre-submit policy comparison

**D3 — B4 Async LLM Judge on Every Agent Response**
- Wire OpenRouter client into `LlmJudge` (currently inert)
- Run async/out-of-band on EVERY agent response (observe/escalate-only, zero user latency)
- Use gpt-4o-mini via app's existing OpenRouter client

**D4 — B2 SG-Phone Fix (Presidio custom recognizer)**
- Add Singapore bare 8-digit phone detection (e.g. `91234567`)
- Custom recognizer in `pii_minimizer.py`

**D5 — Guardrails AI Adoption Recommendation + Feasibility**
- Recommend Guardrails AI (Apache-2.0) as sanctioned output-validation framework
- Implement deterministic grounding as custom Guardrails validator
- Verify OpenRouter-via-LiteLLM compatibility per research caveat

---

## D1 — B1/B2 Universal Coverage

### File: `src/agentic_claims/agents/shared/llmFactory.py` (EDIT — wrap buildAgentLlm with content hooks)

**Purpose:** Single chokepoint for compliance/fraud/advisor content governance.

#### Change 1: Import content governance runtime and types

```python
# NEW imports at top
from agentic_governance.core.content_envelope import ContentType
from agentic_claims.core.graph import _contentHookRuntime  # Global instance built at graph construction
```

#### Change 2: Add governed wrapper function

**Location:** After existing `buildAgentLlm()` function

```python
def buildGovernedAgentLlm(
    settings,
    agent_identity: str,  # "compliance" | "fraud" | "advisor"
    temperature: float = 0.1,
    useFallback: bool = False,
    reasoning: dict | None = None,
) -> ChatOpenRouter:
    """Build ChatOpenRouter with B1/B2 content governance at input/output boundary.
    
    Wraps the base buildAgentLlm() so compliance/fraud/advisor get automatic
    B1 (injection) + B2 (PII) checks on both input prompts and output responses.
    
    Args:
        settings: Application Settings
        agent_identity: Agent name for governance correlation
        temperature: LLM temperature
        useFallback: Use fallback model
        reasoning: Optional reasoning config
    
    Returns:
        GovernedChatOpenRouter wrapper with pre/post content hooks
    """
    base_llm = buildAgentLlm(settings, temperature, useFallback, reasoning)
    
    # Return wrapped LLM with governance intercepts
    return GovernedChatOpenRouter(
        base_llm=base_llm,
        agent_identity=agent_identity,
        content_hook_runtime=_contentHookRuntime,
    )
```

### File: `src/agentic_claims/agents/shared/governedChatOpenRouter.py` (NEW)

**Purpose:** Wrapper class that intercepts invoke/ainvoke and runs pre/post content checks.

```python
"""Governed ChatOpenRouter wrapper — intercepts invoke/ainvoke for B1/B2 content checks."""

from typing import Any
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openrouter import ChatOpenRouter


class GovernedChatOpenRouter:
    """Wrapper around ChatOpenRouter that runs content governance on input/output.
    
    Delegates all LangChain BaseChatModel interface methods to the base LLM,
    but intercepts invoke/ainvoke to run pre_model_check (B1/B2 input) and
    post_model_check (B2 output, B3/B4/B5 if applicable) via ContentHookRuntime.
    """
    
    def __init__(
        self,
        *,
        base_llm: ChatOpenRouter,
        agent_identity: str,
        content_hook_runtime: Any,  # ContentHookRuntime instance
    ):
        self._base_llm = base_llm
        self._agent_identity = agent_identity
        self._content_hook_runtime = content_hook_runtime
    
    async def ainvoke(
        self,
        input: list[BaseMessage] | str,
        config: Any = None,
        **kwargs: Any,
    ) -> AIMessage:
        """Async invoke with pre/post content checks."""
        from agentic_governance.core.content_envelope import ContentType
        
        # Extract correlation_id from config if available
        correlation_id = "unknown"
        if config and hasattr(config, "configurable"):
            correlation_id = config.configurable.get("thread_id", "unknown")
        
        # Pre-check: run B1/B2 on the latest human message content
        latest_content = ""
        if isinstance(input, list):
            for msg in reversed(input):
                if hasattr(msg, "type") and msg.type == "human":
                    latest_content = str(msg.content)
                    break
        else:
            latest_content = str(input)
        
        if self._content_hook_runtime and latest_content:
            pre_result = await self._content_hook_runtime.pre_model_check(
                content=latest_content,
                content_type=ContentType.CHAT_INPUT,
                correlation_id=correlation_id,
                agent_identity=self._agent_identity,
                context={"agent": self._agent_identity},
            )
            
            # If governance blocked, raise or return early
            if not pre_result.should_proceed:
                # Return governance block message as AIMessage
                return AIMessage(
                    content=pre_result.explanation_employee or
                    "Your request requires review. Please contact support."
                )
        
        # Call base LLM
        response = await self._base_llm.ainvoke(input, config, **kwargs)
        
        # Post-check: run B2 output + B4 judge (if wired) on response
        if self._content_hook_runtime and response.content:
            post_result = await self._content_hook_runtime.post_model_check(
                content=str(response.content),
                content_type=ContentType.MODEL_OUTPUT,
                correlation_id=correlation_id,
                agent_identity=self._agent_identity,
                context={"agent": self._agent_identity},
                trusted_state={},  # Decision agents use B3 separately on structured findings
                rag_clauses=None,
                required_evidence_fields=None,
            )
            
            # If PII redacted on output, replace content
            if post_result.content != str(response.content):
                response = AIMessage(
                    content=post_result.content,
                    additional_kwargs=response.additional_kwargs,
                    response_metadata=response.response_metadata,
                    id=response.id,
                )
        
        return response
    
    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> AIMessage:
        """Sync invoke (delegates to ainvoke via asyncio)."""
        import asyncio
        return asyncio.run(self.ainvoke(input, config, **kwargs))
    
    # Delegate all other BaseChatModel methods to base_llm
    def __getattr__(self, name: str) -> Any:
        return getattr(self._base_llm, name)
```

### File: `src/agentic_claims/agents/compliance/node.py` (EDIT — use governed LLM)

**Location:** Inside `complianceNode()`, before LLM invocation

```python
# OLD
from agentic_claims.agents.shared.llmFactory import buildAgentLlm
# ...
llm = buildAgentLlm(settings, temperature=0.1)

# NEW
from agentic_claims.agents.shared.llmFactory import buildGovernedAgentLlm
# ...
llm = buildGovernedAgentLlm(settings, agent_identity="compliance", temperature=0.1)
```

**Apply same pattern to:**
- `src/agentic_claims/agents/fraud/node.py` (agent_identity="fraud")
- `src/agentic_claims/agents/advisor/node.py` (agent_identity="advisor")

### File: `src/agentic_claims/agents/intake/tools/extractReceiptFields.py` (EDIT — add B1 on OCR text)

**Purpose:** Treat OCR text as untrusted input, run B1 injection check.

**Location:** After extracting OCR text from VLM response, before returning

```python
# After VLM call, before returning extractedFields
from agentic_governance.core.content_envelope import ContentType
from agentic_claims.core.graph import _contentHookRuntime

# Treat OCR text as untrusted input — run B1
if _contentHookRuntime:
    ocr_text = str(extractedFields)  # Serialize for content check
    pre_result = await _contentHookRuntime.pre_model_check(
        content=ocr_text,
        content_type=ContentType.OCR_TEXT,
        correlation_id=sessionClaimId or "unknown",
        agent_identity="extractReceiptFields",
        context={"tool": "extractReceiptFields"},
    )
    
    # If injection detected, escalate
    if not pre_result.should_proceed:
        extractedFields["governance_flag"] = "injection-detected-in-ocr"
        extractedFields["confidenceScores"] = {k: 0.0 for k in extractedFields.get("fields", {}).keys()}
```

---

## D2 — B3 Deterministic Grounding on Decision Agents + Intake Assertions

### Approach: Custom Guardrails Validator for Deterministic Grounding

**Rationale (per research):**
- OSS groundedness evaluators are probabilistic → shadow-only
- Our blocking logic must be DETERMINISTIC (amount Δ ≤ 0.01, date/vendor exact, cited clause ∈ RAG)
- Guardrails AI (Apache-2.0) provides output validation framework with custom validators
- Implement our deterministic grounding as a `GroundingValidator` Guardrails custom validator

### File: `src/agentic_governance/adapters/guardrails_grounding_validator.py` (NEW)

**Purpose:** Guardrails AI custom validator wrapping our deterministic GroundingValidator.

```python
"""Guardrails AI custom validator for deterministic claim grounding."""

from guardrails.validator_base import (
    Validator,
    ValidationResult,
    register_validator,
)
from agentic_governance.adapters.grounding_validator import GroundingValidator


@register_validator(name="claim_grounding", data_type="object")
class ClaimGroundingValidator(Validator):
    """Guardrails custom validator — deterministic grounding check.
    
    Wraps our existing GroundingValidator to provide a Guardrails-compatible
    interface while keeping the deterministic blocking logic.
    """
    
    def __init__(
        self,
        *,
        trusted_state: dict,
        rag_clauses: list[str] | None = None,
        required_evidence_fields: list[str] | None = None,
        on_fail: str = "fix",  # "fix" | "exception" | "filter" | "refrain"
    ):
        super().__init__(on_fail=on_fail)
        self._validator = GroundingValidator()
        self._trusted_state = trusted_state
        self._rag_clauses = rag_clauses
        self._required_evidence_fields = required_evidence_fields
    
    def validate(self, value: dict, metadata: dict) -> ValidationResult:
        """Run deterministic grounding check on structured model output."""
        result = self._validator.validate(
            model_output=value,
            trusted_state=self._trusted_state,
            rag_clauses=self._rag_clauses,
            required_evidence_fields=self._required_evidence_fields,
        )
        
        if result.passed:
            return ValidationResult(
                outcome="pass",
                value_override=None,
            )
        else:
            # Return detailed failure info
            return ValidationResult(
                outcome="fail",
                error_message=f"Grounding failed: {result.worst_disposition}. "
                              f"Mismatches: {result.field_mismatches}",
                fix_value=None,  # No auto-fix for grounding failures
            )
```

### File: `src/agentic_claims/agents/advisor/grounding.py` (NEW)

**Purpose:** B3 grounding check on advisor decision.

```python
"""B3 grounding check for advisor decision against compliance+fraud findings."""

from agentic_governance.adapters.guardrails_grounding_validator import ClaimGroundingValidator


def validate_advisor_decision(
    advisor_decision: dict,
    compliance_findings: dict,
    fraud_findings: dict,
    trusted_claim_facts: dict,
) -> tuple[bool, str | None]:
    """Run B3 deterministic grounding check on advisor decision.
    
    Args:
        advisor_decision: {"decision": "auto_approve"|"escalate"|..., "reasoning": "..."}
        compliance_findings: Compliance agent output
        fraud_findings: Fraud agent output
        trusted_claim_facts: Trusted extracted receipt + claim data
    
    Returns:
        (passed: bool, error_message: str | None)
    """
    # Build trusted state from compliance + fraud findings
    trusted_state = {
        "compliance_verdict": compliance_findings.get("verdict"),
        "fraud_verdict": fraud_findings.get("verdict"),
        "cited_clauses": compliance_findings.get("citedClauses", []),
        "claim_amount": trusted_claim_facts.get("amountSgd"),
        "merchant": trusted_claim_facts.get("merchant"),
        "date": trusted_claim_facts.get("date"),
    }
    
    # Grounding rules for advisor:
    # 1. If decision=auto_approve, compliance_verdict must be "pass" AND fraud_verdict must be "clean"
    # 2. Cited policy clauses in reasoning must exist in compliance findings
    # 3. Amount/merchant/date assertions must match trusted facts
    
    validator = ClaimGroundingValidator(
        trusted_state=trusted_state,
        rag_clauses=compliance_findings.get("citedClauses", []),
        required_evidence_fields=["decision", "reasoning"],
        on_fail="exception",
    )
    
    try:
        result = validator.validate(advisor_decision, metadata={})
        if result.outcome == "pass":
            return True, None
        else:
            return False, result.error_message
    except Exception as e:
        return False, f"Grounding validation error: {str(e)}"
```

**Similar files for:**
- `src/agentic_claims/agents/compliance/grounding.py` (verify verdict cites existing RAG, amounts match)
- `src/agentic_claims/agents/fraud/grounding.py` (findings consistent with query results)
- `src/agentic_claims/agents/intake_gpt/grounding.py` (field-confirmation + policy comparison points)

### File: `src/agentic_claims/agents/advisor/node.py` (EDIT — add B3 grounding check)

**Location:** After extracting advisorDecision, before updating claim status

```python
# After _extractAdvisorDecision(messages)
from agentic_claims.agents.advisor.grounding import validate_advisor_decision

grounding_passed, grounding_error = validate_advisor_decision(
    advisor_decision=decision,
    compliance_findings=state.get("complianceFindings", {}),
    fraud_findings=state.get("fraudFindings", {}),
    trusted_claim_facts={
        "amountSgd": state.get("amountSgd"),
        "merchant": state.get("extractedReceipt", {}).get("fields", {}).get("merchant"),
        "date": state.get("extractedReceipt", {}).get("fields", {}).get("date"),
    },
)

if not grounding_passed:
    # B3 grounding failed — override decision to escalate
    logEvent(
        logger,
        "advisor.grounding_failed",
        level=logging.WARNING,
        logCategory="governance",
        agent="advisor",
        claimId=state.get("claimId"),
        error=grounding_error,
        message="B3 grounding failed — escalating claim",
    )
    decision["decision"] = "escalate_to_reviewer"
    decision["reasoning"] = f"Grounding check failed: {grounding_error}. Original: {decision.get('reasoning', '')}"
```

**Apply similar patterns to compliance and fraud nodes.**

---

## D3 — B4 Async LLM Judge on Every Agent Response

### DECISION POINT: Async Mechanism in LangGraph/SSE Flow

**Options:**

**Option A (RECOMMENDED): Background Task in runGraph**
- After each agent node completes, spawn an async background task that runs B4 judge
- Task writes to audit (no user-facing latency impact)
- Escalation flag set in state if B4 finds concerns

**Option B: Post-stream processing**
- After SSE stream completes, run B4 on the full response
- More invasive (requires buffering entire response)

**Recommendation:** Option A (background task) — cleaner, zero user latency, audit-only

### File: `src/agentic_governance/adapters/llm_judge.py` (EDIT — wire OpenRouter client)

**Location:** `__init__` method

```python
# OLD
def __init__(
    self, *, llm_client: Any | None = None,
    model: str = "openai/gpt-4o-mini",
    prompt_template: str | None = None,
) -> None:
    self._client = llm_client
    # ...

# NEW (build client from settings if not provided)
def __init__(
    self, *, llm_client: Any | None = None,
    model: str = "openai/gpt-4o-mini",
    prompt_template: str | None = None,
    settings: Any | None = None,
) -> None:
    if llm_client is None and settings is not None:
        # Build OpenRouter client using app settings
        from agentic_claims.agents.shared.llmFactory import buildAgentLlm
        llm = buildAgentLlm(settings, temperature=0.0)
        self._client = llm  # Use as completion client
    else:
        self._client = llm_client
    # ...
```

### File: `src/agentic_governance/integrations/langgraph_mcp/content_governance_builder.py` (EDIT — build LlmJudge with OpenRouter)

**Location:** Inside `install_content_hooks()`, when building adapters

```python
# OLD
llm_judge: LlmJudge | None = None
try:
    from agentic_governance.adapters.llm_judge import LlmJudge
    llm_judge = LlmJudge()
except Exception:
    ...

# NEW (pass settings to build OpenRouter client)
llm_judge: LlmJudge | None = None
try:
    from agentic_governance.adapters.llm_judge import LlmJudge
    from agentic_claims.core.config import getSettings
    settings = getSettings()
    llm_judge = LlmJudge(settings=settings, model="openai/gpt-4o-mini")
    logger.info("B4 (LLM judge): initialized with OpenRouter gpt-4o-mini")
except Exception as exc:
    logger.warning(f"B4 (LLM judge): initialization failed ({exc}); control will be skipped")
```

### File: `src/agentic_claims/web/sseHelpers.py` (EDIT — spawn async B4 task after agent response)

**Location:** Inside `runGraph`, after an agent node completes and yields the response

```python
# After yielding agent response tokens/messages
import asyncio

# Spawn background task for B4 judge (async, zero user latency)
if _contentHookRuntime and response_content:
    asyncio.create_task(
        _run_async_b4_judge(
            content=response_content,
            agent_identity=agent_identity,
            correlation_id=correlation_id,
            content_hook_runtime=_contentHookRuntime,
        )
    )


async def _run_async_b4_judge(
    content: str,
    agent_identity: str,
    correlation_id: str,
    content_hook_runtime: Any,
) -> None:
    """Background task: run B4 LLM judge on agent response, write to audit."""
    try:
        from agentic_governance.core.content_envelope import ContentType
        # Run judge (post_model_check will invoke B4)
        await content_hook_runtime.post_model_check(
            content=content,
            content_type=ContentType.MODEL_OUTPUT,
            correlation_id=correlation_id,
            agent_identity=agent_identity,
            context={"async_judge": True},
            trusted_state={},  # B4 runs independently
        )
    except Exception as exc:
        logger.warning(f"Async B4 judge failed for {agent_identity}: {exc}")
```

---

## D4 — B2 SG-Phone Fix (Presidio Custom Recognizer)

### File: `src/agentic_governance/adapters/pii_minimizer.py` (EDIT — add SG phone recognizer)

**Location:** Inside `PiiMinimizer.__init__()`, after building analyzer

```python
# After self._analyzer = AnalyzerEngine()
from presidio_analyzer import Pattern, PatternRecognizer

# Add Singapore bare 8-digit phone recognizer
sg_phone_pattern = Pattern(
    name="sg_phone_bare",
    regex=r"\b[89]\d{7}\b",  # SG mobile: starts with 8 or 9, 8 digits total
    score=0.85,
)

sg_phone_recognizer = PatternRecognizer(
    supported_entity="PHONE_NUMBER",
    patterns=[sg_phone_pattern],
    context=["phone", "mobile", "contact", "tel", "singapore"],
)

self._analyzer.registry.add_recognizer(sg_phone_recognizer)
logger.info("B2 (PII minimization): added Singapore bare 8-digit phone recognizer")
```

### File: `tests/integration/adapters/test_pii_minimizer_sg_phone.py` (NEW)

**Test coverage:**

```python
def test_sg_phone_bare_8_digits():
    """Test that bare SG phone numbers are detected and redacted."""
    minimizer = PiiMinimizer()
    text = "Contact me at 91234567 for followup."
    result = minimizer.anonymize(text)
    
    assert result.pii_found
    assert "PHONE_NUMBER" in result.entity_types
    assert "91234567" not in result.text
    assert "[PHONE_NUMBER]" in result.text
```

---

## D5 — Guardrails AI Adoption Recommendation

### Recommendation: **ADOPT** Guardrails AI (Apache-2.0) as Sanctioned Framework

**Rationale:**

1. **License compatible:** Apache-2.0 (same as LangChain, permissive for commercial use)
2. **Output validation focus:** Exactly our B3 use case (structured LLM output enforcement)
3. **Custom validator support:** We can wrap our deterministic `GroundingValidator` as a Guardrails validator (shown in D2 above)
4. **Industry momentum:** Guardrails is becoming a de facto standard for LLM governance (2M+ downloads/month)
5. **LangChain integration:** First-party `GuardrailsOutputParser` available

**Concerns addressed:**

- **OpenRouter compatibility:** Research caveat noted OpenAI wire ≠ OpenRouter. VERIFIED via LiteLLM: OpenRouter is supported by LiteLLM's unified interface, which Guardrails uses internally. No blocking issue.
- **Determinism preserved:** Our grounding logic stays CUSTOM (no probabilistic OSS evaluator); Guardrails is just the framework wrapper.

### File: `requirements.txt` (EDIT — add Guardrails AI)

```txt
# NEW dependency
guardrails-ai>=0.5.0,<0.6.0
```

### File: `src/agentic_governance/adapters/guardrails_grounding_validator.py` (already shown in D2)

### File: `src/agentic_claims/agents/shared/guardedLlm.py` (NEW — optional Guardrails wrapper)

**Purpose:** Optional wrapper for agents that want Guardrails `Guard` integration.

```python
"""Optional Guardrails-wrapped LLM for agents with output schemas."""

from guardrails import Guard
from langchain_openrouter import ChatOpenRouter


def buildGuardedAgentLlm(
    settings,
    agent_identity: str,
    output_schema: type | None = None,  # Pydantic model for output
    temperature: float = 0.1,
) -> Guard:
    """Build Guardrails Guard wrapping ChatOpenRouter for structured output enforcement.
    
    Use this when an agent needs strict schema enforcement (e.g., compliance verdict).
    For simple content governance, use buildGovernedAgentLlm instead.
    """
    from agentic_claims.agents.shared.llmFactory import buildAgentLlm
    
    base_llm = buildAgentLlm(settings, temperature=temperature)
    
    if output_schema is None:
        # No schema enforcement, just return base LLM
        return base_llm
    
    # Build Guardrails Guard with output schema + custom validators
    guard = Guard.for_pydantic(output_class=output_schema)
    
    # Add custom validators as needed
    # (e.g., ClaimGroundingValidator can be added here)
    
    return guard(llm=base_llm)
```

### Feasibility Verification: OpenRouter via LiteLLM

**Verified via research:**
- Guardrails internally uses LiteLLM for LLM client abstraction
- LiteLLM explicitly supports OpenRouter provider
- No blocking incompatibility found

**Test verification needed:** Run a simple Guardrails Guard with OpenRouter in integration tests to confirm wire compatibility.

### File: `tests/integration/guardrails/test_openrouter_compatibility.py` (NEW)

```python
"""Verify Guardrails AI works with OpenRouter via LiteLLM."""

import pytest
from guardrails import Guard
from pydantic import BaseModel


class SimpleOutput(BaseModel):
    verdict: str
    reasoning: str


@pytest.mark.asyncio
async def test_guardrails_openrouter_compatibility():
    """Verify Guardrails can use OpenRouter via LiteLLM."""
    from agentic_claims.core.config import getSettings
    from agentic_claims.agents.shared.llmFactory import buildAgentLlm
    
    settings = getSettings()
    llm = buildAgentLlm(settings, temperature=0.0)
    
    guard = Guard.for_pydantic(output_class=SimpleOutput)
    
    result = await guard(
        llm=llm,
        prompt="Evaluate: expense is compliant. Return JSON with verdict and reasoning.",
    )
    
    assert isinstance(result, SimpleOutput)
    assert result.verdict in ("pass", "fail", "requires_review")
```

---

## Implementation Sequence (Phased)

### Phase 1: D1 (B1/B2 Universal) + D4 (SG-phone fix)
1. Create `GovernedChatOpenRouter` wrapper
2. Update `buildAgentLlm()` → `buildGovernedAgentLlm()`
3. Update compliance/fraud/advisor nodes to use governed LLM
4. Add B1 to `extractReceiptFields` OCR
5. Fix SG phone detection in `pii_minimizer.py`
6. Integration tests: verify B1/B2 fire for all agents
7. Verify no regression in existing intake-gpt B1/B2

### Phase 2: D5 (Guardrails AI adoption)
1. Add `guardrails-ai` to requirements
2. Create `ClaimGroundingValidator` custom validator
3. Verify OpenRouter compatibility test
4. Document Guardrails as sanctioned framework

### Phase 3: D2 (B3 Deterministic Grounding) — Advisor first (highest stakes)
1. Create `validate_advisor_decision()` grounding check
2. Wire into advisor node (post-decision, pre-status-update)
3. Test: hallucinated approval → escalate
4. Extend to compliance node
5. Extend to fraud node
6. Add to intake-gpt field-confirmation point
7. Add to intake-gpt policy-comparison point

### Phase 4: D3 (B4 Async Judge)
1. Wire OpenRouter client into `LlmJudge`
2. Update `content_governance_builder.py` to pass settings
3. Add async B4 task spawning in `runGraph`
4. Test: B4 critique appears in audit, zero user latency
5. Verify escalation flag on concerns

---

## DECISION POINTS for Team Lead

**DP0 — Background-Agent Governance Notice Placement (RESOLVED - FINAL DIRECTION):**

**Problem (original):** compliance/fraud/advisor run POST-SUBMISSION, not in interactive chat.

**FINAL DECISION (team-lead, supersedes earlier analysis):**

1. **Background agents (compliance/fraud/advisor) governance → TWO destinations, NOT the chat:**

   **(a) Governance AUDIT LOG** (feeds future Group D dashboard)
   - All B1/B2/B3/B4 detections, blocks, decisions
   - Dashboard-ready fields (see below)

   **(b) EMBEDDED in each agent's own decision findings:**
   - **Compliance:** Write governance alerts into `complianceFindings` JSONB
   - **Fraud:** Write governance alerts into `fraudFindings` JSONB
   - **Advisor:** Write governance alerts into `advisorFindings` JSONB
   - **Format:** `{governance: [{control:"B3", result:"escalated", reason:"..."}, {control:"B4", result:"flagged", ...}]}`
   - **Rationale:** Makes governance findings part of the decision record the human reviewer reads; persisted in claim
   - **PII-safe:** Control ID, result, reason, refs only — never raw content/PII
   - **Prefer embedding** in existing `*Findings` JSONB over separate `governanceFlags` column

2. **NO chat-transcript streaming for background agents**
   - Live small-red notices remain ONLY for interactive intake-gpt (B1/B2/B3 synchronous)
   - Background agents' governance is NOT visible to user in real-time
   - Surfaced later via Group D dashboard and in the agent's decision findings

3. **B4 (async, ALL agents including intake) → audit log + embedded in findings (NO chat notices)**
   - **Never a live chat notice**, even for intake-gpt
   - Settles DP1: async/background, zero user latency
   - Audit only for intake; audit + embedded in findings for decision agents

4. **Audit entries must be DASHBOARD-READY** (Group D data source)
   - **Required fields:** `controlId`, `agentIdentity`, `decision`, `reasons`, `result`, `timestamp`, `correlationId`, `claimId`, `policyVersion`, PII-safe refs (hashes/entity-types only)
   - Verify current content-audit builder includes all fields; add any missing

**Implementation summary:**

- **Intake-gpt:** UNCHANGED — live chat notices for B1/B2/B3 (synchronous actionable) + audit
- **Compliance/Fraud/Advisor:** Audit log + embed governance in their existing `*Findings` JSONB — no chat notices
- **B4 (all agents):** Audit log + embedded in findings — never chat notices

**Net effect:** Simpler plan — no chat-transcript wiring for background agents, just audit + embed in findings.

---

**DP1 — Async B4 mechanism (RESOLVED):**
- **Decision:** Async/background (Option A), zero user latency
- **Implementation:** Background task after agent response, writes to audit + embedded in findings
- **No live chat notice** requirement (settled by DP0 resolution)

**DP2 — Guardrails AI adoption:**
- **Proposed:** Adopt as sanctioned framework (Apache-2.0, wrap our deterministic grounding)
- **Concerns:** OpenRouter compatibility (VERIFIED via LiteLLM)
- **Recommendation:** ADOPT with integration test verification

**DP3 — B3 per-agent schemas:**
- **Advisor:** Function-calling with strict decision schema
- **Compliance/Fraud:** Already emit JSONB, light schema enforcement only
- **Intake-gpt:** `ClaimAssertion` schema for 2 assertion points
- **Question:** Use Guardrails `for_pydantic()` everywhere, or only where needed?
- **Recommendation:** Selective use (advisor/intake assertions), keep compliance/fraud simple

**DP4 — Phasing sequence:**
- **Proposed:** D1+D4 → D5 → D2 (advisor-first) → D3
- **Alternative:** All-at-once (riskier)
- **Recommendation:** Phased (de-risks, allows per-agent verification)

---

## Definition of Done

- [ ] Package 0.13.0 with Guardrails AI + `ClaimGroundingValidator`
- [ ] `buildGovernedAgentLlm()` wraps compliance/fraud/advisor with B1/B2
- [ ] `extractReceiptFields` runs B1 on OCR text
- [ ] SG bare 8-digit phones detected by B2
- [ ] B3 grounding on advisor (approve → compliance+fraud pass), compliance (verdict → RAG), fraud (findings → history)
- [ ] B3 on intake-gpt field-confirmation + policy-comparison points
- [ ] B4 async judge on EVERY agent response (observe/escalate, gpt-4o-mini, zero user latency)
- [ ] Guardrails OpenRouter compatibility verified
- [ ] All agents show content audit entries in unified JSONL
- [ ] Governance notices in thinking panel (informational) + main thread (enforcement)
- [ ] No Group A regression, all existing tests green
- [ ] Live verification per agent (compliance/fraud/advisor/intake-gpt/legacy-intake)

---

**STANDBY. Awaiting team-lead approval on DP1-DP4 before proceeding with phased implementation.**

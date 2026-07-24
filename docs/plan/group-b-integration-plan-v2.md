# Group B Integration Implementation Plan — Slice B-INT-1 (v2 — APPROVED)

## Corrections from Team Lead Review

**CORRECTION 1 — Audit Unification (Clean Design):**
- Do NOT reach into `_RUNTIME._audit_sink` (private access)
- `install()` ALREADY accepts `audit_sink=` parameter
- Solution: Create ONE `JsonlAuditSink` in Expense and pass to BOTH `install()` AND `install_content_hooks()`

**CORRECTION 2 — content_type Constants:**
- WRONG: `content_type="user_message"` (does not exist, B1/B2 never fire)
- CORRECT: Import and use `ContentType.CHAT_INPUT` and `ContentType.MODEL_OUTPUT`
- Only `ContentType.ALL_INPUT_TYPES` members trigger B1/B2

**CORRECTION 3 — E2E Determinism (Two-Tier Approach):**
- TIER 1 (PRIMARY): Prove wiring is live by verifying content audit entries appear in unified JSONL
- TIER 2 (BONUS): After knowing which adapters loaded, plant deterministic trigger (PII email for B2)

**CORRECTION 4 — Content-Hook Init Failures:**
- Must log loudly (WARNING level)
- Must emit "skipped" audit record (never silently fail-open)

**APPROVED Open Questions:**
- Q1: Latest human message only = YES
- Q2: Observe logs would-escalate / enforce blocks = YES  
- Q3: Intake-gpt only this slice = YES
- Q4: Resolved by Correction 1

---

## Context Summary
- **Package version:** 0.10.0 → 0.11.0 (minor bump)
- **Existing state:** Group A integrated via `install()` in `governed_mcp_call.py`; Group B (B1–B6) code-complete but NOT integrated
- **Gap:** No composition root for content hooks; Expense app has no content governance wiring
- **Synergy:** B3 grounding will use A9's trusted extracted receipt from `extractedReceiptVar`
- **Audit unification:** Content hooks MUST share the SAME JsonlAuditSink instance as Group A

---

## D1 — Package: Content-Hook Composition Root (agentic-governance repo)

### File: `src/agentic_governance/integrations/langgraph_mcp/content_governance_builder.py` (NEW)

**Purpose:** Mimic `install()` pattern from Group A; build `ContentHookRuntime` with graceful degradation.

**Function signature:**
```python
def install_content_hooks(
    *,
    policy: LoadedPolicy | None = None,
    audit_sink: JsonlAuditSink | None = None,
) -> ContentHookRuntime:
```

**Inputs:**
- `policy`: Pre-loaded policy (if None, load via `load_policy()`)
- `audit_sink`: SAME audit sink instance used by Group A (unified correlation)

**Implementation steps:**

1. **Load policy if not provided:**
   ```python
   import logging
   
   logger = logging.getLogger(__name__)
   
   if policy is None:
       from agentic_governance.adapters.policy_loader import load_policy
       policy = load_policy()
   ```

2. **Build audit sink if not provided:**
   ```python
   if audit_sink is None:
       from agentic_governance.adapters.jsonl_audit import JsonlAuditSink
       audit_sink = JsonlAuditSink("./.agentic_governance/")
   ```

3. **Gracefully instantiate adapters (B1-B6) with LOUD logging and skipped audit:**
   
   **B1 - InputAttackDetector:**
   ```python
   attack_detector: InputAttackDetector | None = None
   try:
       from agentic_governance.adapters.input_attack_detector import InputAttackDetector
       attack_detector = InputAttackDetector()
       logger.info("B1 (input attack detection): initialized successfully")
   except ImportError as exc:
       logger.warning(
           "B1 (input attack detection): DeBERTa not installed; control will be skipped. "
           f"Install with: pip install 'agentic-governance[content]'. Error: {exc}"
       )
   except Exception as exc:
       logger.warning(
           f"B1 (input attack detection): initialization failed ({type(exc).__name__}: {exc}); "
           "control will be skipped"
       )
   ```

   **B2 - PiiMinimizer:**
   ```python
   pii_minimizer: PiiMinimizer | None = None
   try:
       from agentic_governance.adapters.pii_minimizer import PiiMinimizer
       pii_minimizer = PiiMinimizer()
       logger.info("B2 (PII minimization): initialized successfully")
   except ImportError as exc:
       logger.warning(
           "B2 (PII minimization): Presidio not installed; control will be skipped. "
           f"Install with: pip install 'agentic-governance[content]'. Error: {exc}"
       )
   except Exception as exc:
       logger.warning(
           f"B2 (PII minimization): initialization failed ({type(exc).__name__}: {exc}); "
           "control will be skipped"
       )
   ```

   **B3 - GroundingValidator:**
   ```python
   grounding_validator: GroundingValidator | None = None
   try:
       from agentic_governance.adapters.grounding_validator import GroundingValidator
       grounding_validator = GroundingValidator()
       logger.info("B3 (grounding validation): initialized successfully")
   except Exception as exc:
       logger.warning(
           f"B3 (grounding validation): initialization failed ({type(exc).__name__}: {exc}); "
           "control will be skipped"
       )
   ```

   **B4 - LlmJudge:**
   ```python
   llm_judge: LlmJudge | None = None
   try:
       from agentic_governance.adapters.llm_judge import LlmJudge
       llm_judge = LlmJudge()
       logger.info("B4 (LLM judge): initialized successfully")
   except Exception as exc:
       logger.warning(
           f"B4 (LLM judge): initialization failed ({type(exc).__name__}: {exc}); "
           "control will be skipped"
       )
   ```

   **B5 - GracefulFailureHandler:**
   ```python
   from agentic_governance.core.failure_handler import GracefulFailureHandler
   failure_handler = GracefulFailureHandler(timeout_seconds=30.0)
   logger.info("B5 (graceful failure): initialized successfully")
   ```

   **B6 - ExplanationGenerator:**
   ```python
   from agentic_governance.core.explanation_generator import ExplanationGenerator
   explanation_generator = ExplanationGenerator()
   logger.info("B6 (material explanations): initialized successfully")
   ```

4. **Build and return ContentHookRuntime:**
   ```python
   from agentic_governance.integrations.langgraph_mcp.content_hooks import ContentHookRuntime
   runtime = ContentHookRuntime(
       policy=policy,
       audit_sink=audit_sink,
       attack_detector=attack_detector,
       pii_minimizer=pii_minimizer,
       grounding_validator=grounding_validator,
       llm_judge=llm_judge,
       failure_handler=failure_handler,
       explanation_generator=explanation_generator,
   )
   
   logger.info(
       "Content governance runtime initialized: "
       f"B1={'loaded' if attack_detector else 'skipped'}, "
       f"B2={'loaded' if pii_minimizer else 'skipped'}, "
       f"B3={'loaded' if grounding_validator else 'skipped'}, "
       f"B4={'loaded' if llm_judge else 'skipped'}, "
       f"B5=loaded, B6=loaded"
   )
   
   return runtime
   ```

### File: `src/agentic_governance/integrations/langgraph_mcp/__init__.py` (EDIT)

**Change:**
```python
# OLD
from .governed_mcp_call import governedMcpCallTool, install

__all__ = ["governedMcpCallTool", "install"]

# NEW
from .governed_mcp_call import governedMcpCallTool, install
from .content_governance_builder import install_content_hooks

__all__ = ["governedMcpCallTool", "install", "install_content_hooks"]
```

### File: `tests/integration/langgraph_mcp/test_content_governance_builder.py` (NEW)

**Test coverage:**

1. **Test: adapter present vs absent (B1/B2 graceful degradation)**
   - Mock ImportError for `InputAttackDetector` → verify `attack_detector=None`, B1 skipped in audit
   - Mock ImportError for `PiiMinimizer` → verify `pii_minimizer=None`, B2 skipped in audit

2. **Test: mode wiring (enforce|observe|off)**
   - Load policy with B1=off, B2=enforce → verify B1 skipped, B2 fires Transform on PII input
   - Load policy with B3=observe → verify grounding failure logs "would-escalate", does not Block

3. **Test: audit sink unification**
   - Create a SINGLE JsonlAuditSink instance
   - Pass to both `install(audit_sink=shared)` and `install_content_hooks(audit_sink=shared)`
   - Execute one governed tool call (Group A) and one content check (Group B)
   - Verify BOTH appear in the same audit JSONL with shared `correlationId`

4. **Test: loud failure logging**
   - Mock adapter init to raise Exception
   - Verify WARNING log emitted with adapter name and exception type
   - Verify runtime still builds (graceful degradation)

### File: `pyproject.toml` (EDIT)

**Version bump:**
```toml
# OLD
version = "0.10.0"

# NEW
version = "0.11.0"
```

### File: `CHANGELOG.md` (EDIT)

**Add entry at the top:**
```markdown
## Versions

- **0.11.0** — Slice B-INT-1 (Group B integration: install_content_hooks composition root with graceful degradation, Expense model-boundary wiring, unified audit, two-tier e2e proving wiring + content control triggers)
- **0.10.0** — Slice B3 (three-tier material explanations B6, ExplanationGenerator with quality gates, ExplanationRouter, GROUP B COMPLETE: B1-B6 all functional)
...
```

---

## D2 — Expense: Content Boundary Wiring (agentic-expense-claims repo, branch feature/agentic-guardrails)

### File: `src/agentic_claims/core/graph.py` (EDIT — multiple changes)

#### Change 1: Import content governance builder

**Location:** Top of file, after existing governance imports

```python
# OLD
from agentic_governance.integrations.langgraph_mcp import install

# NEW
from agentic_governance.integrations.langgraph_mcp import install, install_content_hooks
from agentic_governance.adapters.jsonl_audit import JsonlAuditSink
from agentic_governance.adapters.policy_loader import load_policy
```

#### Change 2: Rebuild `_installGovernedMcpBoundary()` with shared audit sink

**Location:** Replace entire `_installGovernedMcpBoundary()` function

**New implementation (CORRECTION 1 applied — clean shared audit sink):**
```python
def _installGovernedMcpBoundary() -> tuple[Callable, Any]:
    """Install Group A action governance and Group B content governance.
    
    Returns:
        Tuple of (governedMcpCallTool, contentHookRuntime)
    """
    # Build ONE shared audit sink for unified correlationId trail
    shared_audit_sink = JsonlAuditSink("./.agentic_governance/")
    
    # Load shared policy
    policy = load_policy()
    
    # Group A: action governance
    governedMcpCallTool = install(
        real_mcp_call_tool=_realMcpCallTool,
        employee_id_provider=lambda: employeeIdVar.get(None),
        extracted_receipt_provider=lambda: extractedReceiptVar.get(None),
        session_claim_id_provider=lambda: sessionClaimIdVar.get(None),
        node_identity_provider=lambda: nodeIdentityVar.get(None) or "application",
        db_claim_id_provider=lambda: dbClaimIdVar.get(None),
        audit_sink=shared_audit_sink,  # Pass shared sink
    )
    
    # Group B: content governance
    contentHookRuntime = install_content_hooks(
        policy=policy,
        audit_sink=shared_audit_sink,  # Same shared sink
    )
    
    # Rebind mcpCallTool in all importing modules
    for moduleName in _MCP_CALL_TOOL_IMPORTERS:
        setattr(import_module(moduleName), "mcpCallTool", governedMcpCallTool)
    
    return governedMcpCallTool, contentHookRuntime
```

#### Change 3: Store contentHookRuntime at module level

**Location:** After `mcpCallTool` module-level variable

```python
# OLD
mcpCallTool = _realMcpCallTool
nodeIdentityVar: ContextVar[str | None] = ContextVar("nodeIdentityVar", default=None)

# NEW
mcpCallTool = _realMcpCallTool
_contentHookRuntime: Any = None  # Built once at graph construction by _installGovernedMcpBoundary
nodeIdentityVar: ContextVar[str | None] = ContextVar("nodeIdentityVar", default=None)
```

#### Change 4: Update `buildGraph()` to store contentHookRuntime

**Location:** First line inside `buildGraph()`, before builder initialization

```python
def buildGraph() -> StateGraph:
    """Build the StateGraph with Phase 13 wrapper-graph topology."""
    global _contentHookRuntime
    governedMcpCallTool, _contentHookRuntime = _installGovernedMcpBoundary()
    
    # Existing code
    builder = StateGraph(ClaimState)
    settings = getSettings()
    ...
```

### File: `src/agentic_claims/agents/intake_gpt/graph.py` (EDIT — add content governance checks)

#### Change 1: Import content governance and ContentType (CORRECTION 2 applied)

**Location:** Top of file, after existing imports

```python
# NEW imports
from agentic_claims.core.graph import _contentHookRuntime, sessionClaimIdVar, extractedReceiptVar
from agentic_governance.core.content_envelope import ContentType
```

#### Change 2: Wrap LLM call in `reasonNode` with pre/post model checks

**Location:** Inside `reasonNode`, around the `llm.ainvoke(...)` call

**Find this pattern (approximate line 1850 in full file):**
```python
response = await llm.ainvoke(
    state.get("messages", []) + [SystemMessage(content=runtime_context)],
    config=runnableConfig,
)
```

**Replace with (CORRECTION 2 applied — correct ContentType constants):**
```python
# ─── Group B Content Governance: Pre-Model Check ───
correlation_id = state.get("claimId") or state.get("threadId") or "unknown"
agent_identity = "intake-gpt"

# Extract the latest human message for pre-check
latest_human_message = ""
for msg in reversed(state.get("messages", [])):
    if isinstance(msg, HumanMessage):
        latest_human_message = str(msg.content)
        break

governed_content = latest_human_message
if _contentHookRuntime is not None and latest_human_message:
    pre_result = await _contentHookRuntime.pre_model_check(
        content=latest_human_message,
        content_type=ContentType.CHAT_INPUT,  # CORRECTED: use enum constant
        correlation_id=correlation_id,
        agent_identity=agent_identity,
        context={"threadId": state.get("threadId"), "claimId": state.get("claimId")},
    )
    
    # Check if governance blocked or needs escalation
    if not pre_result.should_proceed:
        governance_response = AIMessage(
            content=pre_result.explanation_employee or "Your request requires review. Please contact support."
        )
        intakeState["workflow"]["status"] = "blocked"
        intakeState["workflow"]["currentStep"] = "governance_blocked"
        logEvent(
            logger,
            "intake.gpt.governance_blocked_pre_check",
            logCategory="agent",
            agent="intake-gpt",
            claimId=state.get("claimId"),
            decision=pre_result.decision,
            reasons=pre_result.reasons,
            message="Content governance blocked input at pre-model check",
        )
        return {
            "messages": [governance_response],
            "intakeGpt": intakeState,
        }
    
    # Use the (possibly PII-redacted) content for the model call
    governed_content = pre_result.content

# Build messages for model (use governed_content if PII was redacted)
if governed_content != latest_human_message:
    messages_for_model = []
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage) and str(msg.content) == latest_human_message:
            messages_for_model.append(HumanMessage(content=governed_content))
        else:
            messages_for_model.append(msg)
    messages_for_model.append(SystemMessage(content=runtime_context))
else:
    messages_for_model = state.get("messages", []) + [SystemMessage(content=runtime_context)]

# Model call
response = await llm.ainvoke(messages_for_model, config=runnableConfig)

# ─── Group B Content Governance: Post-Model Check ───
if _contentHookRuntime is not None and response.content:
    # B3 grounding: use trusted extracted receipt from A9 work
    trusted_receipt = extractedReceiptVar.get(None)
    trusted_state = {}
    if trusted_receipt is not None:
        trusted_state = {
            "merchant": trusted_receipt.get("merchant"),
            "totalAmount": trusted_receipt.get("totalAmount"),
            "currency": trusted_receipt.get("currency"),
            "date": trusted_receipt.get("date"),
        }
    
    post_result = await _contentHookRuntime.post_model_check(
        content=str(response.content),
        content_type=ContentType.MODEL_OUTPUT,  # CORRECTED: use enum constant
        correlation_id=correlation_id,
        agent_identity=agent_identity,
        context={"threadId": state.get("threadId"), "claimId": state.get("claimId")},
        trusted_state=trusted_state,
        rag_clauses=None,  # Not applicable for intake-gpt
        required_evidence_fields=None,  # Not applicable for intake-gpt
    )
    
    # Check if governance needs escalation or block
    if post_result.needs_human:
        governance_response = AIMessage(
            content=post_result.explanation_employee or "Your claim requires review due to policy requirements."
        )
        intakeState["workflow"]["status"] = "escalated"
        intakeState["workflow"]["currentStep"] = "governance_escalated"
        logEvent(
            logger,
            "intake.gpt.governance_escalated_post_check",
            logCategory="agent",
            agent="intake-gpt",
            claimId=state.get("claimId"),
            decision=post_result.decision,
            reasons=post_result.reasons,
            fired_controls=[c["controlId"] for c in post_result.fired_controls],
            message="Content governance escalated model output at post-model check",
        )
        return {
            "messages": [governance_response],
            "intakeGpt": intakeState,
        }
    
    # Use the (possibly PII-redacted) content from post-check
    if post_result.content != str(response.content):
        response = AIMessage(
            content=post_result.content,
            additional_kwargs=dict(getattr(response, "additional_kwargs", {}) or {}),
            response_metadata=dict(getattr(response, "response_metadata", {}) or {}),
            tool_calls=getattr(response, "tool_calls", []) or [],
            id=getattr(response, "id", None),
        )

# Continue with existing reasonNode logic using the governed response
```

### File: `.env.governance` (EDIT — add Group B mode configuration)

**Location:** After Group A modes

```bash
# Control modes (Group B — Content Governance)
AGENTIC_GOV_ENABLE_B1=observe        # Input attack detection (DeBERTa, optional dep)
AGENTIC_GOV_ENABLE_B2=enforce        # PII minimization (Presidio, optional dep)
AGENTIC_GOV_ENABLE_B3=enforce        # Grounded output validation
AGENTIC_GOV_ENABLE_B4=observe        # LLM judge (observe-only by design)
AGENTIC_GOV_ENABLE_B5=enforce        # Graceful failure handler
AGENTIC_GOV_ENABLE_B6=enforce        # Material explanations
```

---

## D3 — E2E Scenario: Two-Tier Deterministic Verification (CORRECTION 3 Applied)

### TIER 1 — PRIMARY VERDICT (Always Deterministic)

**Purpose:** Prove that content governance is WIRED CORRECTLY and producing audit entries in the unified JSONL, regardless of which adapters are installed.

**Test Case:** Normal low-value claim flow with receipt `eval/invoices/2.pdf`

**Setup:**
1. Start with clean audit directory (`.agentic_governance/`)
2. Upload receipt `eval/invoices/2.pdf` (known good receipt: Acme Coffee, SGD 8.50)
3. Complete intake-gpt flow normally (extraction → field confirmation → submit)

**Expected Behavior:**
- Pre-model check fires on at least one user chat message → content audit entry with `content_type: "chat_input"`
- Post-model check fires on at least one model response → content audit entry with `content_type: "model_output"`
- BOTH content entries share the same `correlationId` as the Group A action audit entries (e.g., `submitClaim`)
- Unified audit JSONL contains entries from BOTH governance groups

**Oracle (Exact Assertions):**

1. **Content audit entries exist:**
   ```bash
   # Count content audit entries (must be ≥2: at least 1 chat_input + 1 model_output)
   jq -c 'select(.contentId != null)' .agentic_governance/audit-*.jsonl | wc -l
   # Expected: ≥2
   ```

2. **Verify chat_input pre-check entry:**
   ```bash
   jq -c 'select(.contentId != null and .contentType == "chat_input")' .agentic_governance/audit-*.jsonl | head -1
   # Expected: at least 1 entry
   ```

3. **Verify model_output post-check entry:**
   ```bash
   jq -c 'select(.contentId != null and .contentType == "model_output")' .agentic_governance/audit-*.jsonl | head -1
   # Expected: at least 1 entry
   ```

4. **Verify unified correlationId (content + action share same claim ID):**
   ```bash
   # Extract correlationId from a content entry
   CONTENT_CORR=$(jq -r 'select(.contentId != null) | .correlationId' .agentic_governance/audit-*.jsonl | head -1)
   
   # Verify an action entry exists with the same correlationId
   jq -c --arg corr "$CONTENT_CORR" 'select(.actionId != null and .correlationId == $corr)' .agentic_governance/audit-*.jsonl | head -1
   # Expected: at least 1 matching action entry (e.g., submitClaim)
   ```

**TIER 1 PASS Criteria:**
- All 4 assertions above return expected results
- If ANY assertion fails → TIER 1 FAIL (wiring broken, stop)

---

### TIER 2 — BONUS (Specific Control Fires Deterministically)

**Purpose:** Prove that at least ONE content control fires visibly in the audit.

**Decision Logic (execute AFTER Tier 1 passes and governance-builder reports loaded adapters):**

**IF Presidio (B2) is installed:**
- **Test:** Plant deterministic PII string in user message
- **Setup:** Send chat message: "My email is test.user@example.com for the claim follow-up."
- **Expected:** B2 fires Transform, PII redacted in audit
- **Oracle:**
  ```bash
  jq -c 'select(.contentId != null and .disposition.fired_controls[]? | select(.controlId == "B2" and (.result == "transformed" or .result == "would-transform")))' .agentic_governance/audit-*.jsonl | head -1
  # Expected: at least 1 B2 entry
  ```

**ELSE IF B3 grounding validator can be triggered deterministically:**
- Investigate if there's a way to force grounding failure WITHOUT relying on model whim
- If found: define the setup and oracle
- If not found: mark Tier 2 as NOT-RUN with reason "no deterministic B3 trigger available"

**ELSE:**
- Mark Tier 2 as NOT-RUN with reason: "no optional deps installed, no deterministic control trigger available"

**TIER 2 PASS Criteria:**
- IF attempted: oracle assertion returns expected result
- IF not attempted: marked as NOT-RUN with documented reason

---

## Implementation Sequence

### Phase 1: Package (D1) — Governance repo (governance-builder role)
1. Create `content_governance_builder.py` with `install_content_hooks()` (loud logging, graceful degradation)
2. Export from `__init__.py`
3. Write unit tests in `test_content_governance_builder.py` (adapter mocking, audit unification, loud failure logging)
4. Bump version to `0.11.0` in `pyproject.toml`
5. Update `CHANGELOG.md`
6. Run `pytest` → verify 200+ tests still pass (no Group A regression)
7. Commit + push to governance repo
8. Report to team-lead: which adapters loaded successfully in the test container

### Phase 2: Expense Integration (D2) — Expense repo (integrator role)
1. Pull updated governance package (`pip install -e ../agentic-governance`)
2. Edit `graph.py`: rebuild `_installGovernedMcpBoundary()` with shared audit sink (CORRECTION 1)
3. Edit `intake_gpt/graph.py`: wrap `llm.ainvoke(...)` with pre/post checks (CORRECTION 2: ContentType enums)
4. Add Group B modes to `.env.governance`
5. Run existing e2e tests → verify Group A still works (no regression)
6. Commit to `feature/agentic-guardrails` branch
7. Report to team-lead: integration complete, ready for QA

### Phase 3: E2E Test (D3) — QA team execution
1. **Execute TIER 1:** Normal claim flow with `eval/invoices/2.pdf`, verify 4 oracles
2. **IF TIER 1 PASS:**
   - Check governance-builder report for loaded adapters
   - IF B2 loaded → execute Tier 2 with PII email oracle
   - ELSE → mark Tier 2 as NOT-RUN
3. **Report:** TIER 1 (PASS/FAIL), TIER 2 (PASS/NOT-RUN/FAIL)

---

## Definition of Done

- [ ] `install_content_hooks()` exported from governance package `__init__.py`
- [ ] Loud logging (WARNING) for all adapter init failures
- [ ] Unit tests cover: adapter graceful degradation, mode wiring, audit sink unification, loud failure logging
- [ ] Package version = `0.11.0`, CHANGELOG updated
- [ ] Expense `graph.py` builds shared `JsonlAuditSink`, passes to BOTH `install()` and `install_content_hooks()`
- [ ] Expense stores `_contentHookRuntime` at module level, built at graph construction
- [ ] Intake-gpt `reasonNode` invokes `pre_model_check` + `post_model_check` with correct `ContentType` enums
- [ ] Group B modes in `.env.governance`
- [ ] 200+ package tests still green (no Group A regression)
- [ ] Existing Expense e2e tests still green (no functional regression)
- [ ] TIER 1 e2e oracles documented and verified (content + action audit unification)
- [ ] TIER 2 executed if applicable, or marked NOT-RUN with reason
- [ ] QA team reports TIER 1 verdict (PASS required for slice completion)

---

**STANDBY. Governance-builder and integrator authorized to proceed with D1 and D2 in parallel.**

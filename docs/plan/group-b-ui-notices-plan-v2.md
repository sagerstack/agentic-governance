# Governance UI Notices Implementation Plan — Slice B-INT-2 (v2 — APPROVED)

## Team-Lead Decisions (Q1-Q4)

**Q1 — notice_callback injection (APPROVED):**
- **REJECTED:** Package importing from app (even optional/try-except)
- **APPROVED:** Injected `notice_callback` parameter in `install()` and `ContentHookRuntime.__init__()`
- Package builds notice lines via `format_control_notice()` and calls `notice_callback(lines)` if not None
- Expense provides callback that calls `append_notice()` into ContextVar queue
- **Direction:** Always app→package (dependency injection), never package→app

**Q2 — Verbose mode toggle (APPROVED):**
- Defer `AGENTIC_GOV_VERBOSE_NOTICES` to future slice
- Hardcode filtering: A6 never, A1-A12 only Deny/Escalate, B1-B6 all non-skipped

**Q3 — Observe mode wording (APPROVED):**
- Use **"Flagged (observe)"** for `would-escalate`/`would-deny`, NOT "Escalated (observe)"
- Nothing actually escalated in observe mode, so "Escalated" would be misleading
- Enforce mode: "Escalated" / "Blocked" (no suffix)

**Q4 — Two-channel rendering (APPROVED):**
- **Informational/observe notices** (B2 Redacted, B1 Flagged observe, action allows) → **thinking panel**
- **Enforcement interceptions** (B1 Escalated enforce, A5 Blocked, A7 Escalated) → **main thread** governance message (NOT AIMessage)

---

## Context Summary
- **Package version:** 0.11.0 → 0.12.0 (minor bump)
- **Goal:** Surface EVERY fired governance control to Expense chat UI as standardized notices
- **Scope:** Both content controls (B1–B6, model I/O) and action controls (A1–A12, tool calls)
- **Format:** `Governance control {ID} — {safeguard}. {Action}{detail}` (EXACT, no variation)
- **Constraint:** Notices are presentation-only (no decision/audit changes), no raw PII, package never imports app

---

## D1 — Package: Canonical Notice Formatter + Injected Callback Pattern (agentic-governance repo)

**CRITICAL CONSTRAINT:** The governance package must NEVER import from agentic_claims. Direction is always app→package via dependency injection.

### File: `src/agentic_governance/core/notice_formatter.py` (NEW)

**Purpose:** Single source of truth for control labels, verbs, and notice formatting.

#### Canonical Mappings (Constants)

```python
"""Canonical governance control notice formatter."""

from typing import Any

# Control ID → human-readable safeguard label
SAFEGUARD_LABELS = {
    "A1": "Governance envelope",
    "A2": "Payload integrity",
    "A3": "Identity verification",
    "A4": "Capability mandate",
    "A5": "Tool allowlist",
    "A6": "Deterministic disposition",
    "A7": "Exposure limit",
    "A8": "Rate/aggregate limit",
    "A9": "Evidence quality",
    "A10": "Trusted server / input schema",
    "A11": "Fail-closed floor",
    "A12": "Mediation",
    "B1": "Prompt injection",
    "B2": "PII redaction",
    "B3": "Output grounding",
    "B4": "LLM judge",
    "B5": "Graceful failure",
    "B6": "Explanation",
}

# Result/decision → action verb
# Q3 decision: "would-*" (observe mode) use "Flagged" to avoid misleading users
ACTION_VERBS = {
    "allowed": "Allowed",
    "observed": "Allowed",
    "verified": "Allowed",
    "transformed": "Redacted",
    "redacted": "Redacted",
    "would-transform": "Redacted",  # Observe mode still shows "Redacted" (informational)
    "escalate": "Escalated",
    "escalated": "Escalated",
    "would-escalate": "Flagged",  # Q3: "Flagged (observe)" not "Escalated (observe)"
    "deny": "Blocked",
    "denied": "Blocked",
    "blocked": "Blocked",
    "would-deny": "Flagged",  # Q3: "Flagged (observe)" not "Blocked (observe)"
    "skipped-disabled": "Skipped",
}
```

#### Function: `format_control_notice`

**Signature:**
```python
def format_control_notice(
    control_id: str,
    name: str,
    result: str,
    *,
    entity_types: list[str] | None = None,
    signal_value: float | None = None,
    reason: str | None = None,
) -> str:
    """Format a governance control firing into the canonical notice string.
    
    Args:
        control_id: e.g. "B2", "A7"
        name: e.g. "pii-minimization", "exposure-limits" (used for fallback label)
        result: e.g. "transformed", "escalated", "denied", "would-escalate", "allowed"
        entity_types: For B2 only — list of PII entity types (e.g. ["EMAIL_ADDRESS"])
        signal_value: For B1 only — injection score (0.0-1.0, show as percentage)
        reason: Optional (reserved for future use)
    
    Returns:
        Formatted notice: "Governance control {ID} — {safeguard}. {Action}{detail}"
    
    Examples:
        >>> format_control_notice("B2", "pii-minimization", "transformed", entity_types=["EMAIL_ADDRESS"])
        "Governance control B2 — PII redaction. Redacted (EMAIL_ADDRESS)"
        
        >>> format_control_notice("B1", "input-attack-detection", "escalated", signal_value=0.9999)
        "Governance control B1 — Prompt injection. Escalated (99.99%)"
        
        >>> format_control_notice("A7", "exposure-limits", "would-escalate")
        "Governance control A7 — Exposure limit. Flagged (observe)"
        
        >>> format_control_notice("A5", "tool-allowlist", "denied")
        "Governance control A5 — Tool allowlist. Blocked"
    """
```

**Implementation logic:**

1. **Resolve safeguard label:** `safeguard = SAFEGUARD_LABELS.get(control_id, name)`
2. **Resolve action verb:** `action = ACTION_VERBS.get(result.lower(), result.capitalize())`
3. **Build detail suffix:**
   - If B2 and entity_types: ` ({", ".join(entity_types)})`
   - If B1 and signal_value: ` ({signal_value * 100:.2f}%)`
   - If result starts with "would-": ` (observe)` — applies to Flagged outcomes only
   - Else: empty string
4. **Combine:** `f"Governance control {control_id} — {safeguard}. {action}{detail}"`

### File: `src/agentic_governance/integrations/langgraph_mcp/governed_mcp_call.py` (EDIT — add notice_callback parameter)

**Location:** `install()` function signature and `_GovernedMcpRuntime.__init__()`

#### Change 1: Add notice_callback parameter to install()

```python
# OLD signature
def install(
    *,
    real_mcp_call_tool: RealMcpCallTool,
    employee_id_provider: Callable[[], Any],
    extracted_receipt_provider: Callable[[], Any],
    session_claim_id_provider: Callable[[], Any],
    node_identity_provider: Callable[[], Any],
    db_claim_id_provider: Callable[[], Any] = lambda: None,
    engine: GovernanceEngine | None = None,
    audit_sink: Any | None = None,
    identity_registry: Any | None = None,
    mandate_store: Any | None = None,
) -> Callable[[str, str, dict[str, Any] | None], Awaitable[Any]]:

# NEW signature (add notice_callback)
def install(
    *,
    real_mcp_call_tool: RealMcpCallTool,
    employee_id_provider: Callable[[], Any],
    extracted_receipt_provider: Callable[[], Any],
    session_claim_id_provider: Callable[[], Any],
    node_identity_provider: Callable[[], Any],
    db_claim_id_provider: Callable[[], Any] = lambda: None,
    engine: GovernanceEngine | None = None,
    audit_sink: Any | None = None,
    identity_registry: Any | None = None,
    mandate_store: Any | None = None,
    notice_callback: Callable[[list[str]], None] | None = None,  # NEW
) -> Callable[[str, str, dict[str, Any] | None], Awaitable[Any]]:
```

#### Change 2: Pass notice_callback to _GovernedMcpRuntime

```python
_RUNTIME = _GovernedMcpRuntime(
    real_mcp_call_tool=real_mcp_call_tool,
    providers=providers,
    engine=engine,
    audit_sink=audit_sink,
    identity_registry=identity_registry,
    mandate_store=mandate_store,
    notice_callback=notice_callback,  # NEW
)
```

#### Change 3: Store and use notice_callback in _GovernedMcpRuntime

**Add to `__init__`:**
```python
self._notice_callback = notice_callback
```

**In `_record_and_dispatch()`, after `await self._record(envelope, disposition)`:**

```python
# Emit governance notices via injected callback (if provided)
if self._notice_callback is not None and disposition.fired_controls:
    from agentic_governance.core.notice_formatter import format_control_notice
    
    notices = []
    for control in disposition.fired_controls:
        # Skip A6 (deterministic-disposition) — too noisy, fires on every call
        if control.control_id == "A6":
            continue
        # Skip allowed/observed for action controls (A1-A12) unless it's a meaningful verification
        if control.control_id.startswith("A") and control.result in ("allowed", "observed"):
            continue
        # Skip skipped controls
        if control.result == "skipped-disabled":
            continue
        
        # Format notice
        notice = format_control_notice(
            control_id=control.control_id,
            name=control.name,
            result=control.result,
            signal_value=getattr(control, "signal_value", None),
        )
        notices.append(notice)
    
    if notices:
        self._notice_callback(notices)
```

### File: `src/agentic_governance/integrations/langgraph_mcp/content_hooks.py` (EDIT — add notice_callback parameter)

**Location:** `ContentHookRuntime.__init__` signature

#### Change 1: Add notice_callback parameter

```python
# OLD signature
def __init__(
    self,
    *,
    policy: LoadedPolicy,
    audit_sink: Any | None = None,
    attack_detector: InputAttackDetector | None = None,
    pii_minimizer: PiiMinimizer | None = None,
    grounding_validator: GroundingValidator | None = None,
    llm_judge: LlmJudge | None = None,
    failure_handler: GracefulFailureHandler | None = None,
    explanation_generator: ExplanationGenerator | None = None,
) -> None:

# NEW signature (add notice_callback)
def __init__(
    self,
    *,
    policy: LoadedPolicy,
    audit_sink: Any | None = None,
    attack_detector: InputAttackDetector | None = None,
    pii_minimizer: PiiMinimizer | None = None,
    grounding_validator: GroundingValidator | None = None,
    llm_judge: LlmJudge | None = None,
    failure_handler: GracefulFailureHandler | None = None,
    explanation_generator: ExplanationGenerator | None = None,
    notice_callback: Callable[[list[str]], None] | None = None,  # NEW
) -> None:
    # ... existing init code ...
    self._notice_callback = notice_callback  # NEW: store callback
```

#### Change 2: Emit notices in _emit_audit()

**Location:** Inside `_emit_audit()`, after the audit emission

```python
# Emit governance notices via injected callback (if provided)
if self._notice_callback is not None and disposition.fired_controls:
    from agentic_governance.core.notice_formatter import format_control_notice
    
    notices = []
    for control in disposition.fired_controls:
        # Skip skipped controls
        if control.result == "skipped-disabled":
            continue
        
        # Format notice (content controls show ALL non-skipped)
        notice = format_control_notice(
            control_id=control.control_id,
            name=control.name,
            result=control.result,
            entity_types=control.entity_types,
            signal_value=control.signal_value,
        )
        notices.append(notice)
    
    if notices:
        self._notice_callback(notices)
```

### File: `src/agentic_governance/integrations/langgraph_mcp/content_governance_builder.py` (EDIT — add notice_callback parameter)

**Update `install_content_hooks()` signature:**

```python
# OLD signature
def install_content_hooks(
    *,
    policy: LoadedPolicy | None = None,
    audit_sink: JsonlAuditSink | None = None,
) -> ContentHookRuntime:

# NEW signature (add notice_callback)
def install_content_hooks(
    *,
    policy: LoadedPolicy | None = None,
    audit_sink: JsonlAuditSink | None = None,
    notice_callback: Callable[[list[str]], None] | None = None,  # NEW
) -> ContentHookRuntime:
```

**Pass to ContentHookRuntime:**

```python
runtime = ContentHookRuntime(
    policy=policy,
    audit_sink=audit_sink,
    attack_detector=attack_detector,
    pii_minimizer=pii_minimizer,
    grounding_validator=grounding_validator,
    llm_judge=llm_judge,
    failure_handler=failure_handler,
    explanation_generator=explanation_generator,
    notice_callback=notice_callback,  # NEW
)
```

### File: `tests/unit/core/test_notice_formatter.py` (NEW)

**Test coverage:**

1. **Test: all control IDs have labels**
2. **Test: observe mode verbs** (Q3 decision)
   - `would-escalate` → "Flagged (observe)"
   - `would-deny` → "Flagged (observe)"
   - `escalated` → "Escalated"
   - `denied` → "Blocked"
3. **Test: B2 entity types detail**
4. **Test: B1 signal value detail**
5. **Test: simple cases (no detail)**

### File: `pyproject.toml` + `CHANGELOG.md` (version bump to 0.12.0)

---

## D2 + D3 — Expense: Governance Notices via Injected Callback (agentic-expense-claims repo)

### File: `src/agentic_claims/web/governanceNoticeContext.py` (NEW)

**Purpose:** Request-scoped queue for governance notices (fed by injected callback).

```python
"""Request-scoped governance notice queue for SSE emission."""

from contextvars import ContextVar

governanceNoticeQueueVar: ContextVar[list[str]] = ContextVar(
    "governanceNoticeQueueVar", default=None
)

def init_notice_queue() -> None:
    """Initialize an empty notice queue for this request."""
    governanceNoticeQueueVar.set([])

def append_notice(notice: str) -> None:
    """Append a governance notice to the current request's queue."""
    queue = governanceNoticeQueueVar.get(None)
    if queue is not None:
        queue.append(notice)

def drain_notices() -> list[str]:
    """Drain and return all pending notices, clearing the queue."""
    queue = governanceNoticeQueueVar.get(None)
    if queue is None:
        return []
    notices = list(queue)
    queue.clear()
    return notices
```

### File: `src/agentic_claims/core/graph.py` (EDIT — inject notice_callback into install() and install_content_hooks())

**Location:** Inside `_installGovernedMcpBoundary()`

```python
def _installGovernedMcpBoundary() -> tuple[Callable, Any]:
    """Install Group A action governance and Group B content governance.
    
    Returns:
        Tuple of (governedMcpCallTool, contentHookRuntime)
    """
    from agentic_claims.web.governanceNoticeContext import append_notice
    
    # Build ONE shared audit sink for unified correlationId trail
    shared_audit_sink = JsonlAuditSink("./.agentic_governance/")
    
    # Load shared policy
    policy = load_policy()
    
    # Define the notice callback that feeds into the ContextVar queue
    def notice_callback(notices: list[str]) -> None:
        """Injected callback: append governance notices to the request queue."""
        for notice in notices:
            append_notice(notice)
    
    # Group A: action governance (with injected callback)
    governedMcpCallTool = install(
        real_mcp_call_tool=_realMcpCallTool,
        employee_id_provider=lambda: employeeIdVar.get(None),
        extracted_receipt_provider=lambda: extractedReceiptVar.get(None),
        session_claim_id_provider=lambda: sessionClaimIdVar.get(None),
        node_identity_provider=lambda: nodeIdentityVar.get(None) or "application",
        db_claim_id_provider=lambda: dbClaimIdVar.get(None),
        audit_sink=shared_audit_sink,
        notice_callback=notice_callback,  # NEW: inject callback
    )
    
    # Group B: content governance (with same injected callback)
    contentHookRuntime = install_content_hooks(
        policy=policy,
        audit_sink=shared_audit_sink,
        notice_callback=notice_callback,  # NEW: inject callback
    )
    
    # Rebind mcpCallTool in all importing modules
    for moduleName in _MCP_CALL_TOOL_IMPORTERS:
        setattr(import_module(moduleName), "mcpCallTool", governedMcpCallTool)
    
    return governedMcpCallTool, contentHookRuntime
```

### File: `src/agentic_claims/web/routers/chat.py` (EDIT — initialize notice queue)

**Location:** Inside chat endpoint, before graph invocation

```python
from agentic_claims.web.governanceNoticeContext import init_notice_queue

# Before graph invocation
employeeIdVar.set(currentUser.employee_id)
sessionClaimIdVar.set(sessionId)
init_notice_queue()  # NEW: initialize notice queue for this request
```

### File: `src/agentic_claims/web/sseEvents.py` (EDIT — add SSE event types)

```python
class SseEvent:
    # ... existing events ...
    GOVERNANCE_NOTICE = "governance-notice"  # Informational → thinking panel
    GOVERNANCE_MESSAGE = "governance-message"  # Enforcement → main thread
```

### File: `src/agentic_claims/agents/intake_gpt/graph.py` (EDIT — replace AIMessage with governance state)

**Changes:**

1. **Import notice formatter (already using injected callback, so no need to manually format here)**
2. **Replace AIMessage returns with `governanceBlockMessage` in state**
3. **Informational notices already emitted via callback** (no manual append needed)

**Example transformation for pre_model_check block:**

```python
# OLD (WRONG — returns AIMessage)
if not pre_result.should_proceed:
    governance_response = AIMessage(
        content=pre_result.explanation_employee or "..."
    )
    return {"messages": [governance_response], "intakeGpt": intakeState}

# NEW (CORRECT — store message in state for SSE emission)
if not pre_result.should_proceed:
    intakeState["workflow"]["status"] = "blocked"
    intakeState["workflow"]["currentStep"] = "governance_blocked"
    
    # Collect enforcement notices (callback already emitted them to queue)
    # Just store a fallback message in case no notices were generated
    intakeState["governanceBlockMessage"] = (
        pre_result.explanation_employee or 
        "Your request requires review. Please contact support."
    )
    
    return {"intakeGpt": intakeState}  # NO AIMessage
```

### File: `src/agentic_claims/web/sseHelpers.py` (EDIT — drain notices + emit governance messages)

**Location:** Inside `runGraph`, in the main event loop

#### Change 1: Drain informational notices from queue

```python
from agentic_claims.web.governanceNoticeContext import drain_notices

# After processing each event
pending_notices = drain_notices()
for notice in pending_notices:
    # Emit to thinking panel (step-content style)
    yield ServerSentEvent(raw_data=notice, event=SseEvent.GOVERNANCE_NOTICE)
```

#### Change 2: Check for governance block messages in state

```python
# After a node completes (e.g., reasonNode)
if snapshot.values.get("intakeGpt", {}).get("governanceBlockMessage"):
    block_message = snapshot.values["intakeGpt"]["governanceBlockMessage"]
    # Emit as GOVERNANCE_MESSAGE (main thread, distinct from assistant)
    yield ServerSentEvent(raw_data=block_message, event=SseEvent.GOVERNANCE_MESSAGE)
    # Mark as done (no assistant response will follow)
    yield ServerSentEvent(raw_data="Governance intervention", event=SseEvent.DONE)
```

### File: `templates/chat.html` (EDIT — add SSE swap targets)

#### Change 1: Thinking panel governance notices

**Location:** Inside `#thinkingPanel`, after `thinkingContent`

```html
<div id="governanceNotices" sse-swap="governance-notice" hx-swap="beforeend"
     class="text-xs text-secondary/80 leading-relaxed mt-2 space-y-1 empty:hidden"></div>
```

#### Change 2: Main thread governance messages

**Location:** After `#aiMessages`, before `#doneTarget`

```html
<div id="governanceMessages" sse-swap="governance-message" hx-swap="beforeend"
     hx-on::after-swap="document.getElementById('chatHistory').scrollTop = document.getElementById('chatHistory').scrollHeight"
     class="space-y-6 empty:hidden"></div>
```

**Rendering pattern for GOVERNANCE_MESSAGE** (sseHelpers or template partial):
```html
<div class="flex gap-4 max-w-2xl">
  <div class="w-8 h-8 rounded-lg bg-tertiary-container flex items-center justify-center shrink-0 border border-tertiary/20">
    <span class="material-symbols-outlined text-tertiary text-sm" style="font-variation-settings: 'FILL' 1;">shield</span>
  </div>
  <div class="space-y-2">
    <div class="bg-tertiary-container/50 p-4 rounded-2xl rounded-tl-none border border-tertiary/10">
      <p class="text-on-tertiary-container text-sm leading-relaxed">[GOVERNANCE MESSAGE]</p>
    </div>
    <span class="text-[10px] text-outline px-1">Governance</span>
  </div>
</div>
```

---

## D4 — Review Checklist

- [ ] Package never imports from app (all notices via injected callback)
- [ ] Format correctness: Q3 decision ("Flagged (observe)" for would-*)
- [ ] No PII leakage (B2 shows entity types only)
- [ ] Two-channel rendering (informational → thinking, enforcement → main thread)
- [ ] Filtering logic (A6 never, A1-A12 only Deny/Escalate, B1-B6 all non-skipped)
- [ ] No regression (all tests green, Group A/B still work)
- [ ] No decision/audit changes (notices are presentation-only)

---

## Definition of Done

- [ ] Package 0.12.0 with `format_control_notice()`, injected `notice_callback` in both runtimes
- [ ] Expense `governanceNoticeContext.py` provides ContextVar queue
- [ ] Chat router calls `init_notice_queue()` before graph invocation
- [ ] `_installGovernedMcpBoundary()` injects `notice_callback` into both `install()` and `install_content_hooks()`
- [ ] `runGraph` drains queue → GOVERNANCE_NOTICE events → thinking panel
- [ ] `runGraph` checks `governanceBlockMessage` → GOVERNANCE_MESSAGE events → main thread
- [ ] Templates/chat.html has swap targets for both event types
- [ ] Manual demo: PII message → `Governance control B2 — PII redaction. Redacted (EMAIL_ADDRESS)` in thinking panel
- [ ] Manual demo: B1 enforce → `Governance control B1 — Prompt injection. Escalated (99.99%)` in main thread
- [ ] Manual demo: A7 observe → `Governance control A7 — Exposure limit. Flagged (observe)` in thinking panel
- [ ] All tests green, no regression

---

**STANDBY. Plan approved with Q1-Q4 decisions integrated. Awaiting authorization for builders to proceed with D1/D2/D3.**

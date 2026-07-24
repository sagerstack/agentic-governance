# Governance UI Notices Implementation Plan — Slice B-INT-2

## Context Summary
- **Package version:** 0.11.0 → 0.12.0 (minor bump)
- **Goal:** Surface EVERY fired governance control to Expense chat UI as standardized notices
- **Scope:** Both content controls (B1–B6, model I/O) and action controls (A1–A12, tool calls)
- **Format:** `Governance control {ID} — {safeguard}. {Action}{detail}` (EXACT, no variation)
- **Constraint:** Notices are presentation-only (no decision/audit changes), no raw PII

---

## D1 — Package: Canonical Notice Formatter (agentic-governance repo)

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
# Note: "would-escalate" / "would-deny" / "would-transform" map to same verb as enforce mode,
# but with "(observe)" suffix added by formatter logic
ACTION_VERBS = {
    "allowed": "Allowed",
    "observed": "Allowed",
    "verified": "Allowed",
    "transformed": "Redacted",
    "redacted": "Redacted",
    "would-transform": "Redacted",
    "escalate": "Escalated",
    "escalated": "Escalated",
    "would-escalate": "Escalated",
    "deny": "Blocked",
    "denied": "Blocked",
    "blocked": "Blocked",
    "would-deny": "Blocked",
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
    mode: str | None = None,
) -> str:
    """Format a governance control firing into the canonical notice string.
    
    Args:
        control_id: e.g. "B2", "A7"
        name: e.g. "pii-minimization", "exposure-limits" (not shown in notice, used for fallback)
        result: e.g. "transformed", "escalated", "denied", "allowed"
        entity_types: For B2 only — list of PII entity types found (e.g. ["EMAIL_ADDRESS", "PHONE_NUMBER"])
        signal_value: For B1 only — injection score (0.0-1.0, show as percentage if present)
        reason: Optional additional context (not currently used in format, reserved for future)
        mode: "observe" | "enforce" | "off" — adds "(observe)" suffix if mode=observe and result is would-*
    
    Returns:
        Formatted notice string: "Governance control {ID} — {safeguard}. {Action}{detail}"
    
    Examples:
        >>> format_control_notice("B2", "pii-minimization", "transformed", entity_types=["EMAIL_ADDRESS"])
        "Governance control B2 — PII redaction. Redacted (EMAIL_ADDRESS)"
        
        >>> format_control_notice("B1", "input-attack-detection", "escalated", signal_value=0.9999)
        "Governance control B1 — Prompt injection. Escalated (99.99%)"
        
        >>> format_control_notice("A5", "tool-allowlist", "denied")
        "Governance control A5 — Tool allowlist. Blocked"
        
        >>> format_control_notice("A7", "exposure-limits", "would-escalate", mode="observe")
        "Governance control A7 — Exposure limit. Escalated (observe)"
    """
```

**Implementation logic:**

1. **Resolve safeguard label:** `safeguard = SAFEGUARD_LABELS.get(control_id, name)`
2. **Resolve action verb:** `action = ACTION_VERBS.get(result.lower(), result.capitalize())`
3. **Build detail suffix:**
   - If B2 and entity_types: ` ({", ".join(entity_types)})`
   - If B1 and signal_value: ` ({signal_value * 100:.2f}%)`
   - If mode == "observe" and result starts with "would-": ` (observe)`
   - Else: empty string
4. **Combine:** `f"Governance control {control_id} — {safeguard}. {action}{detail}"`

### File: `tests/unit/core/test_notice_formatter.py` (NEW)

**Test coverage:**

1. **Test: all control IDs have labels**
   - Verify every A1–A12, B1–B6 has an entry in SAFEGUARD_LABELS

2. **Test: all result verbs map correctly**
   - allowed/observed/verified → Allowed
   - transformed/redacted → Redacted
   - escalate/escalated/would-escalate → Escalated
   - deny/denied/blocked → Blocked

3. **Test: B2 entity types detail**
   - `format_control_notice("B2", "pii-minimization", "transformed", entity_types=["EMAIL_ADDRESS", "PHONE_NUMBER"])`
   - Expected: `"Governance control B2 — PII redaction. Redacted (EMAIL_ADDRESS, PHONE_NUMBER)"`

4. **Test: B1 signal value detail**
   - `format_control_notice("B1", "input-attack-detection", "escalated", signal_value=0.9999)`
   - Expected: `"Governance control B1 — Prompt injection. Escalated (99.99%)"`

5. **Test: observe mode suffix**
   - `format_control_notice("A7", "exposure-limits", "would-escalate", mode="observe")`
   - Expected: `"Governance control A7 — Exposure limit. Escalated (observe)"`

6. **Test: no detail for simple cases**
   - `format_control_notice("A5", "tool-allowlist", "denied")`
   - Expected: `"Governance control A5 — Tool allowlist. Blocked"`

### File: `pyproject.toml` (EDIT)

**Version bump:**
```toml
# OLD
version = "0.11.0"

# NEW
version = "0.12.0"
```

### File: `CHANGELOG.md` (EDIT)

**Add entry at the top:**
```markdown
## Versions

- **0.12.0** — Slice B-INT-2 (Governance UI notices: canonical formatter for A1-A12 + B1-B6, surfaced to Expense chat UI as standardized notice lines)
- **0.11.0** — Slice B-INT-1 (Group B integration: install_content_hooks composition root with graceful degradation, Expense model-boundary wiring, unified audit, two-tier e2e proving wiring + content control triggers)
...
```

---

## D2 — Expense: Content-Control Notices (agentic-expense-claims repo, branch feature/agentic-guardrails)

### File: `src/agentic_claims/web/sseEvents.py` (EDIT)

**Add TWO new SSE event types for governance notices:**

```python
# OLD
class SseEvent:
    TOKEN = "token"
    THINKING_START = "thinking-start"
    STEP_NAME = "step-name"
    STEP_CONTENT = "step-content"
    THINKING_DONE = "thinking-done"
    MESSAGE = "message"
    SUMMARY_UPDATE = "summary-update"
    PATHWAY_UPDATE = "pathway-update"
    TABLE_UPDATE = "table-update"
    DONE = "done"
    ERROR = "error"
    INTERRUPT = "interrupt"

# NEW (add at the end)
    GOVERNANCE_NOTICE = "governance-notice"  # Informational notices → thinking panel (step-content style)
    GOVERNANCE_MESSAGE = "governance-message"  # Enforcement interceptions → main thread (distinct from AIMessage)
```

**Routing logic:**
- `GOVERNANCE_NOTICE`: Informational/observe outcomes (B2 redacted, B1 would-escalate, A1-A12 allowed) → rendered in the thinking panel via `step-content` swap
- `GOVERNANCE_MESSAGE`: Enforcement interceptions that block the turn (B1 escalated, A5 denied, A7 escalated) → rendered in main thread as a distinct governance bubble (NOT assistant style)

### File: `src/agentic_claims/agents/intake_gpt/graph.py` (EDIT — replace ad hoc "Flagged for review" with proper governance messages)

**Location:** Inside `reasonNode`, in the pre_model_check and post_model_check blocks

**UX REQUIREMENT (team-lead refinement):**
- DO NOT return AIMessage for governance blocks (that makes it look like the model said it)
- Enforcement interceptions store a `governanceBlockMessage` in state for runGraph to emit as GOVERNANCE_MESSAGE
- Informational notices go to the thinking panel via the ContextVar queue (unified D3 approach)

#### Change 1: Import notice formatter and queue (top of file)

```python
# NEW imports
from agentic_governance.core.notice_formatter import format_control_notice
from agentic_claims.web.governanceNoticeContext import append_notice
```

#### Change 2: Replace AIMessage with governance state for pre_model_check blocks

**Find (the existing block that returns AIMessage when governance blocks):**
```python
if not pre_result.should_proceed:
    governance_response = AIMessage(
        content=pre_result.explanation_employee or "Your request requires review. Please contact support."
    )
    intakeState["workflow"]["status"] = "blocked"
    intakeState["workflow"]["currentStep"] = "governance_blocked"
    logEvent(...)
    return {
        "messages": [governance_response],
        "intakeGpt": intakeState,
    }
```

**Replace with:**
```python
if not pre_result.should_proceed:
    # Governance blocked the input — DO NOT return an AIMessage (looks like the model said it)
    # Instead: mark state as blocked and store the governance message for SSE emission
    intakeState["workflow"]["status"] = "blocked"
    intakeState["workflow"]["currentStep"] = "governance_blocked"
    
    # Format enforcement notices from fired controls
    blocked_notices = []
    for control in pre_result.fired_controls:
        if control.get("result") in ("escalated", "denied", "blocked"):
            notice = format_control_notice(
                control_id=control.get("controlId", ""),
                name=control.get("name", ""),
                result=control.get("result", ""),
                entity_types=control.get("entityTypes"),
                signal_value=control.get("signalValue"),
            )
            blocked_notices.append(notice)
    
    # Store in state for SSE emission (runGraph will emit as GOVERNANCE_MESSAGE)
    intakeState["governanceBlockMessage"] = "\n".join(blocked_notices) if blocked_notices else (
        pre_result.explanation_employee or "Your request requires review. Please contact support."
    )
    
    logEvent(
        logger,
        "intake.gpt.governance_blocked_pre_check",
        logCategory="governance",
        agent="intake-gpt",
        claimId=state.get("claimId"),
        decision=pre_result.decision,
        reasons=pre_result.reasons,
        message="Content governance blocked input at pre-model check",
    )
    
    # Return state WITHOUT an AIMessage — runGraph will handle emission
    return {"intakeGpt": intakeState}
```

**Apply the same pattern to post_model_check** (find `if post_result.needs_human:` and apply identical transformation).

#### Change 3: Emit informational notices to thinking panel queue

**Insert AFTER extracting pre_result/post_result, BEFORE the block checks:**

```python
# Emit informational governance notices to the thinking panel (via ContextVar queue)
if pre_result.fired_controls:
    for control in pre_result.fired_controls:
        if control.get("result") == "skipped-disabled":
            continue  # Don't show skipped
        # Only emit informational notices (not enforcement interceptions)
        # Enforcement interceptions are handled via governanceBlockMessage above
        if control.get("result") in ("transformed", "redacted", "would-escalate", "would-deny", "allowed", "observed"):
            notice = format_control_notice(
                control_id=control.get("controlId", ""),
                name=control.get("name", ""),
                result=control.get("result", ""),
                entity_types=control.get("entityTypes"),
                signal_value=control.get("signalValue"),
            )
            append_notice(notice)  # Queue for runGraph to emit as GOVERNANCE_NOTICE
```

**Apply to both pre_result and post_result.**

### File: `src/agentic_claims/web/sseHelpers.py` (EDIT — emit governance notices and messages in runGraph)

**Location:** Inside `runGraph`, in the main event loop

#### Change 1: Drain informational notices from ContextVar queue

**Add periodic check after each event:**

```python
# Inside the main event loop, after processing an event
from agentic_claims.web.governanceNoticeContext import drain_notices

# Drain any governance notices accumulated during this event
pending_notices = drain_notices()
for notice in pending_notices:
    # Emit to thinking panel (step-content style)
    yield ServerSentEvent(raw_data=notice, event=SseEvent.GOVERNANCE_NOTICE)
```

#### Change 2: Check for governance block messages in state

**After a node completes (e.g., reasonNode), check if it set a `governanceBlockMessage`:**

```python
# After checking the snapshot/state from a node
if snapshot.values.get("intakeGpt", {}).get("governanceBlockMessage"):
    block_message = snapshot.values["intakeGpt"]["governanceBlockMessage"]
    # Emit as GOVERNANCE_MESSAGE (distinct from assistant, renders in main thread)
    yield ServerSentEvent(raw_data=block_message, event=SseEvent.GOVERNANCE_MESSAGE)
    # Mark as done (no assistant response will follow)
    yield ServerSentEvent(raw_data="Governance intervention", event=SseEvent.DONE)
```

### File: `templates/chat.html` (EDIT — add SSE swap targets for governance events)

**Purpose:** Render governance notices in the thinking panel and governance messages in the main thread.

#### Change 1: Add governance-notice swap target (thinking panel)

**Location:** Inside the thinking panel, after `thinkingContent`

```html
<!-- Inside #thinkingPanel, after the existing thinkingContent div -->
<div id="governanceNotices" sse-swap="governance-notice" hx-swap="beforeend"
     class="text-xs text-secondary/80 leading-relaxed mt-2 space-y-1 empty:hidden"></div>
```

**Styling:** Governance notices in the thinking panel should be visually distinct from tool steps:
- Color: secondary/80 (governance teal, slightly muted)
- Icon: optional shield/check icon prefix
- Font: slightly smaller than tool steps (text-xs)

#### Change 2: Add governance-message swap target (main thread)

**Location:** After `#aiMessages`, before `#doneTarget`

```html
<!-- Governance Messages (enforcement interceptions) -->
<div id="governanceMessages" sse-swap="governance-message" hx-swap="beforeend"
     hx-on::after-swap="document.getElementById('chatHistory').scrollTop = document.getElementById('chatHistory').scrollHeight"
     class="space-y-6 empty:hidden"></div>
```

**Rendering pattern for GOVERNANCE_MESSAGE:**
When `runGraph` emits a `governance-message` event, wrap it in a governance-styled bubble:

```html
<!-- Example governance message bubble (distinct from assistant) -->
<div class="flex gap-4 max-w-2xl">
  <div class="w-8 h-8 rounded-lg bg-tertiary-container flex items-center justify-center shrink-0 border border-tertiary/20">
    <span class="material-symbols-outlined text-tertiary text-sm" style="font-variation-settings: 'FILL' 1;">shield</span>
  </div>
  <div class="space-y-2">
    <div class="bg-tertiary-container/50 p-4 rounded-2xl rounded-tl-none border border-tertiary/10">
      <p class="text-on-tertiary-container text-sm leading-relaxed">[GOVERNANCE MESSAGE CONTENT]</p>
    </div>
    <span class="text-[10px] text-outline px-1">Governance</span>
  </div>
</div>
```

**Key visual distinctions:**
- Icon: shield (not smart_toy like assistant)
- Colors: tertiary palette (distinct from assistant's surface-container-low)
- Label: "Governance" timestamp (not "Just now" like assistant)

---

## D3 — Expense: Action-Control Notices (DECISION POINT — ContextVar Approach Proposed)

### Problem Statement

Surfacing A1–A12 dispositions from deep in the governance runtime (`governed_mcp_call.py`) to the SSE stream (`runGraph`) is non-trivial because:
- The governance runtime is invoked inside tool calls, which are buried in agent nodes
- `runGraph` is the SSE generator; it needs to yield `ServerSentEvent` for notices
- Threading a `notice_callback` through `install()` requires the callback to be request-scoped

### Proposed Approach: ContextVar Queue + runGraph Polling

**Why this approach:**
- **Minimal invasiveness:** Does NOT modify `install()` signature or `_GovernedMcpRuntime` internals
- **Request-safe:** ContextVar provides async-safe request isolation (same pattern as `employeeIdVar`)
- **Unified pattern:** Same mechanism can handle BOTH content notices (B1–B6) and action notices (A1–A12)

**How it works:**
1. Create a new `ContextVar[list[str]]` called `governanceNoticeQueueVar` in a new module `governanceNoticeContext.py`
2. Set it to an empty list at the start of each chat request (in the chat router, before graph invocation)
3. Governance runtimes (both action and content) append formatted notices to the queue when dispositions fire
4. `runGraph` periodically checks the queue (e.g., after each event) and yields any pending notices as SSE events
5. Clear the queue after emitting to avoid duplication

### Implementation Steps

#### File: `src/agentic_claims/web/governanceNoticeContext.py` (NEW)

**Purpose:** Request-scoped queue for governance notices.

```python
"""Request-scoped governance notice queue for SSE emission.

Set by chat router before graph invocation.
Appended by governance runtimes (action + content) when controls fire.
Read and cleared by runGraph SSE generator.
"""

from contextvars import ContextVar

# List of formatted notice strings accumulated during the request
governanceNoticeQueueVar: ContextVar[list[str]] = ContextVar(
    "governanceNoticeQueueVar",
    default=None,
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

#### File: `src/agentic_claims/web/routers/chat.py` (EDIT — initialize notice queue)

**Location:** Inside the chat endpoint, before graph invocation

**Find (approximate pattern):**
```python
employeeIdVar.set(currentUser.employee_id)
sessionClaimIdVar.set(sessionId)
```

**Add after:**
```python
from agentic_claims.web.governanceNoticeContext import init_notice_queue

init_notice_queue()
```

#### File: `src/agentic_claims/core/graph.py` (EDIT — append action notices from governance runtime)

**Location:** Inside `_installGovernedMcpBoundary`, AFTER `install()` call

**NEW approach (SIMPLIFIED — no callback threading):**

Instead of modifying `install()`, create a WRAPPER around `governedMcpCallTool` that intercepts the result and extracts notices from the audit.

**ALTERNATIVE DECISION POINT:** This requires post-hoc notice extraction from the disposition. A cleaner approach is to ADD notice emission directly inside `_GovernedMcpRuntime._record_and_dispatch()` in the governance package. This would be a D1 change (add to the package), not a D3 change.

**RECOMMENDED APPROACH (requires D1 addition):**

### D1 Addition: Add notice emission to governance runtimes

**File: `src/agentic_governance/integrations/langgraph_mcp/governed_mcp_call.py` (EDIT)**

**Add at top:**
```python
# NEW import (optional — if None, no notices are emitted)
try:
    from agentic_claims.web.governanceNoticeContext import append_notice
except ImportError:
    append_notice = None
```

**Location:** Inside `_GovernedMcpRuntime._record_and_dispatch()`, after `await self._record(envelope, disposition)`

**Add:**
```python
# Emit governance notices for fired controls (if context is available)
if append_notice is not None:
    from agentic_governance.core.notice_formatter import format_control_notice
    for control in disposition.fired_controls:
        # Skip A6 (deterministic-disposition) — too noisy, fires on every call
        if control.control_id == "A6":
            continue
        # Skip "allowed" results for action controls (A1-A12) unless verbose mode is on
        # For now, default: only show non-Allow outcomes for action controls
        if control.control_id.startswith("A") and control.result in ("allowed", "verified", "observed"):
            continue
        # Skip skipped controls (unless verbose mode is on)
        if control.result == "skipped-disabled":
            continue
        
        # Format and emit
        notice = format_control_notice(
            control_id=control.control_id,
            name=control.name,
            result=control.result,
            signal_value=getattr(control, "signal_value", None),
            reason=None,  # Not used in current format
        )
        append_notice(notice)
```

**CRITICAL DECISION POINT for team-lead:**

**Option 1 (RECOMMENDED):** Add the notice emission to the governance package (`governed_mcp_call.py`) as shown above. This keeps ALL governance logic in one place, and the Expense app just provides the queue via ContextVar.

**Option 2:** Keep governance package pure (no Expense-specific imports), and wrap `governedMcpCallTool` in Expense `graph.py` to extract notices from the return value. This requires a more invasive change to propagate dispositions.

**RECOMMENDATION:** Use Option 1 (add to package), but make it OPTIONAL — the import is wrapped in try/except, so the package still works standalone without the Expense app.

#### File: `src/agentic_governance/integrations/langgraph_mcp/content_hooks.py` (EDIT — emit content notices)

**Same pattern as action notices above:**

**Add at top:**
```python
# NEW import (optional)
try:
    from agentic_claims.web.governanceNoticeContext import append_notice
except ImportError:
    append_notice = None
```

**Location:** Inside `ContentHookRuntime._emit_audit()`, after the audit emission

**Add:**
```python
# Emit governance notices for fired controls (if context is available)
if append_notice is not None:
    from agentic_governance.core.notice_formatter import format_control_notice
    for control in disposition.fired_controls:
        # Skip skipped controls
        if control.result == "skipped-disabled":
            continue
        
        # Format and emit (content controls show ALL non-skipped)
        notice = format_control_notice(
            control_id=control.control_id,
            name=control.name,
            result=control.result,
            entity_types=control.entity_types,
            signal_value=control.signal_value,
        )
        append_notice(notice)
```

#### File: `src/agentic_claims/web/sseHelpers.py` (EDIT — drain and emit notices in runGraph)

**Location:** Inside the main `runGraph` event loop, after each `astream_events` yield

**Add periodic check (e.g., after processing each event):**

```python
# Inside the main event loop, after processing an event
from agentic_claims.web.governanceNoticeContext import drain_notices

# Drain any governance notices accumulated during this event
pending_notices = drain_notices()
for notice in pending_notices:
    yield ServerSentEvent(raw_data=notice, event=SseEvent.GOVERNANCE_NOTICE)
```

**Exact placement:** After the main event processing block, before continuing to the next event. This ensures notices appear in the SSE stream as soon as they're emitted by the governance runtimes.

---

## D4 — Review Checklist (reviewer role)

### Format Correctness
- [ ] All notices match EXACT format: `Governance control {ID} — {safeguard}. {Action}{detail}`
- [ ] All control IDs (A1-A12, B1-B6) have correct safeguard labels
- [ ] All result verbs map correctly (allowed→Allowed, denied→Blocked, etc.)
- [ ] B2 shows entity TYPES only, never raw PII (e.g., "EMAIL_ADDRESS", not "test@example.com")
- [ ] B1 shows signal value as percentage (99.99%) when present
- [ ] Observe mode shows "(observe)" suffix for would-* results

### No PII Leakage
- [ ] B2 PII redaction notices show entity types only, no raw values
- [ ] Audit JSONL checked: no raw PII in any governance notice field
- [ ] Test case: plant PII email → verify notice shows "EMAIL_ADDRESS", not the email

### No Decision/Audit Changes
- [ ] Notices are emitted AFTER decisions are made (do not influence disposition)
- [ ] Audit JSONL still contains complete disposition records (notices do not replace audit)
- [ ] Test case: compare audit before/after adding notices → identical disposition entries

### No Regression
- [ ] 200+ governance package tests still green
- [ ] Existing Expense e2e tests still green (no functional changes)
- [ ] Group A action controls still fire correctly
- [ ] Group B content controls still fire correctly

### Notice Attribution
- [ ] Governance notices appear in SSE stream as distinct events (not confused with model output)
- [ ] Frontend UI renders notices distinctly (e.g., system message style, not assistant bubble)
- [ ] Notices appear in chronological order (pre-check → model response → post-check → tool calls)

### Filtering Logic
- [ ] A6 "Allowed" does NOT show (too noisy, fires on every call)
- [ ] Action controls (A1-A12): only non-Allow outcomes show by default (Deny/Escalate)
- [ ] Content controls (B1-B6): ALL non-skipped outcomes show (including Transform)
- [ ] Skipped controls do NOT show (unless verbose mode is implemented later)

---

## Implementation Sequence

### Phase 1: Package (D1) — Governance repo (governance-builder role)
1. Create `notice_formatter.py` with `format_control_notice()` and canonical mappings
2. Write unit tests in `test_notice_formatter.py` (all control IDs, verbs, details)
3. **DECISION:** Add notice emission to `governed_mcp_call.py` and `content_hooks.py` (optional import pattern)
4. Bump version to `0.12.0` in `pyproject.toml`
5. Update `CHANGELOG.md`
6. Run `pytest` → verify 200+ tests still pass
7. Commit + push to governance repo

### Phase 2: Expense Integration (D2 + D3) — Expense repo (integrator role)
1. Pull updated governance package (`pip install -e ../agentic-governance`)
2. Create `governanceNoticeContext.py` with ContextVar queue
3. Edit `chat.py` router: call `init_notice_queue()` before graph invocation
4. Add `SseEvent.GOVERNANCE_NOTICE` to `sseEvents.py`
5. Edit `sseHelpers.py` `runGraph`: drain and emit notices after each event
6. Edit `intake_gpt/graph.py`: emit content notices after pre/post checks (if needed — may be redundant if package already emits)
7. Run existing e2e tests → verify no regression
8. Manual test: send PII message → verify notice shows "EMAIL_ADDRESS", not raw email
9. Commit to `feature/agentic-guardrails` branch

### Phase 3: Review (D4) — Reviewer role
1. Verify format correctness for all control types (A1-A12, B1-B6)
2. Verify no PII leakage (B2 entity types only)
3. Verify no decision/audit changes (before/after comparison)
4. Verify no regression (all tests green)
5. Verify notice attribution (SSE events distinct, frontend rendering correct)
6. Report: PASS/FAIL with specific findings

---

## Open Questions for Team Lead

**Q1 — D3 DECISION POINT:** Should notice emission be added to the governance package (`governed_mcp_call.py` and `content_hooks.py`) with optional import of `append_notice`, OR should Expense wrap the governance calls to extract notices post-hoc?
- **RECOMMENDATION:** Add to package (Option 1) — cleaner, all governance logic in one place, optional import makes it non-breaking for other users of the package.

**Q2 — Verbose mode toggle:** Should we add a `AGENTIC_GOV_VERBOSE_NOTICES=true|false` env var to control whether A6/A1 "Allowed" notices show, or defer to a future slice?
- **RECOMMENDATION:** Defer to future slice; start with hardcoded filtering (A6 never, A1-A12 Allow skip, B1-B6 all non-skipped).

**Q3 — Observe mode suffix:** Should `would-escalate` show as "Escalated (observe)" or "Flagged (observe)"?
- **RECOMMENDATION:** Use "Escalated (observe)" to maintain verb consistency with enforce mode.

**Q4 — Frontend rendering:** Should governance notices appear as system messages (gray background, distinct from assistant/user), or as a new UI element (e.g., yellow info banner)?
- **RECOMMENDATION:** System message style (gray) for this slice; frontend polish (banner) can be a future UX improvement.

---

## Definition of Done

- [ ] Package 0.12.0 with `format_control_notice()` + canonical mappings, tests green
- [ ] (If Q1=Option 1) Package emits notices via optional `append_notice` import in both action and content runtimes
- [ ] Expense `governanceNoticeContext.py` provides request-scoped queue
- [ ] Chat router initializes notice queue before graph invocation
- [ ] `runGraph` drains and emits notices as SSE events (type `governance-notice`)
- [ ] Frontend renders governance notices distinctly (system message style)
- [ ] Manual demo: PII message → `Governance control B2 — PII redaction. Redacted (EMAIL_ADDRESS)`
- [ ] Manual demo: Injection → `Governance control B1 — Prompt injection. Escalated (99.99%)`
- [ ] Manual demo: Denied tool → `Governance control A5 — Tool allowlist. Blocked`
- [ ] All existing tests green (no regression)
- [ ] Review checklist items verified by reviewer

---

## UX Refinement Summary (Team-Lead Directive)

**Problem identified:** Current B-INT-1 stopgap returns AIMessage for governance blocks, making it look like the model said "Flagged for review: injection-detected". This is wrong — governance is not the model.

**Required design changes (incorporated into plan above):**

1. **Two distinct channels:**
   - **Informational notices** (B2 redacted, B1 observe, action allows) → `GOVERNANCE_NOTICE` SSE event → thinking panel (`#governanceNotices`)
   - **Enforcement interceptions** (B1 enforce, A5 deny, blocks turn) → `GOVERNANCE_MESSAGE` SSE event → main thread governance bubble

2. **Never AIMessage:** Governance blocks store `governanceBlockMessage` in state; runGraph emits as GOVERNANCE_MESSAGE (distinct visual styling, not assistant)

3. **Thinking panel for informational:** Automated governance annotations appear alongside tool steps in the activity panel

4. **Main thread for enforcement:** When governance actually stops the turn, a distinct governance message (shield icon, tertiary colors) explains why

5. **Standardized format still applies:** `Governance control {ID} — {safeguard}. {Action}{detail}`

6. **Replace ad hoc strings:** The "Flagged for review: ..." AIMessage is replaced with proper governance-notice channel

---

**STANDBY. Awaiting team-lead approval on Q2 (verbose mode) and Q3 (observe wording) before proceeding with implementation.**

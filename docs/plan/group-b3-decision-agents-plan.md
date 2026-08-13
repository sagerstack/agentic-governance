# B3 Grounded Output Validation — Decision Agents Implementation Plan

## Context Summary
- **Scope:** Phase 3 of B-INT-3 — implement B3 (grounded output validation) for decision agents
- **Agent coverage:** Advisor FIRST (highest stakes), then compliance. **FRAUD EXCLUDED from B3** (keeps B1/B2 only)
- **Mechanism:** Reuse existing `ContentHookRuntime.post_model_check()` + `GroundingValidator`
- **Current state:** D1 wiring exists but passes `trusted_state={}`, `rag_clauses=None` → B3 no-ops
- **NO Guardrails:** Decision agents already emit structured JSONB findings

## Team Lead Decisions (Approved)

**DP1 — Advisor Override Semantics: (a) OVERRIDE, downgrade-only**
- When advisor B3 grounding/consistency fails, governance **downgrades** the decision (auto_approve → escalate_to_reviewer) BEFORE `updateClaimStatus` is called
- Embeds the reason in `advisorFindings.governance`
- Audits it
- **NEVER upgrades** a decision — downgrade-to-human-review only

**DP2 — Fraud B3 Grounding: Leave-as-is (NO B3 on fraud)**
- Do NOT build custom fraud grounding
- Fraud keeps B1/B2 only (from D1)
- B3 scope for this phase = **ADVISOR (3A) + COMPLIANCE (3B) ONLY**
- Fraud 3C section dropped from plan

---

## Advisor — B3 Grounded Output Validation

### File: `src/agentic_claims/agents/advisor/node.py` (EDIT — populate B3 inputs)

**Location:** Inside `advisorNode()`, after extracting `advisorDecision` from agent messages, BEFORE calling `post_model_check()`

#### 1. FIELD MAPPING (Advisor → GroundingValidator format)

**Advisor output shape:**
```python
advisorDecision = {
    "decision": "auto_approve" | "return_to_claimant" | "escalate_to_reviewer",
    "reasoning": "...",
    "citedClauses": ["clause1", "clause2", ...],  # Optional
}
advisorFindings = {...}  # Additional structured findings
```

**GroundingValidator expects:**
```python
model_output = {
    "amount": float,
    "date": str,
    "vendor": str,
    "cited_clauses": list[str],
}
```

**Normalization:**
```python
# Build normalized dict for grounding check
normalized_output = {
    "decision": advisorDecision.get("decision"),
    "reasoning": advisorDecision.get("reasoning", ""),
    "cited_clauses": advisorDecision.get("citedClauses", []),
    # Advisor doesn't directly assert amount/date/vendor, but we check it references them correctly
    # Extract from reasoning if present (simple presence check, not full parsing)
}
```

#### 2. TRUSTED_STATE SOURCE

**Source:** Trusted extracted receipt + claim data from state

```python
# Lazy import (avoid circular import at module level)
from agentic_claims.agents.intake.extractionContext import extractedReceiptVar

trusted_receipt = extractedReceiptVar.get(None)
claim_data = state.get("claimData", {})

if trusted_receipt and isinstance(trusted_receipt, dict):
    fields = trusted_receipt.get("fields", {})
    trusted_state = {
        "amount": claim_data.get("amountSgd") or fields.get("totalAmount"),
        "date": fields.get("date"),
        "vendor": fields.get("merchant"),
        "currency": fields.get("currency"),
        "compliance_verdict": state.get("complianceFindings", {}).get("verdict"),
        "fraud_verdict": state.get("fraudFindings", {}).get("verdict"),
    }
else:
    trusted_state = {}
```

**Rationale:**
- Use `extractedReceiptVar` (trusted receipt from A9/intake)
- Fall back to `claimData` from state for amount
- Include compliance + fraud verdicts (advisor grounding check: auto_approve ONLY if both pass)

#### 3. RAG_CLAUSES SOURCE

**Source:** Compliance findings' cited clauses (already verified by compliance agent)

```python
compliance_findings = state.get("complianceFindings", {})
rag_clauses = compliance_findings.get("citedClauses", [])
```

**Rationale:**
- Compliance agent already ran `searchPolicies` and verified clauses exist
- Advisor's citations should be a SUBSET of compliance's citations
- If advisor cites a clause compliance didn't retrieve → grounding failure

#### 4. ADVISOR-SPECIFIC GROUNDING RULES

**Beyond standard GroundingValidator checks, add advisor-specific logic:**

```python
# Advisor-specific grounding checks
advisor_grounding_passed = True
grounding_errors = []

# Rule 1: auto_approve REQUIRES compliance="pass" AND fraud="clean"
if advisorDecision.get("decision") == "auto_approve":
    compliance_verdict = trusted_state.get("compliance_verdict")
    fraud_verdict = trusted_state.get("fraud_verdict")
    
    if compliance_verdict != "pass":
        advisor_grounding_passed = False
        grounding_errors.append(f"auto_approve requires compliance=pass, got {compliance_verdict}")
    
    if fraud_verdict not in ("clean", "low_risk"):
        advisor_grounding_passed = False
        grounding_errors.append(f"auto_approve requires fraud=clean/low_risk, got {fraud_verdict}")

# Rule 2: Cited clauses must be subset of compliance's cited clauses
advisor_cited = set(advisorDecision.get("citedClauses", []))
compliance_cited = set(rag_clauses)

if advisor_cited - compliance_cited:  # Advisor cited something compliance didn't
    advisor_grounding_passed = False
    extra_clauses = advisor_cited - compliance_cited
    grounding_errors.append(f"cited clauses not in compliance findings: {extra_clauses}")
```

#### 5. DISPOSITIONS (Post-Decision Semantics)

**Problem:** Advisor runs AFTER submitClaim, decision already persisted. What does B3 Escalate/Block mean?

**DECISION POINT FLAGGED:**

**Proposed semantics:**

- **Escalate (grounding mismatch):**
  - Audit log with `grounding-failed`
  - Embed in `advisorFindings.governance`
  - Set claim status to `escalated` (override advisor's decision)
  - DO NOT reverse a persisted `auto_approve` — just flag for human review

- **Block (critical grounding failure, e.g., date mismatch):**
  - Currently NOT APPLICABLE for advisor (date is from receipt, not advisor's assertion)
  - If advisor were to hallucinate a date/amount, Escalate (don't Block post-decision)

**Implementation:**

```python
if not advisor_grounding_passed or not grounding_result.passed:
    # B3 grounding failed — embed in findings and escalate claim
    advisorFindings["governance"] = advisorFindings.get("governance", []) + [
        {
            "control": "B3",
            "result": "escalated",
            "reason": "; ".join(grounding_errors + grounding_result.reasons),
            "details": {
                "advisor_decision": advisorDecision.get("decision"),
                "compliance_verdict": trusted_state.get("compliance_verdict"),
                "fraud_verdict": trusted_state.get("fraud_verdict"),
            },
        }
    ]
    
    # Override decision to escalate_to_reviewer (governance override)
    advisorDecision["decision"] = "escalate_to_reviewer"
    advisorDecision["reasoning"] = f"[Governance B3] {'; '.join(grounding_errors)}. Original: {advisorDecision.get('reasoning', '')}"
    
    # Update claim status to escalated (via updateClaimStatus tool)
    # This happens in the existing advisor node flow
```

**Question for team-lead:** Is it acceptable to OVERRIDE the advisor's decision (auto_approve → escalate_to_reviewer) when B3 grounding fails, BEFORE the claim status update? Or should we let the decision persist and only flag in findings + audit?

**Recommendation:** OVERRIDE the decision (safer — prevents hallucinated approvals from going through).

#### 6. LAZY IMPORT (Circular Import Avoidance)

**Rule:** graph.py module globals must be lazy-imported inside functions.

```python
# WRONG (top of file)
from agentic_claims.core.graph import _contentHookRuntime  # Circular import!

# CORRECT (inside advisorNode function)
def advisorNode(state: ClaimState) -> dict:
    # Lazy import to avoid circular dependency
    from agentic_claims.core.graph import _backgroundContentHookRuntime
    
    # Now use _backgroundContentHookRuntime for post_model_check
    if _backgroundContentHookRuntime:
        post_result = await _backgroundContentHookRuntime.post_model_check(...)
```

---

## Compliance — B3 Grounded Output Validation

### File: `src/agentic_claims/agents/compliance/node.py` (EDIT — populate B3 inputs)

#### 1. FIELD MAPPING (Compliance → GroundingValidator format)

**Compliance output shape:**
```python
complianceFindings = {
    "verdict": "pass" | "fail" | "requires_review",
    "violations": [...],
    "citedClauses": ["clause1", "clause2", ...],
    "summary": "...",
    "requiresManagerApproval": bool,
    "requiresDirectorApproval": bool,
}
```

**Normalization:**
```python
normalized_output = {
    "verdict": complianceFindings.get("verdict"),
    "cited_clauses": complianceFindings.get("citedClauses", []),
    "violations": complianceFindings.get("violations", []),
}
```

#### 2. TRUSTED_STATE SOURCE

**Source:** Same as advisor — trusted receipt + claim data

```python
from agentic_claims.agents.intake.extractionContext import extractedReceiptVar

trusted_receipt = extractedReceiptVar.get(None)
claim_data = state.get("claimData", {})

if trusted_receipt:
    fields = trusted_receipt.get("fields", {})
    trusted_state = {
        "amount": claim_data.get("amountSgd") or fields.get("totalAmount"),
        "date": fields.get("date"),
        "vendor": fields.get("merchant"),
        "currency": fields.get("currency"),
    }
else:
    trusted_state = {}
```

#### 3. RAG_CLAUSES SOURCE

**Source:** Policy search results from compliance's own RAG query

**Location:** Inside `complianceNode()`, after `searchPolicies` tool call

```python
# Compliance agent calls searchPolicies via RAG MCP
# Results are in the agent's message history (ToolMessage)
# Extract from response:

rag_clauses = []
for msg in messages:
    if isinstance(msg, ToolMessage) and msg.name == "searchPolicies":
        search_result = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
        if isinstance(search_result, list):
            rag_clauses = [clause.get("text", "") for clause in search_result if isinstance(clause, dict)]
        elif isinstance(search_result, dict) and "results" in search_result:
            rag_clauses = [clause.get("text", "") for clause in search_result["results"] if isinstance(clause, dict)]
```

**Alternative (if policy results are in state):**
```python
rag_clauses = state.get("policySearchResults", [])
```

#### 4. COMPLIANCE-SPECIFIC GROUNDING RULES

**Checks:**

1. **Cited clauses exist in RAG results:**
   - All `citedClauses` must appear in `rag_clauses`
   - If compliance cites a clause not in RAG → hallucination → Escalate

2. **Amount assertions match trusted state:**
   - If compliance references "claim amount exceeds $X" in reasoning, verify X matches `trusted_state["amount"]`
   - Simple substring check (no full NLP)

```python
# Grounding check: cited clauses must be in RAG results
compliance_cited = set(complianceFindings.get("citedClauses", []))
rag_cited = set(rag_clauses)

grounding_passed = True
grounding_errors = []

if compliance_cited - rag_cited:
    grounding_passed = False
    extra = compliance_cited - rag_cited
    grounding_errors.append(f"cited clauses not in RAG results: {extra}")
```

#### 5. DISPOSITIONS

**Escalate (grounding failure):**
- Embed in `complianceFindings.governance`
- Mark claim for escalation
- Audit log

**Block:** NOT APPLICABLE for compliance (no critical date/merchant assertions that warrant Block)

**Implementation:**
```python
if not grounding_passed:
    complianceFindings["governance"] = complianceFindings.get("governance", []) + [
        {
            "control": "B3",
            "result": "escalated",
            "reason": "; ".join(grounding_errors),
        }
    ]
    
    # Set verdict to requires_review (governance override)
    complianceFindings["verdict"] = "requires_review"
    complianceFindings["requiresReview"] = True
```

#### 6. LAZY IMPORT

**Same pattern as advisor:**
```python
def complianceNode(state: ClaimState) -> dict:
    from agentic_claims.core.graph import _backgroundContentHookRuntime
    # Use for post_model_check
```

---

## Fraud — B3 Status

**EXCLUDED from B3 per DP2.**

Fraud node keeps B1/B2 only (from D1 universal coverage). No grounded output validation. No changes to fraud node for Phase 3.

---

## Implementation Sequence (Advisor-First)

### Phase 3A: Advisor B3 Grounding
1. Edit `advisor/node.py`:
   - Lazy import `_backgroundContentHookRuntime`
   - Build `trusted_state` from `extractedReceiptVar` + state
   - Extract `rag_clauses` from compliance findings
   - Normalize advisor output to grounding format
   - Add advisor-specific grounding rules (auto_approve requires compliance=pass + fraud=clean)
   - Call `post_model_check()` with populated inputs
   - On grounding failure: embed in `advisorFindings.governance`, **downgrade decision** (auto_approve → escalate_to_reviewer) — NEVER upgrade
2. Integration test: advisor with hallucinated approval (compliance=fail but decision=auto_approve) → B3 downgrades to escalate_to_reviewer

### Phase 3B: Compliance B3 Grounding
1. Edit `compliance/node.py`:
   - Lazy import `_backgroundContentHookRuntime`
   - Build `trusted_state` from `extractedReceiptVar`
   - Extract `rag_clauses` from searchPolicies ToolMessage
   - Normalize compliance output
   - Check cited clauses ⊆ RAG results
   - On grounding failure: embed in findings, set verdict=requires_review
2. Integration test: compliance cites non-existent clause → B3 escalates

### Phase 3C: Fraud
**EXCLUDED** per DP2. No implementation for fraud B3.

---

## DECISION POINTS — RESOLVED

**DP1 — Advisor decision override semantics: APPROVED (a) OVERRIDE, downgrade-only**

When advisor B3 grounding fails (e.g., auto_approve but compliance=fail):
- Governance **downgrades** the decision (auto_approve → escalate_to_reviewer) BEFORE `updateClaimStatus` is called
- Embeds the reason in `advisorFindings.governance`
- Audits it
- **NEVER upgrades** a decision — downgrade-to-human-review only

**Rationale:**
- Advisor runs before `updateClaimStatus` is called
- Downgrading the decision prevents a bad approval from being persisted
- Findings embed + audit still capture the governance intervention
- Human reviewer sees: decision=escalate_to_reviewer, reason="[Governance B3] auto_approve requires compliance=pass..."

---

**DP2 — Fraud B3 grounding: APPROVED leave-as-is (NO B3 on fraud)**

Fraud is **EXCLUDED** from B3 grounded output validation:
- Fraud keeps B1/B2 only (from D1 universal coverage)
- No custom grounding logic for fraud
- B3 scope = **ADVISOR + COMPLIANCE ONLY**

---

## Definition of Done

### Phase 3A - Advisor (APPROVED)

- [ ] `advisor/node.py` populates `trusted_state` (receipt + claim data + compliance/fraud verdicts)
- [ ] `advisor/node.py` extracts `rag_clauses` from compliance findings
- [ ] Advisor-specific grounding rules implemented (auto_approve requires compliance=pass + fraud=clean/low_risk)
- [ ] Cited clauses checked against compliance's RAG results
- [ ] On grounding failure: embed in `advisorFindings.governance`, **downgrade decision** (auto_approve → escalate_to_reviewer) — NEVER upgrade
- [ ] Lazy import `_backgroundContentHookRuntime` (no circular import)
- [ ] Integration test: hallucinated auto_approve → B3 downgrades to escalate_to_reviewer
- [ ] Audit log contains B3 grounding-failed entry with agentIdentity=advisor

### Phase 3B - Compliance (APPROVED)

- [ ] `compliance/node.py` populates `trusted_state` (receipt + claim data)
- [ ] `compliance/node.py` extracts `rag_clauses` from searchPolicies ToolMessage
- [ ] Cited clauses ⊆ RAG results check implemented
- [ ] On grounding failure: embed in `complianceFindings.governance`, set verdict=requires_review
- [ ] Lazy import `_backgroundContentHookRuntime` (no circular import)
- [ ] Integration test: compliance cites non-existent clause → B3 escalates
- [ ] Audit log contains B3 grounding-failed entry with agentIdentity=compliance

### Phase 3C - Fraud

**EXCLUDED** per DP2. No implementation.

---

**Status:** Plan APPROVED. Team-lead dispatching Phase 3A (advisor) to integrator.

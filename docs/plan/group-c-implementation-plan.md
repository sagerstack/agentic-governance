# Group C Implementation Plan — Human Oversight & Failsafes

## Scope agreed for this slice

Included:
- advisor recommendation and governance oversight evaluated **separately**
- governance oversight result captured in audit as a separate artifact
- human reviewer sees both advisor recommendation and governance oversight
- deterministic escalation contract with:
  - reviewer role
  - allowed actions (`approve`, `reject`)
  - action hash
  - contract id
- governance may override upward from advisor recommendation to human review

Explicitly excluded for this slice:
- timeout / expiry control
- reviewer `modify` action
- employee recourse / appeal workflow

## Design

### Package responsibilities (`agentic-governance`)
- Provide a deterministic Group C evaluator:
  - input: advisor decision, trusted claim context, agent findings, prior governance findings
  - output:
    - governance decision
    - reasons
    - override flag
    - final status
    - escalation contract (when required)
- No LLM in the oversight decision loop
- No third-party oversight framework dependency required

### App responsibilities (`agentic-expense-claims`)
- Run Group C **after** advisor recommendation is available
- Persist and surface two separate artifacts:
  1. `advisor_decision`
  2. `governance_oversight`
- If governance requires human review, final claim status becomes `escalated`
  even when advisor recommended `auto_approve`
- Reviewer page and audit timeline render advisor and governance separately

## Decision rules in this slice

Governance requires human review when any of the following hold:
- advisor explicitly requests reviewer escalation
- fraud verdict is `duplicate` or `suspicious`
- compliance verdict is `fail` or `requires_review`
- actionable Group B governance concerns are present from B3/B4

Otherwise governance allows the advisor decision.

## Persistence / audit model

### Advisor audit entry
- existing `advisor_decision`
- remains the advisor-stage recommendation artifact

### Governance audit entry
- new `governance_oversight`
- captures:
  - `decision`
  - `requires_human_review`
  - `governance_override`
  - `final_status`
  - `reasons`
  - `rationale`
  - `contract`

### Claim persistence
- app stores governance oversight under `advisorFindings.governanceOversight`
- reviewer/audit views read it separately from advisor reasoning

## UI changes

### Review page
Show separate cards for:
- Advisory Agent
- Governance Oversight

### Audit timeline
Add a separate step:
- Governance Oversight

## Out-of-scope follow-ons
- timeout → default block / senior escalation
- reviewer SLA / latency enforcement
- reviewer quality metrics dashboard
- employee appeal / correction workflow
- named assignee queueing

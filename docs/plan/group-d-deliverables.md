# Group D Deliverables — Audit, Monitoring & Incident

## Objective

Group D makes the runtime governance control plane:
- trustworthy
- traceable
- monitorable
- operationally actionable
- incident-ready

This group is not just a dashboard. The dashboard is only the operator surface. Group D is complete only when audit integrity, monitoring, alerts, interventions, and incident handling all exist together.

---

## Complete deliverables

### D1. Canonical governance event model
A normalized event schema covering:
- `action_governance`
- `content_governance`
- `oversight_governance`
- `reviewer_decision`
- `system_failure`
- `incident_opened`
- `incident_updated`
- `incident_closed`

Each event should carry, where applicable:
- `eventId`
- `correlationId`
- `claimId`
- `dbClaimId`
- `agentIdentity`
- `controlGroup`
- `controlId`
- `decision`
- `reasons`
- `timestamp`
- `payloadRef` / safe reference fields
- `policyVersion`

---

### D2. Tamper-evident audit spine
A hardened governance audit trail with:
- append-only event emission
- hash chaining (`prevEntryHash`, `entryHash`)
- stable correlation across app/governance/reviewer events
- PII-safe payload references rather than raw sensitive blobs where possible

This becomes the stronger forensic source of truth for runtime governance.

---

### D3. End-to-end traceability
Ability to reconstruct a claim’s full path end to end:
- receipt upload
- extraction
- policy check
- action governance
- content governance
- compliance/fraud/advisor
- governance oversight
- reviewer action
- final disposition

---

### D4. Governance failure auditing
Explicit event capture for control-plane failures such as:
- audit sink write failure
- governance evaluator failure
- content/runtime hook failure
- oversight persistence failure
- monitoring degradation
- reviewer-path failure

Governance failure must itself be auditable.

---

### D5. Monitoring rules engine
Deterministic monitors for conditions such as:
- repeated denied tool calls
- spikes in B1/B3/B4 results
- unusual escalation growth
- excessive stuck escalations
- suspicious reviewer activity
- audit sink failures
- duplicate/fraud pattern spikes

Each rule defines:
- threshold
- severity
- action

---

### D6. Monitoring dashboard
Operational dashboard showing at minimum:
- control fire rates by group/control
- escalated claim backlog
- advisor vs governance disagreement rate
- reviewer throughput/latency
- governance override counts
- recent system/governance failures
- audit sink health
- recent incidents
- anomaly trend charts

The dashboard is the operator surface for Group D, not the whole of Group D.

---

### D7. Alert-to-intervention actions
Monitoring must trigger real actions, not only visual alerts:
- observe-only alert
- degraded mode flag
- manual-only routing
- flow halt/block for critical cases
- incident creation

---

### D8. Incident pipeline
A defined incident workflow with:
- incident creation criteria
- linked evidence/events
- materiality classification
- lifecycle states:
  - `open`
  - `investigating`
  - `mitigated`
  - `closed`
- audit trail for incident handling itself

---

### D9. Aggregate governance metrics
Longitudinal metrics for:
- control firing trends
- B1 OCR false-positive candidates
- B3 downgrade rate
- B4 concern rate
- escalation rate
- governance override rate
- reviewer latency
- backlog health
- systemic duplicate/fraud trends

---

### D10. Ops/reviewer surfaces
Operational views for:
- audit timeline
- dashboard
- incident list/detail
- review backlog health
- governance failure summaries

---

## MVP scope recommendation

### Group D MVP
1. canonical governance event model
2. tamper-evident audit spine
3. governance failure events
4. monitoring dashboard
5. basic alert rules
6. incident creation workflow

### Follow-on scope
7. alert-to-intervention automation
8. richer metrics/trends
9. reviewer/backlog analytics
10. deeper incident workflows

---

## First implementation focus

We will start with:

## Audit integrity

Audit integrity is the foundation for the rest of Group D. Without a trustworthy runtime record, monitoring, dashboarding, and incidents become weak or disputable.

### Audit integrity deliverables

#### DI-1. Canonical audit event shape
Define one canonical schema for governance events so all later monitoring/dashboard work consumes a stable contract.

#### DI-2. Hash-chained governance audit entries
Every governance event should include:
- `entryId`
- `prevEntryHash`
- `entryHash`
- canonicalized event body hash inputs

This makes silent alteration detectable.

#### DI-3. Strong correlation fields
Every event should carry consistent correlation and identity fields so claim reconstruction is deterministic.

#### DI-4. PII-safe evidence references
Prefer references/hashes over raw sensitive payloads while still preserving forensic usefulness.

#### DI-5. Governance failure events
Audit sink failure and related governance write failures must emit explicit failure events.

#### DI-6. Canonical source-of-truth decision
For Group D, the governance audit spine should be treated as the stronger forensic record, while app DB timeline views remain derived operational views.

---

## Next step after this document

Implement Audit Integrity first:
1. finalize canonical event schema
2. strengthen JSONL governance audit chain
3. add explicit failure events
4. define how DB/UI derive from the governance audit spine

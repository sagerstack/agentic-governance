# Running the governed Expense app in Docker

Two ways to get `agentic-governance` into the Dockerized Expense app. The path dependency
`agentic-governance = { path = "../agentic-governance" }` does **not** resolve inside a normal
Docker build (the sibling repo is outside the app's build context), so we bring it in explicitly.

---

## Option 2 — Parent additional build context  (IMPLEMENTED NOW — quick test)

Used to quickly validate the Slice-0 integration end-to-end. Requires both repos checked out
side by side (`sagerstack/agentic-expense-claims` and `sagerstack/agentic-governance`) and a
Docker/Compose new enough for `additional_contexts` (Docker 23+/Compose 2.17+).

**What was changed (on branch `feature/agentic-guardrails`, deploy-config only):**
- `docker-compose.yml` → app `build:` now declares
  `additional_contexts: { governance: ../agentic-governance }`, plus an audit volume
  `./.governance-audit:/app/.agentic_governance` so governance events are visible on the host.
- `Dockerfile` → `COPY --from=governance . /agentic-governance` (sibling of `/app`), strips the
  governance path-dep line from the copied `pyproject.toml` so the existing `poetry export`
  stays consistent with `poetry.lock`, then `pip install /agentic-governance` explicitly.
- No `poetry.lock` regeneration needed; the host `pyproject.toml` path-dep is untouched (host
  dev / Level-2 on-host still works).

**Run it:**
```bash
cd agentic-expense-claims
git checkout feature/agentic-guardrails
docker compose up --build            # builds app image with governance installed
# (or: ./scripts/startup.sh if it wraps compose up)
```

**Verify governance is live:**
```bash
# 1) submit/process a claim via the UI at http://localhost:8000
# 2) watch governance events (Slice 0 = Observe-only, nothing blocked):
tail -f agentic-expense-claims/.governance-audit/audit.jsonl
#    → one envelope + disposition + audit entry per MCP tool call
```
- **Transparency:** the app behaves exactly as on `main`; every MCP call emits an audit event.
- **Fail-closed spot check:** make the audit sink path unwritable (or the engine raise) → an
  `insertClaim` is denied and no DB row is written.

Notes/limitations:
- `additional_contexts` needs BuildKit (default in modern Docker Desktop).
- Only works when the two repos are siblings on disk. Not suitable for CI/registry builds.

---

## Option 1 — Versioned wheel install  (RECOMMENDED for the proper demo/deploy — do later)

Self-contained, registry-friendly, closest to production. The app image depends on a built
artifact, not a sibling directory.

**1. Build the wheel from the governance repo:**
```bash
cd agentic-governance
python -m build                      # → dist/agentic_governance-0.1.0-py3-none-any.whl
```

**2. Vendor the wheel into the app build context:**
```bash
mkdir -p agentic-expense-claims/vendor
cp agentic-governance/dist/agentic_governance-*.whl agentic-expense-claims/vendor/
```

**3. App `pyproject.toml`** — replace the path dep with a normal versioned dep:
```toml
agentic-governance = "^0.1.0"
```
then regenerate the lock: `poetry lock` (so `poetry export` includes it).

**4. Dockerfile** — install the wheel (revert the Option-2 additional-context block):
```dockerfile
COPY vendor/agentic_governance-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/agentic_governance-*.whl
```

**5. docker-compose.yml** — plain `build: .` (drop `additional_contexts`); keep the audit volume.

**Later hardening:** publish `agentic-governance` to a private index and just
`poetry add agentic-governance` — no vendored wheel, no path/context tricks. Multi-stage build
can build the wheel and copy it into the runtime image in one Dockerfile.

---

## Common to both

- **Branch:** build the app image from `feature/agentic-guardrails` (or a merged `demo` branch) so
  the `core/graph.py` DI edit is present. Governance activates automatically once installed —
  no env flag.
- **Audit volume:** mount `./.governance-audit:/app/.agentic_governance` so envelopes/dispositions
  are visible on the host and available as the future dashboard's data source.
- **Scope note:** Dockerfile/compose/wheel changes are deployment config, deliberately *outside*
  the 2-file POC integration scope (`pyproject.toml` + `core/graph.py`). Keep them on the
  demo/deploy branch, not folded into the governance layer or the minimal app edit.

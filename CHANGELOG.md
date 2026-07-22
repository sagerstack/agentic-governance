# Changelog

## Versioning policy

- Increment the MINOR version after every completed slice.
- Increment the MAJOR version after every completed group, resetting MINOR to 0.

## Versions

- **0.5.0** — Slice 4 (configurable exposure, rate, and receipt-evidence disposition controls)
- **0.4.0** — Slice 3 (unified configurable policy table + envelope integrity + independently staged control modes)
- **0.3.1** — Added environment-driven mandate-revocation and forced-identity demo toggles
- **0.3.0** — Slice 2 (verified agent identities + machine-readable per-identity mandates)
- **0.2.2** — Audit `policyVersion` now reports the package version (removed internal slice labels from runtime data)
- **0.2.1** — Audit sink writes a new timestamped file per run (`audit-<UTC>.jsonl`)
- **0.2.0** — Slice 1 (least-privilege deny-unknown-tool allowlist + Deny path + demo trigger)
- **0.1.0** — Slice 0 (walking skeleton: envelope + disposition + JSONL audit + fail-closed floor)

# agentic-governance

Slice 1 least-privilege gate for an app-agnostic runtime governance layer.

The pure-Python policy decision point denies by default and grants exact
`(serverUrl, wire-toolName)` pairs using the governance-owned allowlist in
`agentic_governance.adapters.tool_allowlist`. MCP server URLs are read from the
existing `RAG_MCP_URL`, `DB_MCP_URL`, and `CURRENCY_MCP_URL` environment variables.

For a live Deny demo without changing application code, subtract normally allowed
wire tools with a comma-separated environment variable, for example:

```bash
AGENTIC_GOV_DENY_TOOLS="convertCurrency"  # empty/unset by default
```

By default, each installed governance runtime writes its run to a new audit file in
`./.agentic_governance/`, named `audit-<UTC YYYYMMDDTHHMMSSZ>-<6 hex>.jsonl`.
Previous run files are preserved. Passing an explicit `.jsonl` path to
`JsonlAuditSink` continues to use that exact file. No `audit-latest.jsonl` pointer is
created.

## Install

```bash
pip install -e .
```

## Test

```bash
pytest
```

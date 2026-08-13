from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_entry_id() -> str:
    return str(uuid4())


def canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def hash_event_body(data: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def finalize_entry(entry: dict[str, Any], *, prev_entry_hash: str | None) -> dict[str, Any]:
    finalized = dict(entry)
    finalized["prevEntryHash"] = prev_entry_hash
    body = {k: v for k, v in finalized.items() if k != "entryHash"}
    finalized["entryHash"] = hash_event_body(body)
    return finalized

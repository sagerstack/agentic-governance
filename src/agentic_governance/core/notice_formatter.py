"""Canonical governance control notice formatter.

Produces standardized human-readable notices for governance control firings.
Format: "Governance control {ID} — {safeguard}. {Action}{detail}"
"""

from __future__ import annotations

from typing import Any


# Control ID → human-readable safeguard label
SAFEGUARD_LABELS: dict[str, str] = {
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
ACTION_VERBS: dict[str, str] = {
    "allowed": "Allowed",
    "observed": "Allowed",
    "verified": "Allowed",
    "transformed": "Redacted",
    "redacted": "Redacted",
    "would-transform": "Redacted",
    "escalate": "Escalated",
    "escalated": "Escalated",
    "would-escalate": "Flagged",
    "deny": "Blocked",
    "denied": "Blocked",
    "blocked": "Blocked",
    "would-deny": "Flagged",
    "skipped-disabled": "Skipped",
}


def format_control_notice(
    control_id: str,
    name: str,
    result: str,
    *,
    entity_types: list[str] | tuple[str, ...] | None = None,
    signal_value: float | None = None,
    reason: str | None = None,
    mode: str | None = None,
) -> str:
    """Format a governance control firing into the canonical notice string.
    
    Args:
        control_id: e.g. "B2", "A7"
        name: e.g. "pii-minimization", "exposure-limits" (fallback if control_id unknown)
        result: e.g. "transformed", "escalated", "denied", "allowed"
        entity_types: For B2 only — list/tuple of PII entity types found
                     (e.g. ["EMAIL_ADDRESS", "PHONE_NUMBER"])
        signal_value: For B1 only — injection score (0.0-1.0, shown as percentage)
        reason: Optional additional context (reserved for future, not currently used)
        mode: "observe" | "enforce" | "off" — adds "(observe)" suffix if mode=observe
             and result starts with "would-"
    
    Returns:
        Formatted notice string: "Governance control {ID} — {safeguard}. {Action}{detail}"
    
    Examples:
        >>> format_control_notice("B2", "pii-minimization", "transformed", 
        ...                       entity_types=["EMAIL_ADDRESS"])
        'Governance control B2 — PII redaction. Redacted (EMAIL_ADDRESS)'
        
        >>> format_control_notice("B1", "input-attack-detection", "escalated", 
        ...                       signal_value=0.9999)
        'Governance control B1 — Prompt injection. Escalated (99.99%)'
        
        >>> format_control_notice("A5", "tool-allowlist", "denied")
        'Governance control A5 — Tool allowlist. Blocked'
        
        >>> format_control_notice("A7", "exposure-limits", "would-escalate", mode="observe")
        'Governance control A7 — Exposure limit. Flagged (observe)'
    """
    # Resolve safeguard label (fallback to name if control_id unknown)
    safeguard = SAFEGUARD_LABELS.get(control_id, name)
    
    # Resolve action verb (fallback to capitalized result if unknown)
    action = ACTION_VERBS.get(result.lower(), result.capitalize())
    
    # Build detail suffix
    detail = ""
    
    # B2: entity types (PII categories)
    if control_id == "B2" and entity_types:
        entity_list = ", ".join(entity_types)
        detail = f" ({entity_list})"
    
    # B1: signal value (injection score as percentage)
    elif control_id == "B1" and signal_value is not None:
        percentage = signal_value * 100
        detail = f" ({percentage:.2f}%)"
    
    # Observe mode: add suffix for would-* results
    if mode == "observe" and result.startswith("would-"):
        detail += " (observe)" if not detail else ""
        # If detail exists (e.g., B2 entity types), append observe
        if " (" in detail and not detail.endswith("(observe)"):
            detail = detail.rstrip(")") + ", observe)"
    
    # Combine: "Governance control {ID} — {safeguard}. {Action}{detail}"
    return f"Governance control {control_id} — {safeguard}. {action}{detail}"

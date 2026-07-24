"""Unit tests for governance control notice formatter."""

from __future__ import annotations

import pytest

from agentic_governance.core.notice_formatter import (
    SAFEGUARD_LABELS,
    ACTION_VERBS,
    format_control_notice,
)


# Test: All control IDs have labels

def test_all_action_controls_have_labels():
    """Verify every A1-A12 control has a safeguard label."""
    for i in range(1, 13):
        control_id = f"A{i}"
        assert control_id in SAFEGUARD_LABELS, f"{control_id} missing safeguard label"


def test_all_content_controls_have_labels():
    """Verify every B1-B6 control has a safeguard label."""
    for i in range(1, 7):
        control_id = f"B{i}"
        assert control_id in SAFEGUARD_LABELS, f"{control_id} missing safeguard label"


# Test: All result verbs map correctly

def test_allowed_verbs_map_to_allowed():
    """allowed/observed/verified → Allowed"""
    for verb in ["allowed", "observed", "verified"]:
        assert ACTION_VERBS[verb] == "Allowed"


def test_redacted_verbs_map_to_redacted():
    """transformed/redacted/would-transform → Redacted"""
    assert ACTION_VERBS["transformed"] == "Redacted"
    assert ACTION_VERBS["redacted"] == "Redacted"
    assert ACTION_VERBS["would-transform"] == "Redacted"


def test_escalated_verbs_map_to_escalated():
    """escalate/escalated → Escalated; would-escalate → Flagged"""
    assert ACTION_VERBS["escalate"] == "Escalated"
    assert ACTION_VERBS["escalated"] == "Escalated"
    assert ACTION_VERBS["would-escalate"] == "Flagged"


def test_blocked_verbs_map_to_blocked():
    """deny/denied/blocked → Blocked; would-deny → Flagged"""
    assert ACTION_VERBS["deny"] == "Blocked"
    assert ACTION_VERBS["denied"] == "Blocked"
    assert ACTION_VERBS["blocked"] == "Blocked"
    assert ACTION_VERBS["would-deny"] == "Flagged"


def test_skipped_verb_maps_to_skipped():
    """skipped-disabled → Skipped"""
    assert ACTION_VERBS["skipped-disabled"] == "Skipped"


def test_flagged_verbs_for_observe_mode():
    """would-escalate/would-deny → Flagged (observe-mode verb)"""
    assert ACTION_VERBS["would-escalate"] == "Flagged"
    assert ACTION_VERBS["would-deny"] == "Flagged"


# Test: Basic format (no details)

def test_basic_format_action_control():
    """A5 tool-allowlist denied → 'Governance control A5 — Tool allowlist. Blocked'"""
    notice = format_control_notice("A5", "tool-allowlist", "denied")
    assert notice == "Governance control A5 — Tool allowlist. Blocked"


def test_basic_format_content_control():
    """B3 grounded-output-validation escalated → 'Governance control B3 — Output grounding. Escalated'"""
    notice = format_control_notice("B3", "grounded-output-validation", "escalated")
    assert notice == "Governance control B3 — Output grounding. Escalated"


def test_format_uses_canonical_label():
    """Control ID A2 uses canonical label 'Payload integrity' not the name"""
    notice = format_control_notice("A2", "envelope-integrity", "denied")
    assert "Payload integrity" in notice
    assert "envelope-integrity" not in notice


def test_format_fallback_to_name_for_unknown_control():
    """Unknown control ID falls back to using the name as label"""
    notice = format_control_notice("X99", "custom-control", "denied")
    assert "Governance control X99 — custom-control. Blocked" == notice


def test_format_capitalizes_unknown_result():
    """Unknown result gets capitalized as fallback"""
    notice = format_control_notice("A1", "governance-envelope", "unknown-result")
    assert notice == "Governance control A1 — Governance envelope. Unknown-result"


# Test: B2 entity types detail

def test_b2_with_single_entity_type():
    """B2 with one entity type shows (EMAIL_ADDRESS)"""
    notice = format_control_notice(
        "B2", "pii-minimization", "transformed",
        entity_types=["EMAIL_ADDRESS"]
    )
    assert notice == "Governance control B2 — PII redaction. Redacted (EMAIL_ADDRESS)"


def test_b2_with_multiple_entity_types():
    """B2 with multiple entity types shows comma-separated list"""
    notice = format_control_notice(
        "B2", "pii-minimization", "transformed",
        entity_types=["EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON"]
    )
    assert notice == "Governance control B2 — PII redaction. Redacted (EMAIL_ADDRESS, PHONE_NUMBER, PERSON)"


def test_b2_with_empty_entity_types():
    """B2 with empty entity types list shows no detail"""
    notice = format_control_notice(
        "B2", "pii-minimization", "transformed",
        entity_types=[]
    )
    assert notice == "Governance control B2 — PII redaction. Redacted"


def test_b2_with_none_entity_types():
    """B2 with None entity types shows no detail"""
    notice = format_control_notice(
        "B2", "pii-minimization", "transformed",
        entity_types=None
    )
    assert notice == "Governance control B2 — PII redaction. Redacted"


def test_b2_allowed_shows_no_entity_types():
    """B2 allowed (no PII found) shows no entity types"""
    notice = format_control_notice(
        "B2", "pii-minimization", "allowed",
        entity_types=None
    )
    assert notice == "Governance control B2 — PII redaction. Allowed"


# Test: B1 signal value detail

def test_b1_with_high_signal_value():
    """B1 with signal value shows percentage"""
    notice = format_control_notice(
        "B1", "input-attack-detection", "escalated",
        signal_value=0.9999
    )
    assert notice == "Governance control B1 — Prompt injection. Escalated (99.99%)"


def test_b1_with_low_signal_value():
    """B1 with low signal value shows percentage"""
    notice = format_control_notice(
        "B1", "input-attack-detection", "allowed",
        signal_value=0.1234
    )
    assert notice == "Governance control B1 — Prompt injection. Allowed (12.34%)"


def test_b1_with_zero_signal_value():
    """B1 with zero signal value shows 0.00%"""
    notice = format_control_notice(
        "B1", "input-attack-detection", "allowed",
        signal_value=0.0
    )
    assert notice == "Governance control B1 — Prompt injection. Allowed (0.00%)"


def test_b1_with_none_signal_value():
    """B1 with None signal value shows no detail"""
    notice = format_control_notice(
        "B1", "input-attack-detection", "escalated",
        signal_value=None
    )
    assert notice == "Governance control B1 — Prompt injection. Escalated"


# Test: Observe mode suffix

def test_observe_mode_with_would_escalate():
    """would-escalate in observe mode → Flagged (observe)"""
    notice = format_control_notice(
        "A7", "exposure-limits", "would-escalate",
        mode="observe"
    )
    assert notice == "Governance control A7 — Exposure limit. Flagged (observe)"


def test_observe_mode_with_would_deny():
    """would-deny in observe mode → Flagged (observe)"""
    notice = format_control_notice(
        "A2", "envelope-integrity", "would-deny",
        mode="observe"
    )
    assert notice == "Governance control A2 — Payload integrity. Flagged (observe)"


def test_enforce_mode_no_observe_suffix():
    """enforce mode does NOT add (observe) suffix even for would-* results"""
    notice = format_control_notice(
        "A7", "exposure-limits", "would-escalate",
        mode="enforce"
    )
    # In enforce mode, would-* shouldn't happen, but if it does, no (observe) suffix
    # would-escalate maps to "Flagged" (observe-mode verb)
    assert notice == "Governance control A7 — Exposure limit. Flagged"


def test_observe_mode_with_non_would_result():
    """observe mode with enforce-mode result (escalated) does NOT add suffix"""
    notice = format_control_notice(
        "A7", "exposure-limits", "escalated",
        mode="observe"
    )
    # escalated (enforce-mode result) → Escalated, no suffix needed
    assert notice == "Governance control A7 — Exposure limit. Escalated"


def test_b1_observe_mode_with_signal_value():
    """B1 would-escalate in observe mode with signal value → Flagged (99.99%, observe)"""
    notice = format_control_notice(
        "B1", "input-attack-detection", "would-escalate",
        signal_value=0.9999,
        mode="observe"
    )
    # Per team-lead's locked Q3 decision: would-escalate → "Flagged"
    # With signal value + observe mode → "Flagged (99.99%, observe)"
    assert notice == "Governance control B1 — Prompt injection. Flagged (99.99%, observe)"


# Test: Complete examples from scope doc

def test_scope_example_b2_redacted():
    """Scope doc example: B2 PII redaction with entity types"""
    notice = format_control_notice(
        "B2", "pii-minimization", "transformed",
        entity_types=["EMAIL_ADDRESS", "PHONE_NUMBER"]
    )
    assert notice == "Governance control B2 — PII redaction. Redacted (EMAIL_ADDRESS, PHONE_NUMBER)"


def test_scope_example_b1_escalated():
    """Scope doc example: B1 prompt injection with signal value"""
    notice = format_control_notice(
        "B1", "input-attack-detection", "escalated",
        signal_value=0.9999
    )
    assert notice == "Governance control B1 — Prompt injection. Escalated (99.99%)"


def test_scope_example_a5_blocked():
    """Scope doc example: A5 tool allowlist blocked"""
    notice = format_control_notice(
        "A5", "tool-allowlist", "denied"
    )
    assert notice == "Governance control A5 — Tool allowlist. Blocked"


def test_scope_example_a7_escalated():
    """Scope doc example: A7 exposure limit escalated"""
    notice = format_control_notice(
        "A7", "exposure-limits", "escalated"
    )
    assert notice == "Governance control A7 — Exposure limit. Escalated"


def test_scope_example_a2_blocked():
    """Scope doc example: A2 payload integrity blocked"""
    notice = format_control_notice(
        "A2", "envelope-integrity", "denied"
    )
    assert notice == "Governance control A2 — Payload integrity. Blocked"


def test_scope_example_a1_allowed():
    """Scope doc example: A1 governance envelope allowed"""
    notice = format_control_notice(
        "A1", "governance-envelope", "allowed"
    )
    assert notice == "Governance control A1 — Governance envelope. Allowed"


# Test: Edge cases

def test_empty_control_id():
    """Empty control ID uses name as fallback"""
    notice = format_control_notice(
        "", "custom-check", "allowed"
    )
    assert notice == "Governance control  — custom-check. Allowed"


def test_case_insensitive_result():
    """Result verb lookup is case-insensitive"""
    notice = format_control_notice(
        "A5", "tool-allowlist", "DENIED"
    )
    assert notice == "Governance control A5 — Tool allowlist. Blocked"


def test_tuple_entity_types():
    """entity_types as tuple works the same as list"""
    notice = format_control_notice(
        "B2", "pii-minimization", "transformed",
        entity_types=("EMAIL_ADDRESS", "PERSON")
    )
    assert notice == "Governance control B2 — PII redaction. Redacted (EMAIL_ADDRESS, PERSON)"


def test_all_controls_format_correctly():
    """Verify every control ID A1-A12, B1-B6 formats correctly"""
    for control_id in ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11", "A12",
                       "B1", "B2", "B3", "B4", "B5", "B6"]:
        notice = format_control_notice(control_id, "test-control", "allowed")
        assert notice.startswith(f"Governance control {control_id} — ")
        assert "Allowed" in notice
        assert SAFEGUARD_LABELS[control_id] in notice

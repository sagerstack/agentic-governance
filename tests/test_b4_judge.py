"""Unit tests for B4 (LLM-as-judge) async extraction from post_model_check.

Verifies:
1. judge() runs asynchronously and off the sync latency path
2. judge() with stub client returning concerns → audit entry + critique returned
3. judge() with stub client returning no concerns → audit entry (no-concerns) + empty critique
4. judge() with client None → returns None (inert)
5. judge() with mode "off" → returns empty critique + skipped audit
6. judge() with client that raises → empty critique (B5 graceful-failure)
7. judge() observe/escalate-only: never blocks or denies
8. post_model_check no longer invokes the judge (regression)
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import Mock, AsyncMock

from agentic_governance.adapters.policy_loader import load_policy
from agentic_governance.adapters.llm_judge import LlmJudge, JudgeCritique, StubLlmJudge
from agentic_governance.integrations.langgraph_mcp.content_hooks import ContentHookRuntime


@pytest.fixture
def policy_env(monkeypatch):
    monkeypatch.setenv("RAG_MCP_URL", "http://rag")
    monkeypatch.setenv("DB_MCP_URL", "http://db")
    monkeypatch.setenv("CURRENCY_MCP_URL", "http://currency")


class MemoryAuditSink:
    """In-memory audit sink for testing."""
    def __init__(self):
        self.entries = []

    async def append_content(self, env, disp):
        from agentic_governance.adapters.jsonl_audit import build_content_audit_entry
        self.entries.append(build_content_audit_entry(env, disp))

    async def append(self, env, disp):
        if hasattr(env, 'content_id'):
            await self.append_content(env, disp)


# Judge with concerns → audit + critique + notice

async def test_judge_with_concerns_emits_audit_and_returns_critique(policy_env, monkeypatch):
    """judge() with concerns → audit entry emitted + critique returned."""
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_B4", "observe")
    audit_sink = MemoryAuditSink()
    policy = load_policy()
    
    # Stub judge that returns concerns
    judge = StubLlmJudge(
        concerns=("hallucination detected",),
        confidence=0.85,
        flags=("hallucination",),
    )
    
    runtime = ContentHookRuntime(
        policy=policy,
        llm_judge=judge,
        audit_sink=audit_sink,
    )
    
    critique = await runtime.judge(
        content="The model output to judge",
        correlation_id="test-123",
        agent_identity="intake-gpt",
        context={"claim_type": "expense"},
    )
    
    # Critique returned with concerns
    assert critique is not None
    assert "hallucination detected" in critique.concerns
    assert critique.confidence == 0.85
    assert "hallucination" in critique.flags
    assert critique.contributed_to_escalation is False  # B4 never blocks
    
    # Audit entry emitted
    assert len(audit_sink.entries) == 1
    entry = audit_sink.entries[0]
    assert entry["correlationId"] == "test-123"
    
    # B4 fired control in audit (nested in disposition)
    disposition = entry.get("disposition", {})
    fired = disposition.get("firedControls", [])
    b4_controls = [c for c in fired if c.get("controlId") == "B4"]
    assert len(b4_controls) == 1
    assert b4_controls[0]["result"] == "concerns-found"
    assert b4_controls[0]["signalValue"] == 0.85  # confidence score


async def test_judge_with_no_concerns_emits_audit_and_empty_critique(policy_env, monkeypatch):
    """judge() with no concerns → audit entry (no-concerns) + empty critique."""
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_B4", "observe")
    audit_sink = MemoryAuditSink()
    policy = load_policy()
    
    judge = StubLlmJudge(concerns=(), confidence=0.95, flags=())
    
    runtime = ContentHookRuntime(
        policy=policy,
        llm_judge=judge,
        audit_sink=audit_sink,
    )
    
    critique = await runtime.judge(
        content="Clean model output",
        correlation_id="test-456",
        agent_identity="intake-gpt",
        context={},
    )
    
    # Critique returned with no concerns
    assert critique is not None
    assert len(critique.concerns) == 0
    assert critique.confidence == 0.95
    
    # Audit entry emitted
    assert len(audit_sink.entries) == 1
    entry = audit_sink.entries[0]
    
    # B4 fired control with no-concerns result (nested in disposition)
    disposition = entry.get("disposition", {})
    fired = disposition.get("firedControls", [])
    b4_controls = [c for c in fired if c.get("controlId") == "B4"]
    assert len(b4_controls) == 1
    assert b4_controls[0]["result"] == "no-concerns"


# Judge is inert (None) → returns None

async def test_judge_with_no_llm_judge_returns_none(policy_env, monkeypatch):
    """judge() with llm_judge=None → returns None (inert, no audit)."""
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_B4", "observe")
    audit_sink = MemoryAuditSink()
    policy = load_policy()
    
    runtime = ContentHookRuntime(
        policy=policy,
        llm_judge=None,  # Inert
        audit_sink=audit_sink,
    )
    
    critique = await runtime.judge(
        content="Any content",
        correlation_id="test-789",
        agent_identity="intake-gpt",
        context={},
    )
    
    # Inert judge returns None
    assert critique is None
    
    # No audit emitted (inert)
    assert len(audit_sink.entries) == 0


# Judge mode off → skipped audit + empty critique

async def test_judge_mode_off_emits_skipped_audit(policy_env, monkeypatch):
    """judge() with mode "off" → emits skipped-disabled audit + empty critique."""
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_B4", "off")
    audit_sink = MemoryAuditSink()
    policy = load_policy()
    
    judge = StubLlmJudge(concerns=("would be concern",), confidence=0.5, flags=("x",))
    
    runtime = ContentHookRuntime(
        policy=policy,
        llm_judge=judge,
        audit_sink=audit_sink,
    )
    
    critique = await runtime.judge(
        content="Any content",
        correlation_id="test-off",
        agent_identity="intake-gpt",
        context={},
    )
    
    # Empty critique returned
    assert critique is not None
    assert len(critique.concerns) == 0
    assert critique.confidence is None
    
    # Skipped audit emitted
    assert len(audit_sink.entries) == 1
    entry = audit_sink.entries[0]
    disposition = entry.get("disposition", {})
    fired = disposition.get("firedControls", [])
    b4_controls = [c for c in fired if c.get("controlId") == "B4"]
    assert len(b4_controls) == 1
    assert b4_controls[0]["result"] == "skipped-disabled"


# Judge failure → B5 graceful-failure (empty critique, no raise)

async def test_judge_client_exception_returns_empty_critique(policy_env, monkeypatch):
    """judge() with client that raises → empty critique (B5 graceful-failure)."""
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_B4", "observe")
    audit_sink = MemoryAuditSink()
    policy = load_policy()
    
    # Judge that raises an exception
    class FailingJudge(LlmJudge):
        def __init__(self):
            super().__init__(llm_client=None)
        
        async def critique(self, model_output, context):
            raise RuntimeError("Judge API failed")
    
    judge = FailingJudge()
    
    runtime = ContentHookRuntime(
        policy=policy,
        llm_judge=judge,
        audit_sink=audit_sink,
    )
    
    # Should NOT raise
    critique = await runtime.judge(
        content="Any content",
        correlation_id="test-fail",
        agent_identity="intake-gpt",
        context={},
    )
    
    # Empty critique returned (graceful failure)
    assert critique is not None
    assert len(critique.concerns) == 0
    assert critique.confidence is None
    assert critique.latency_ms >= 0  # Latency recorded even on failure


# B4 observe/escalate-only: never blocks or denies

async def test_judge_never_blocks_or_denies(policy_env, monkeypatch):
    """B4 is observe/escalate-only: never changes decision to Block or Deny."""
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_B4", "enforce")
    audit_sink = MemoryAuditSink()
    policy = load_policy()
    
    # Judge with strong concerns
    judge = StubLlmJudge(
        concerns=("critical issue", "major concern"),
        confidence=0.95,
        flags=("hallucination", "inconsistency"),
    )
    
    runtime = ContentHookRuntime(
        policy=policy,
        llm_judge=judge,
        audit_sink=audit_sink,
    )
    
    critique = await runtime.judge(
        content="Concerning output",
        correlation_id="test-block",
        agent_identity="intake-gpt",
        context={},
    )
    
    # Critique returned
    assert critique is not None
    assert len(critique.concerns) == 2
    
    # Audit decision is "Allow" (B4 never blocks)
    assert len(audit_sink.entries) == 1
    entry = audit_sink.entries[0]
    disposition_data = entry.get("disposition", {})
    assert disposition_data.get("decision") == "Allow"


# Notice callback integration

async def test_judge_with_concerns_emits_notice_via_callback(policy_env, monkeypatch):
    """judge() with concerns + notice_callback → emits formatted notice."""
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_B4", "observe")
    audit_sink = MemoryAuditSink()
    policy = load_policy()
    
    # Notice collector
    notices = []
    def callback(lines):
        notices.extend(lines)
    
    judge = StubLlmJudge(concerns=("hallucination",), confidence=0.9, flags=("hallucination",))
    
    runtime = ContentHookRuntime(
        policy=policy,
        llm_judge=judge,
        audit_sink=audit_sink,
        notice_callback=callback,
    )
    
    await runtime.judge(
        content="Concerning output",
        correlation_id="test-notice",
        agent_identity="intake-gpt",
        context={},
    )
    
    # Notice emitted
    assert len(notices) == 1
    assert "B4" in notices[0]
    assert "LLM judge" in notices[0]
    assert "Flagged" in notices[0]  # concerns-found → Flagged (observe mode)


async def test_judge_without_concerns_does_not_emit_notice(policy_env, monkeypatch):
    """judge() without concerns + notice_callback → NO notice (clean pass suppressed)."""
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_B4", "observe")
    audit_sink = MemoryAuditSink()
    policy = load_policy()
    
    notices = []
    def callback(lines):
        notices.extend(lines)
    
    judge = StubLlmJudge(concerns=(), confidence=0.95, flags=())
    
    runtime = ContentHookRuntime(
        policy=policy,
        llm_judge=judge,
        audit_sink=audit_sink,
        notice_callback=callback,
    )
    
    await runtime.judge(
        content="Clean output",
        correlation_id="test-clean",
        agent_identity="intake-gpt",
        context={},
    )
    
    # NO notice (clean pass suppressed per actionable-only filter)
    assert len(notices) == 0


# post_model_check no longer invokes judge (regression)

async def test_post_model_check_does_not_invoke_judge(policy_env, monkeypatch):
    """post_model_check should NOT invoke the judge (B4 extracted to judge())."""
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_B4", "observe")
    audit_sink = MemoryAuditSink()
    policy = load_policy()
    
    # Judge that records if it's called
    judge_called = []
    class TrackingJudge(LlmJudge):
        def __init__(self):
            super().__init__(llm_client=None)
        
        async def critique(self, model_output, context):
            judge_called.append((model_output, context))
            return JudgeCritique(concerns=(), confidence=0.9, flags=(), contributed_to_escalation=False, latency_ms=0.0)
    
    judge = TrackingJudge()
    
    runtime = ContentHookRuntime(
        policy=policy,
        llm_judge=judge,
        audit_sink=audit_sink,
    )
    
    # Run post_model_check
    await runtime.post_model_check(
        content="Model output",
        content_type="model_output",
        correlation_id="test-regression",
        agent_identity="intake-gpt",
        context={},
    )
    
    # Judge should NOT be called from post_model_check
    assert len(judge_called) == 0, "post_model_check should not invoke the judge"


# Latency tracking

async def test_judge_records_latency(policy_env, monkeypatch):
    """judge() records latency_ms in the returned critique."""
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_B4", "observe")
    audit_sink = MemoryAuditSink()
    policy = load_policy()
    
    judge = StubLlmJudge(concerns=(), confidence=0.9, flags=())
    
    runtime = ContentHookRuntime(
        policy=policy,
        llm_judge=judge,
        audit_sink=audit_sink,
    )
    
    critique = await runtime.judge(
        content="Test content",
        correlation_id="test-latency",
        agent_identity="intake-gpt",
        context={},
    )
    
    assert critique is not None
    assert critique.latency_ms >= 0  # Latency recorded

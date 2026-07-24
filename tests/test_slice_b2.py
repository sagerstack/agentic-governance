from __future__ import annotations

import asyncio
import json
import os
import pytest

from agentic_governance.adapters.grounding_validator import GroundingValidator, FactCheck, GroundingResult
from agentic_governance.adapters.llm_judge import JudgeCritique, LlmJudge, StubLlmJudge
from agentic_governance.adapters.policy_loader import load_policy
from agentic_governance.core.failure_handler import FailureReason, GracefulFailureHandler, StructuredFailure
from agentic_governance.integrations.langgraph_mcp.content_hooks import ContentHookRuntime
from agentic_governance.adapters.input_attack_detector import StubInputAttackDetector
from agentic_governance.adapters.pii_minimizer import StubPiiMinimizer


@pytest.fixture
def policy_env(monkeypatch):
    monkeypatch.setenv("RAG_MCP_URL", "http://rag")
    monkeypatch.setenv("DB_MCP_URL", "http://db")
    monkeypatch.setenv("CURRENCY_MCP_URL", "http://currency")


def _make_runtime(**kwargs):
    os.environ.setdefault("RAG_MCP_URL", "http://rag")
    os.environ.setdefault("DB_MCP_URL", "http://db")
    os.environ.setdefault("CURRENCY_MCP_URL", "http://currency")
    policy = load_policy()
    return ContentHookRuntime(policy=policy, **kwargs)


class MemoryAuditSink:
    def __init__(self):
        self.entries = []

    async def append_content(self, env, disp):
        from agentic_governance.adapters.jsonl_audit import build_content_audit_entry
        self.entries.append(build_content_audit_entry(env, disp))

    async def append(self, env, disp):
        await self.append_content(env, disp)


# GroundingValidator tests

def test_grounding_amount_match_passes():
    result = GroundingValidator().validate({"amount": "50.00"}, {"amount": "50.00"})
    assert result.passed


def test_grounding_amount_mismatch_escalates():
    result = GroundingValidator().validate({"amount": "99.99"}, {"amount": "50.00"})
    check = next(c for c in result.checks if c.fact_name == "amount")
    assert not check.passed and check.disposition_on_fail == "Escalate"


def test_grounding_date_match_passes():
    result = GroundingValidator().validate({"date": "2026-07-23"}, {"date": "2026-07-23"})
    assert result.passed


def test_grounding_date_mismatch_blocks():
    """Date mismatch -> Block (spec: 'reject')."""
    result = GroundingValidator().validate({"date": "2020-01-01"}, {"date": "2026-07-23"})
    check = next(c for c in result.checks if c.fact_name == "date")
    assert not check.passed and check.disposition_on_fail == "Block"


def test_grounding_vendor_match_passes():
    result = GroundingValidator().validate({"vendor": "ACME"}, {"vendor": "acme"})
    assert result.passed


def test_grounding_vendor_mismatch_escalates():
    result = GroundingValidator().validate({"vendor": "Fake Co"}, {"vendor": "ACME"})
    check = next(c for c in result.checks if c.fact_name == "vendor")
    assert not check.passed and check.disposition_on_fail == "Escalate"


def test_grounding_citation_in_rag_passes():
    result = GroundingValidator().validate({"cited_clauses": ["3.2.1"]}, {}, rag_clauses=["3.2.1", "4.1"])
    assert result.passed


def test_grounding_citation_not_in_rag_escalates():
    result = GroundingValidator().validate({"cited_clauses": ["FAKE"]}, {}, rag_clauses=["3.2.1"])
    check = next(c for c in result.checks if c.fact_name == "policy_citations")
    assert not check.passed and check.disposition_on_fail == "Escalate"


def test_grounding_missing_required_evidence_escalates():
    result = GroundingValidator().validate({"vendor": "ACME"}, {}, required_evidence_fields=["amount", "vendor"])
    check = next(c for c in result.checks if c.fact_name == "required_evidence")
    assert not check.passed


def test_grounding_fact_check_hashes_not_raw_values():
    result = GroundingValidator().validate({"amount": "99.99"}, {"amount": "50.00"})
    check = next(c for c in result.checks if c.fact_name == "amount")
    assert check.expected_ref != "50.00" and len(check.expected_ref) == 64
    assert check.actual_ref != "99.99" and len(check.actual_ref) == 64


# GracefulFailureHandler tests

@pytest.mark.asyncio
async def test_failure_handler_success_returns_result():
    async def ok():
        return {"ok": True}
    result = await GracefulFailureHandler().handle("test", ok())
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_failure_handler_timeout_returns_structured_failure():
    async def slow():
        await asyncio.sleep(100)
    result = await GracefulFailureHandler(timeout_seconds=0.01).handle("slow_op", slow())
    assert isinstance(result, StructuredFailure)
    assert result.reason == FailureReason.TIMEOUT.value
    assert result.retriable is True


@pytest.mark.asyncio
async def test_failure_handler_value_error_returns_malformed():
    async def bad():
        raise ValueError("bad")
    result = await GracefulFailureHandler().handle("bad_op", bad())
    assert isinstance(result, StructuredFailure)
    assert result.reason == FailureReason.MALFORMED.value
    assert result.retriable is False


@pytest.mark.asyncio
async def test_failure_handler_never_silently_continues():
    async def broken():
        await asyncio.sleep(100)
    result = await GracefulFailureHandler(timeout_seconds=0.01).handle("broken", broken())
    assert isinstance(result, StructuredFailure)
    assert result.failure_id is not None
    assert result.ts is not None


def test_structured_failure_has_no_raw_exception_fields():
    import dataclasses
    f = StructuredFailure(failure_id="x", reason="timeout", operation="op", correlation_id=None, retriable=True, ts="t")
    field_names = {fld.name for fld in dataclasses.fields(f)}
    assert "exception" not in field_names and "message" not in field_names


def test_structured_failure_is_frozen():
    from dataclasses import FrozenInstanceError
    f = StructuredFailure(failure_id="x", reason="timeout", operation="op", correlation_id=None, retriable=True, ts="t")
    with pytest.raises((FrozenInstanceError, AttributeError)):
        f.reason = "tampered"  # type: ignore[misc]


# LlmJudge tests

@pytest.mark.asyncio
async def test_llm_judge_observe_mode_never_escalates_alone(policy_env):
    # B4 default is observe
    stub = StubLlmJudge(concerns=("possible hallucination",))
    runtime = _make_runtime(llm_judge=stub)
    result = await runtime.post_model_check(
        json.dumps({"amount": "50", "date": "2026-07-23", "vendor": "ACME"}),
        content_type="model_output", correlation_id="t1", agent_identity="advisor",
        trusted_state={"amount": "50", "date": "2026-07-23", "vendor": "ACME"},
    )
    assert result.decision == "Allow"


@pytest.mark.asyncio
async def test_llm_judge_enforce_no_b3_finding_does_not_escalate(policy_env, monkeypatch):
    """B4 alone (even in enforce) cannot escalate without B3 finding."""
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_B4", "enforce")
    stub = StubLlmJudge(concerns=("suspicious reasoning",))
    runtime = _make_runtime(llm_judge=stub, grounding_validator=GroundingValidator())
    result = await runtime.post_model_check(
        json.dumps({"amount": "50", "date": "2026-07-23", "vendor": "ACME"}),
        content_type="model_output", correlation_id="t2", agent_identity="advisor",
        trusted_state={"amount": "50", "date": "2026-07-23", "vendor": "ACME"},
    )
    assert result.decision == "Allow"  # B4 alone cannot escalate


@pytest.mark.asyncio
async def test_llm_judge_off_mode_skips(policy_env, monkeypatch):
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_B4", "off")
    stub = StubLlmJudge(concerns=("huge concern",))
    runtime = _make_runtime(llm_judge=stub)
    result = await runtime.post_model_check("output", content_type="model_output", correlation_id="t3", agent_identity="advisor")
    b4 = [c for c in result.fired_controls if c["controlId"] == "B4"]
    assert b4[0]["result"] == "skipped-disabled"


@pytest.mark.asyncio
async def test_llm_judge_failure_does_not_break_pipeline(policy_env):
    class FailingJudge(LlmJudge):
        async def critique(self, *a, **kw):
            raise RuntimeError("judge failed")
    runtime = _make_runtime(llm_judge=FailingJudge())
    result = await runtime.post_model_check("output", content_type="model_output", correlation_id="t4", agent_identity="advisor")
    assert result.decision in ("Allow", "Transform", "Escalate", "Block")


# post_model_check integration

@pytest.mark.asyncio
async def test_post_model_check_clean_output_allows(policy_env):
    runtime = _make_runtime(pii_minimizer=StubPiiMinimizer(has_pii=False), grounding_validator=GroundingValidator())
    result = await runtime.post_model_check(
        json.dumps({"amount": "50", "date": "2026-07-23", "vendor": "ACME"}),
        content_type="model_output", correlation_id="t5", agent_identity="advisor",
        trusted_state={"amount": "50", "date": "2026-07-23", "vendor": "ACME"},
    )
    assert result.decision == "Allow" and result.should_proceed


@pytest.mark.asyncio
async def test_post_model_check_grounding_amount_mismatch_escalates(policy_env, monkeypatch):
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_B3", "enforce")
    runtime = _make_runtime(pii_minimizer=StubPiiMinimizer(has_pii=False), grounding_validator=GroundingValidator())
    result = await runtime.post_model_check(
        json.dumps({"amount": "999.99", "vendor": "ACME"}),
        content_type="model_output", correlation_id="t6", agent_identity="advisor",
        trusted_state={"amount": "50.00", "vendor": "ACME"},
    )
    assert result.decision == "Escalate"


@pytest.mark.asyncio
async def test_post_model_check_date_mismatch_blocks(policy_env, monkeypatch):
    monkeypatch.setenv("AGENTIC_GOV_ENABLE_B3", "enforce")
    runtime = _make_runtime(pii_minimizer=StubPiiMinimizer(has_pii=False), grounding_validator=GroundingValidator())
    result = await runtime.post_model_check(
        json.dumps({"date": "2020-01-01"}),
        content_type="model_output", correlation_id="t7", agent_identity="advisor",
        trusted_state={"date": "2026-07-23"},
    )
    assert result.decision == "Block"


@pytest.mark.asyncio
async def test_post_model_check_emits_audit_entry(policy_env):
    sink = MemoryAuditSink()
    runtime = _make_runtime(audit_sink=sink)
    await runtime.post_model_check("clean output", content_type="model_output", correlation_id="t8", agent_identity="advisor")
    assert len(sink.entries) == 1 and "contentRef" in sink.entries[0]

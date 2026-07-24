"""Content governance composition root — install_content_hooks().

Builds a ContentHookRuntime with B1-B6 adapters, wiring all available
content controls with graceful degradation for missing heavy dependencies.
"""

from __future__ import annotations

import logging
from typing import Any

from agentic_governance.adapters.policy_loader import LoadedPolicy, load_policy
from agentic_governance.adapters.jsonl_audit import JsonlAuditSink
from agentic_governance.integrations.langgraph_mcp.content_hooks import ContentHookRuntime


logger = logging.getLogger(__name__)


def install_content_hooks(
    *,
    policy: LoadedPolicy | None = None,
    audit_sink: Any | None = None,
) -> ContentHookRuntime:
    """Build ContentHookRuntime with all available B1-B6 content adapters.
    
    Gracefully degrades when heavy dependencies (transformers, presidio) are missing:
    the adapter is set to None → the control is skipped and audited as skipped.
    
    Args:
        policy: Loaded policy object. If None, loads from load_policy().
        audit_sink: Audit sink for content events. If None, creates JsonlAuditSink.
                   CRITICAL: When integrating with Group A, pass the SAME sink
                   instance to both install() and install_content_hooks() to
                   achieve unified action + content audit with shared correlation IDs.
    
    Returns:
        ContentHookRuntime instance (NOT a singleton — each graph creates its own).
    """
    # Load policy if not provided
    if policy is None:
        policy = load_policy()
    
    # Create audit sink if not provided (but caller should pass the shared sink)
    if audit_sink is None:
        audit_sink = JsonlAuditSink("./.agentic_governance/")
    
    # B1: InputAttackDetector (DeBERTa-based prompt injection detection)
    # Heavy dep: transformers (HuggingFace)
    attack_detector = None
    try:
        from agentic_governance.adapters.input_attack_detector import InputAttackDetector
        attack_detector = InputAttackDetector()
    except ImportError as exc:
        logger.warning(
            "B1 input-attack-detection: transformers not available, control will be skipped. "
            "Install with: pip install 'agentic-governance[content]' (%s)",
            exc,
        )
    except Exception as exc:
        logger.warning(
            "B1 input-attack-detection: failed to initialize InputAttackDetector, control will be skipped. "
            "Error: %s",
            exc,
        )
    
    # B2: PiiMinimizer (Presidio-based PII detection and anonymization)
    # Heavy dep: presidio-analyzer, presidio-anonymizer
    pii_minimizer = None
    try:
        from agentic_governance.adapters.pii_minimizer import PiiMinimizer
        pii_minimizer = PiiMinimizer()
    except ImportError as exc:
        logger.warning(
            "B2 pii-minimization: presidio not available, control will be skipped. "
            "Install with: pip install 'agentic-governance[content]' (%s)",
            exc,
        )
    except Exception as exc:
        logger.warning(
            "B2 pii-minimization: failed to initialize PiiMinimizer, control will be skipped. "
            "Error: %s",
            exc,
        )
    
    # B3: GroundingValidator (deterministic fact checker)
    # No heavy deps — pure Python
    grounding_validator = None
    try:
        from agentic_governance.adapters.grounding_validator import GroundingValidator
        grounding_validator = GroundingValidator()
    except Exception as exc:
        logger.warning(
            "B3 grounded-output-validation: failed to initialize GroundingValidator, control will be skipped. "
            "Error: %s",
            exc,
        )
    
    # B4: LlmJudge (observe-only LLM critique)
    # No heavy deps — llm_client is None by default, which LlmJudge handles gracefully
    llm_judge = None
    try:
        from agentic_governance.adapters.llm_judge import LlmJudge
        # LlmJudge with llm_client=None returns empty critiques (safe fallback)
        llm_judge = LlmJudge(llm_client=None)
    except Exception as exc:
        logger.warning(
            "B4 llm-judge: failed to initialize LlmJudge, control will be skipped. "
            "Error: %s",
            exc,
        )
    
    # B5: GracefulFailureHandler (structured failure handling)
    # No heavy deps — always instantiate
    failure_handler = None
    try:
        from agentic_governance.core.failure_handler import GracefulFailureHandler
        failure_handler = GracefulFailureHandler()
    except Exception as exc:
        logger.warning(
            "B5 graceful-failure: failed to initialize GracefulFailureHandler, control will be skipped. "
            "Error: %s",
            exc,
        )
    
    # B6: ExplanationGenerator (three-tier material explanations)
    # No heavy deps — always instantiate
    explanation_generator = None
    try:
        from agentic_governance.core.explanation_generator import ExplanationGenerator
        explanation_generator = ExplanationGenerator()
    except Exception as exc:
        logger.warning(
            "B6 material-explanation: failed to initialize ExplanationGenerator, control will be skipped. "
            "Error: %s",
            exc,
        )
    
    # Build and return ContentHookRuntime with all available adapters
    return ContentHookRuntime(
        policy=policy,
        audit_sink=audit_sink,
        attack_detector=attack_detector,
        pii_minimizer=pii_minimizer,
        grounding_validator=grounding_validator,
        llm_judge=llm_judge,
        failure_handler=failure_handler,
        explanation_generator=explanation_generator,
    )

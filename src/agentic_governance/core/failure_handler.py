from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, TypeVar
from uuid import uuid4


T = TypeVar("T")


class FailureReason(str, Enum):
    TIMEOUT = "timeout"
    MALFORMED = "malformed"
    MISSING = "missing"
    PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True)
class StructuredFailure:
    """Standardized failure record.

    NEVER stores raw exception messages (may leak PII/secrets).
    The 'retriable' field signals the CALLER whether it's safe to retry
    with a fresh coroutine.
    """
    failure_id: str
    reason: str           # FailureReason value
    operation: str        # Which operation failed (not the exception message)
    correlation_id: str | None
    retriable: bool
    ts: str               # UTC ISO timestamp


class GracefulFailureHandler:
    """Wraps async operations with structured failure handling.

    NEVER silent continuation. Always returns StructuredFailure or the real result.
    Coroutines are single-use: retry = caller calls handle() again with a fresh coro.
    The 'retriable' field on StructuredFailure signals whether retry is safe.
    """

    def __init__(self, *, timeout_seconds: float = 30.0, max_retries: int = 1) -> None:
        self._timeout = timeout_seconds
        self._max_retries = max_retries  # stored but not used in single-coro handle()

    async def handle(
        self,
        operation: str,
        coro: Awaitable[T],
        *,
        correlation_id: str | None = None,
    ) -> T | StructuredFailure:
        """Execute coro, return result or StructuredFailure. Never raises. Never silently continues."""
        try:
            return await asyncio.wait_for(coro, timeout=self._timeout)
        except asyncio.TimeoutError:
            return self._make_failure(operation, FailureReason.TIMEOUT, correlation_id, retriable=True)
        except (ValueError, KeyError, json.JSONDecodeError):
            return self._make_failure(operation, FailureReason.MALFORMED, correlation_id, retriable=False)
        except LookupError:
            return self._make_failure(operation, FailureReason.MISSING, correlation_id, retriable=False)
        except Exception:
            return self._make_failure(operation, FailureReason.PROVIDER_ERROR, correlation_id, retriable=True)

    def _make_failure(
        self, operation: str, reason: FailureReason,
        correlation_id: str | None, retriable: bool,
    ) -> StructuredFailure:
        return StructuredFailure(
            failure_id=str(uuid4()), reason=reason.value, operation=operation,
            correlation_id=correlation_id, retriable=retriable,
            ts=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def is_failure(result: Any) -> bool:
        return isinstance(result, StructuredFailure)

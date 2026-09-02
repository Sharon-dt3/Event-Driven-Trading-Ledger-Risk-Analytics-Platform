"""Request-scoped correlation id helpers."""
from __future__ import annotations

import uuid
from contextvars import ContextVar

CORRELATION_HEADER = "X-Correlation-ID"

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


def set_correlation_id(value: str) -> None:
    _correlation_id.set(value)


def get_correlation_id() -> str:
    return _correlation_id.get()


def new_correlation_id() -> str:
    return str(uuid.uuid4())

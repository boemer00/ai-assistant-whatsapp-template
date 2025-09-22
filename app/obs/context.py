"""Scaffold: request context helpers using ContextVars.

Provides placeholders for request-scoped identifiers such as request_id and
user-related identifiers (e.g., message_sid, from number). Implementation to
be added later.
"""

from contextvars import ContextVar
from typing import Optional


# Public ContextVars (names are stable API)
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
message_sid_var: ContextVar[Optional[str]] = ContextVar("message_sid", default=None)
from_var: ContextVar[Optional[str]] = ContextVar("from_number", default=None)


def clear_context() -> None:
    """Reset context variables to defaults."""
    request_id_var.set(None)
    message_sid_var.set(None)
    from_var.set(None)

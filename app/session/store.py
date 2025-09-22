from __future__ import annotations

"""Scaffold: simple in-memory TTL session store.

This module declares a small API and docstrings; implementation will follow.
"""

from typing import Optional, Dict, Any
import time
import threading


class SessionStore:
    """In-memory session dictionary with TTL semantics."""

    def __init__(self, ttl_seconds: int = 900):
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._data: Dict[str, Dict[str, Any]] = {}

    def _expired(self, rec: Dict[str, Any]) -> bool:
        return (time.time() - rec.get("updated_at", 0)) > self.ttl_seconds

    def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Return session state if not expired, else None."""
        with self._lock:
            rec = self._data.get(user_id)
            if not rec:
                return None
            if self._expired(rec):
                self._data.pop(user_id, None)
                return None
            return rec.get("state")

    def set(self, user_id: str, state: Dict[str, Any]) -> None:
        """Save session state for user_id."""
        now = time.time()
        with self._lock:
            self._data[user_id] = {
                "state": state,
                "updated_at": now,
                "started_at": self._data.get(user_id, {}).get("started_at", now),
            }

    def clear(self, user_id: str) -> None:
        """Delete session state for user_id."""
        with self._lock:
            self._data.pop(user_id, None)

    def touch(self, user_id: str) -> None:
        """Update last-seen timestamp to avoid expiration."""
        with self._lock:
            if user_id in self._data:
                self._data[user_id]["updated_at"] = time.time()

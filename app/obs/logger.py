"""Structured JSON logging to stdout.

Low overhead, minimal dependencies, safe for production stdout collectors.
"""

from typing import Any, Dict
from datetime import datetime, timezone
import json

from app.obs.context import request_id_var, message_sid_var, from_var


def _redact_phone(value: Any) -> Any:
    s = str(value) if value is not None else ""
    if not s:
        return s
    digits = [c for c in s if c.isdigit()]
    if len(digits) < 4:
        return "***"
    tail = "".join(digits[-4:])
    return f"***{tail}"


def log_event(event: str, **fields: Any) -> None:
    now = datetime.now(timezone.utc).isoformat()
    payload: Dict[str, Any] = {
        "ts": now,
        "level": fields.pop("level", "INFO"),
        "event": event,
        "request_id": request_id_var.get(),
    }
    # Attach context vars if not provided explicitly
    payload.setdefault("message_sid", message_sid_var.get())
    if "user_from" not in fields:
        payload["user_from"] = _redact_phone(from_var.get())

    # Merge remaining fields
    for k, v in fields.items():
        if k in ("from", "from_number", "user_from"):
            payload["user_from"] = _redact_phone(v)
        else:
            payload[k] = v

    try:
        print(json.dumps(payload, separators=(",", ":")))
    except Exception:
        # As a last resort, avoid crashing the app due to logging
        pass

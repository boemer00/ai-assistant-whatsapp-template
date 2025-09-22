from __future__ import annotations

"""Merge helpers to accumulate conversational inputs into session state."""

from typing import Dict, Any, List
import re
from app.utils.dates import to_iso_date


def extract_codes(text: str) -> List[str]:
    """Extract 3-letter IATA-like tokens from text."""
    if not text:
        return []
    tokens = re.findall(r"\b([A-Z]{3})\b", text.upper())
    stop3 = {"AND", "THE", "FOR", "VIA", "BUT", "NOT"}
    # Deduplicate preserving order
    seen = set()
    out: List[str] = []
    for t in tokens:
        if t in stop3:
            continue
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def merge_message(state: Dict[str, Any], text: str,
                  pending_origin: List[str] | None,
                  pending_dest: List[str] | None) -> Dict[str, Any]:
    """Merge current user message into state.

    - Accept explicit codes and intersect with pending options when present
    - Capture date and passengers heuristically
    """
    s = dict(state or {})
    s.setdefault("intent", {})

    codes = extract_codes(text)
    if codes:
        po = set(pending_origin or [])
        pd = set(pending_dest or [])
        # Assign codes to sides if pending options present
        for code in codes:
            if po and code in po and not s.get("origin_code"):
                s["origin_code"] = code
            elif pd and code in pd and not s.get("destination_code"):
                s["destination_code"] = code
        # If one side still empty and only one code, assign to the empty side
        if len(codes) == 1:
            if not s.get("origin_code") and not po:
                s["origin_code"] = codes[0]
            elif not s.get("destination_code") and not pd:
                s["destination_code"] = codes[0]

    # Passengers (e.g., "2 adults", "3 people", "2 pax")
    m = re.search(r"(\d+)\s*(adults?|people|pax)", text, re.IGNORECASE)
    if m:
        try:
            s["intent"]["passengers"] = int(m.group(1))
        except Exception:
            pass

    # Dates - prefer setting departure_date if empty
    iso = to_iso_date(text)
    if iso and not s["intent"].get("departure_date"):
        s["intent"]["departure_date"] = iso

    return s


def is_ready_for_confirmation(state: Dict[str, Any]) -> bool:
    """Return True if origin/destination codes and a departure date are set."""
    if not state:
        return False
    origin = state.get("origin_code")
    dest = state.get("destination_code")
    dep = (state.get("intent") or {}).get("departure_date")
    return bool(origin and dest and dep)


def is_ready_to_search(state: Dict[str, Any]) -> bool:
    """Return True if confirmation accepted and required fields present."""
    return bool(is_ready_for_confirmation(state) and state.get("confirmed"))

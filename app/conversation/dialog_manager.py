"""Dialog Manager scaffold.

This module defines a minimal dialog/slot manager responsible for:
- Deciding whether to ask for travel preferences once core intent is present
- Building a compact preferences prompt summarizing the trip and choices
- Parsing short replies to capture user preferences
- Applying sensible defaults when the user opts for them
- Summarizing the trip for display

Implementation will be provided in the next step. This file only contains
interfaces, type hints, and docstrings.
"""

from typing import Optional, Dict, List, Any

try:
    # IATADb is optional in runtime; import for type hints only.
    from app.iata.lookup import IATADb  # type: ignore
except Exception:  # pragma: no cover - type-only dependency
    IATADb = object  # type: ignore


class DialogManager:
    """Minimal dialog/slot manager interface (scaffold).

    The dialog manager orchestrates a small set of follow-up questions to
    refine a flight search request after core fields are available.

    Session contract (mutable keys under a dict-like session object):
    - session["stage"]: Optional[str] — None | "awaiting_preferences"
    - session["preferences"]: Dict[str, Any] with the following optional keys:
        - origin_airports: List[str]
        - destination_airports: List[str]
        - time_window: str ("early_morning" | "morning" | "afternoon" | "evening" | "any")
        - cabin: str ("economy" | "premium_economy" | "business")
        - baggage: str ("hand_only" | "checked")
        - nonstop_only: bool
        - seat_prefs: str (free text; optional)
    """

    def __init__(self, iata_db: Optional["IATADb"] = None) -> None:
        """Create a dialog manager with optional IATA database access."""
        self.iata_db = iata_db

    def should_ask_preferences(self, info: Dict[str, Any], session: Dict[str, Any]) -> bool:
        """Return True if we should ask the one-shot preferences prompt.

        Expected behavior (to be implemented):
        - Return True when required fields (origin, destination, departure_date)
          are present and we have not already asked for preferences in this
          session.
        - Otherwise return False.
        """
        required_ok = bool(info.get("origin") and info.get("destination") and info.get("departure_date"))
        if not required_ok:
            return False

        # If we've already asked, don't ask again in this session
        if session.get("stage") == "awaiting_preferences":
            return False

        # If preferences already exist, skip asking
        prefs = session.get("preferences") or {}
        has_any_pref = any(
            k in prefs and prefs.get(k) not in (None, [], "")
            for k in (
                "origin_airports",
                "destination_airports",
                "time_window",
                "cabin",
                "baggage",
                "nonstop_only",
                "seat_prefs",
            )
        )
        return not has_any_pref

    def build_preferences_prompt(self, info: Dict[str, Any]) -> str:
        """Return a compact, friendly prompt asking for preferences.

        The prompt should include:
        - Trip summary: From, To, Date, Passengers, Trip type (one-way/round)
        - Preference choices with short labels:
          1) Airports (show common groups if city recognized; e.g., LHR/LGW...)
          2) Time window (Early morning / Morning / Afternoon / Evening / No preference)
          3) Cabin & baggage (Economy / Premium Economy / Business; Hand-only vs Checked)
          4) Non-stop vs any (Non-stop only vs open to 1 stop)
          5) Seat & extras (optional free text)
        """
        summary = self.summarize_trip(info)

        origin_group = self._airport_group_line(info.get("origin"))
        dest_group = self._airport_group_line(info.get("destination"))

        lines: List[str] = []
        lines.append(f"{summary}")
        if origin_group:
            lines.append(f"- Origin airports: {origin_group}")
        if dest_group:
            lines.append(f"- Destination airports: {dest_group}")
        lines.append("- Time window: Early morning / Morning / Afternoon / Evening / No preference")
        lines.append("- Cabin & bags: Economy / Premium Economy / Business; Hand only or Checked")
        lines.append("- Non-stop vs any: Non-stop only, or open to 1 stop if cheaper")
        lines.append("- Seat & extras (optional): e.g., sit together, aisle/window")
        lines.append("")
        lines.append("Reply with any preferences (e.g., 'LHR & CDG, morning, economy, hand only, nonstop').")
        lines.append("Or say 'use defaults' and I'll pick sensible options.")

        return "\n".join(lines)

    def parse_preference_reply(
        self,
        text: str,
        info: Dict[str, Any],
        session: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse a user reply to the preferences prompt.

        Return a dict containing:
        - "preferences_update": Dict[str, Any] — partial updates to merge into
          session["preferences"]. Keys may include origin_airports,
          destination_airports, time_window, cabin, baggage, nonstop_only,
          seat_prefs.
        - "done": bool — True if the reply indicates we should proceed (e.g.,
          user says "yes", "use defaults", or otherwise confirms).
        - "ack": Optional[str] — an optional short acknowledgement message that
          can be sent back to the user (e.g., "Great — nonstop economy in the
          morning. Ready to search?").
        """
        text_l = (text or "").strip().lower()
        prefs_update: Dict[str, Any] = {}
        ack_parts: List[str] = []

        # Quick confirmations / defaults
        confirmations = {"yes", "yep", "yeah", "confirm", "go ahead", "proceed", "ok", "okay", "search", "search now", "ready"}
        default_markers = {"use defaults", "defaults", "sensible defaults", "pick defaults", "choose defaults", "that’s fine", "thats fine", "fine", "looks good", "all good"}

        if any(marker in text_l for marker in default_markers):
            defaults = self.apply_defaults(info)
            prefs_update.update(defaults)
            return {"preferences_update": prefs_update, "done": True, "ack": "Using sensible defaults. Ready to search?"}

        if any(word in text_l for word in confirmations):
            return {"preferences_update": {}, "done": True, "ack": "Great — proceeding."}

        # Parse nonstop preference
        nonstop_true_markers = ["non-stop", "nonstop", "direct"]
        if any(k in text_l for k in nonstop_true_markers):
            prefs_update["nonstop_only"] = True
            ack_parts.append("non-stop")
        if "1 stop" in text_l or "one stop" in text_l or "any stop" in text_l or "any" == text_l:
            prefs_update["nonstop_only"] = False
            ack_parts.append("allow 1 stop")

        # Parse cabin
        if "premium economy" in text_l:
            prefs_update["cabin"] = "premium_economy"
            ack_parts.append("premium economy")
        elif "business" in text_l:
            prefs_update["cabin"] = "business"
            ack_parts.append("business")
        elif "economy" in text_l:
            prefs_update["cabin"] = "economy"
            ack_parts.append("economy")

        # Parse baggage
        if any(k in text_l for k in ["hand only", "hand-only", "hand luggage", "hand baggage", "carry on", "carry-on", "cabin bag", "cabin baggage"]):
            prefs_update["baggage"] = "hand_only"
            ack_parts.append("hand-only")
        if "checked" in text_l:
            prefs_update["baggage"] = "checked"
            ack_parts.append("checked bag")

        # Parse time window
        if "early morning" in text_l:
            prefs_update["time_window"] = "early_morning"
            ack_parts.append("early morning")
        elif "morning" in text_l:
            prefs_update["time_window"] = "morning"
            ack_parts.append("morning")
        elif "afternoon" in text_l:
            prefs_update["time_window"] = "afternoon"
            ack_parts.append("afternoon")
        elif "evening" in text_l:
            prefs_update["time_window"] = "evening"
            ack_parts.append("evening")
        elif "no preference" in text_l or text_l == "any":
            prefs_update["time_window"] = "any"
            ack_parts.append("no time preference")

        # Parse airports (IATA codes present in text). Minimal approach: map codes that match origin/destination groups.
        origin_codes: List[str] = []
        dest_codes: List[str] = []
        if self.iata_db is not None:
            origin_codes = self.iata_db.resolve(str(info.get("origin", ""))) or []
            dest_codes = self.iata_db.resolve(str(info.get("destination", ""))) or []

        # Extract 3-letter codes in any case; normalize to upper
        import re
        found = [m.group(0).upper() for m in re.finditer(r"\b([A-Za-z]{3})\b", text)]
        selected_origin: List[str] = []
        selected_dest: List[str] = []
        for code in found:
            if origin_codes and code in origin_codes:
                if code not in selected_origin:
                    selected_origin.append(code)
            elif dest_codes and code in dest_codes:
                if code not in selected_dest:
                    selected_dest.append(code)

        if selected_origin:
            prefs_update["origin_airports"] = selected_origin
        if selected_dest:
            prefs_update["destination_airports"] = selected_dest

        ack = None
        if prefs_update:
            if ack_parts:
                ack = "Got it — " + ", ".join(ack_parts) + ". Ready to search?"
            else:
                ack = "Got it. Ready to search?"

        return {"preferences_update": prefs_update, "done": False, "ack": ack}

    def apply_defaults(self, info: Dict[str, Any]) -> Dict[str, Any]:
        """Return a default preferences dict to use when user opts for defaults.

        Suggested defaults (to be implemented):
        - cabin = "economy"
        - baggage = "hand_only"
        - nonstop_only = True
        - time_window = "morning"
        If origin/destination correspond to well-known cities, you may choose a
        primary airport (e.g., LHR for London, CDG for Paris) as a single code
        to avoid multi-airport complexity in the initial version.
        """
        defaults: Dict[str, Any] = {
            "cabin": "economy",
            "baggage": "hand_only",
            "nonstop_only": True,
            "time_window": "morning",
        }

        # Prefer a primary airport when obvious.
        origin = str(info.get("origin") or "").strip().lower()
        destination = str(info.get("destination") or "").strip().lower()

        def choose_primary(city: str) -> List[str]:
            mapping = {
                "london": ["LHR", "LGW", "LCY", "STN", "LTN"],
                "paris": ["CDG", "ORY"],
            }
            candidates = mapping.get(city) or []
            if candidates:
                return [candidates[0]]
            # Fall back to first resolved code if possible
            if self.iata_db is not None:
                try:
                    resolved = self.iata_db.resolve(city)
                    if resolved:
                        return [resolved[0]]
                except Exception:
                    pass
            return []

        oa = choose_primary(origin)
        da = choose_primary(destination)
        if oa:
            defaults["origin_airports"] = oa
        if da:
            defaults["destination_airports"] = da

        return defaults

    def summarize_trip(self, info: Dict[str, Any]) -> str:
        """Return a short one-line trip summary for prompts and confirmations."""
        origin = info.get("origin") or "?"
        destination = info.get("destination") or "?"
        dep = info.get("departure_date") or "?"
        pax = int(info.get("passengers")) if info.get("passengers") else 1
        trip_type = "Round-trip" if info.get("return_date") else "One-way"
        return f"Trip: {origin} → {destination} on {dep}, {pax} adult(s). {trip_type}."

    # Internal helpers
    def _airport_group_line(self, place: Optional[str]) -> str:
        if not place:
            return ""
        if self.iata_db is None:
            return ""
        try:
            codes = self.iata_db.resolve(str(place))
            if not codes:
                return ""
            top = codes[:5]
            return "/".join(top)
        except Exception:
            return ""

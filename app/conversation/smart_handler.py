import re
from typing import Dict, Optional, Any, List, Tuple
from datetime import datetime, timedelta
from enum import Enum

from app.session.redis_store import RedisSessionStore
from app.parse.fast_intent import fast_parse
from app.llm.extract_intent import extract_intent, IntentSchema
from app.amadeus.client import AmadeusClient
from app.formatters.whatsapp import format_reply, format_confirmation
from app.types import RankedResults
from langchain_openai import ChatOpenAI


class IntentConfidence:
    def __init__(self):
        self.scores = {}

    def add(self, field: str, value: Any, confidence: float):
        self.scores[field] = {"value": value, "confidence": confidence}

    def needs_confirmation(self, threshold: float = 0.8) -> List[str]:
        return [field for field, data in self.scores.items()
                if data["confidence"] < threshold]

    def get_value(self, field: str) -> Any:
        return self.scores.get(field, {}).get("value")


class SmartConversationHandler:
    def __init__(
        self,
        session_store: RedisSessionStore,
        amadeus_client: AmadeusClient,
        llm: ChatOpenAI = None
    ):
        self.session_store = session_store
        self.amadeus_client = amadeus_client
        self.llm = llm
        self.correction_patterns = self._compile_correction_patterns()

    def _compile_correction_patterns(self) -> Dict[str, re.Pattern]:
        return {
            "change_destination": re.compile(r"(?:change|make|switch).*(?:to|destination).*(\w+)", re.I),
            "change_date": re.compile(r"(?:change|make|switch).*(?:date|day).*(\d+|\w+)", re.I),
            "change_passengers": re.compile(r"(?:change|make|now).*(\d+).*(?:people|passengers|adults)", re.I),
            "add_return": re.compile(r"(?:add|include|with).*return.*(\d+|\w+)", re.I),
            "confirm": re.compile(r"^(?:yes|yep|yeah|correct|perfect|looks good|confirm)", re.I),
            "cancel": re.compile(r"^(?:no|cancel|stop|nevermind|forget it)", re.I),
        }

    def handle_message(self, user_id: str, message: str) -> str:
        # Get or create session
        session = self.session_store.get(user_id) or {"info": {}, "history": [], "preferences": {}}

        # Add message to history
        session["history"].append({"role": "user", "content": message, "timestamp": datetime.now().isoformat()})

        # Check if this is a correction/modification
        correction_type = self._detect_correction(message)
        if correction_type and session.get("info"):
            return self._handle_correction(user_id, session, message, correction_type)

        # Extract all entities from message
        entities, confidence = self._extract_with_confidence(message, session)

        # Merge with existing session info
        session["info"] = self._smart_merge(session["info"], entities)

        # Check what's missing
        missing_fields = self._get_missing_required_fields(session["info"])

        # If we have everything, confirm before searching
        if not missing_fields:
            # Check if user already confirmed
            if self._is_confirmation(message):
                return self._execute_search(user_id, session)
            else:
                # Generate natural confirmation
                return self._generate_confirmation(session["info"], confidence)

        # Ask for missing information naturally
        return self._ask_for_missing_info(missing_fields, session["info"])

    def _extract_with_confidence(self, message: str, session: Dict) -> Tuple[Dict, IntentConfidence]:
        confidence = IntentConfidence()

        # Try fast parse first
        intent = fast_parse(message)
        if intent:
            # High confidence for structured input
            if intent.origin:
                confidence.add("origin", intent.origin, 0.95)
            if intent.destination:
                confidence.add("destination", intent.destination, 0.95)
            if intent.departure_date:
                confidence.add("departure_date", intent.departure_date, 0.95)
            if intent.return_date:
                confidence.add("return_date", intent.return_date, 0.95)
            if intent.passengers:
                confidence.add("passengers", intent.passengers, 0.95)
        else:
            # Use LLM for natural language
            intent = extract_intent(self.llm, message)
            # Lower confidence for LLM extraction
            if intent.origin:
                confidence.add("origin", intent.origin, 0.8)
            if intent.destination:
                confidence.add("destination", intent.destination, 0.8)
            if intent.departure_date:
                confidence.add("departure_date", intent.departure_date, 0.7)
            if intent.return_date:
                confidence.add("return_date", intent.return_date, 0.7)
            if intent.passengers:
                confidence.add("passengers", intent.passengers or 1, 0.85)

        entities = {k: v["value"] for k, v in confidence.scores.items()}
        return entities, confidence

    def _smart_merge(self, existing: Dict, new: Dict) -> Dict:
        # Intelligently merge new info with existing
        merged = existing.copy()
        for key, value in new.items():
            if value is not None:
                merged[key] = value
        return merged

    def _get_missing_required_fields(self, info: Dict) -> List[str]:
        required = ["origin", "destination", "departure_date"]
        return [field for field in required if not info.get(field)]

    def _detect_correction(self, message: str) -> Optional[str]:
        for correction_type, pattern in self.correction_patterns.items():
            if pattern.search(message):
                return correction_type
        return None

    def _handle_correction(self, user_id: str, session: Dict, message: str, correction_type: str) -> str:
        info = session["info"]

        if correction_type == "change_destination":
            match = self.correction_patterns["change_destination"].search(message)
            if match:
                new_dest = match.group(1).upper()
                old_dest = info.get("destination", "unknown")
                info["destination"] = new_dest
                self.session_store.set(user_id, session)
                return f"Changed destination from {old_dest} to {new_dest}. Ready to search?"

        elif correction_type == "change_passengers":
            match = self.correction_patterns["change_passengers"].search(message)
            if match:
                new_count = int(match.group(1))
                info["passengers"] = new_count
                self.session_store.set(user_id, session)
                return f"Updated to {new_count} passengers. Shall I search now?"

        elif correction_type == "confirm":
            return self._execute_search(user_id, session)

        elif correction_type == "cancel":
            self.session_store.clear(user_id)
            return "No problem! Search cancelled. How else can I help you?"

        return "I didn't quite catch that. Could you clarify what you'd like to change?"

    def _is_confirmation(self, message: str) -> bool:
        return bool(self.correction_patterns["confirm"].search(message))

    def _generate_confirmation(self, info: Dict, confidence: IntentConfidence) -> str:
        # Check if any fields need clarification
        uncertain_fields = confidence.needs_confirmation()

        if uncertain_fields:
            # Ask about uncertain fields
            field_questions = {
                "departure_date": f"Just to confirm, you want to depart on {info['departure_date']}?",
                "destination": f"And you're flying to {info['destination']}, correct?",
                "origin": f"Flying from {info['origin']}, right?"
            }
            for field in uncertain_fields:
                if field in field_questions:
                    return field_questions[field]

        # Generate natural confirmation
        parts = [f"Perfect! Let me search for flights from {info['origin']} to {info['destination']}"]
        parts.append(f"departing {info['departure_date']}")
        if info.get('return_date'):
            parts.append(f"returning {info['return_date']}")
        if info.get('passengers', 1) > 1:
            parts.append(f"for {info['passengers']} passengers")

        return " ".join(parts) + ". Shall I proceed?"

    def _ask_for_missing_info(self, missing: List[str], info: Dict) -> str:
        # Generate natural prompts for missing info
        prompts = {
            "origin": "Where are you flying from?",
            "destination": "Where would you like to go?",
            "departure_date": "When would you like to depart?"
        }

        # Add context from what we already know
        if "origin" in missing and info.get("destination"):
            return f"Great! You want to go to {info['destination']}. Where are you flying from?"
        elif "destination" in missing and info.get("origin"):
            return f"Got it, flying from {info['origin']}. Where to?"
        elif "departure_date" in missing:
            context = []
            if info.get("origin"):
                context.append(f"from {info['origin']}")
            if info.get("destination"):
                context.append(f"to {info['destination']}")
            if context:
                return f"Nice! Flying {' '.join(context)}. What date?"
            else:
                return "When would you like to travel?"

        # Default to first missing field
        return prompts.get(missing[0], "Could you provide more details about your trip?")

    def _execute_search(self, user_id: str, session: Dict) -> str:
        info = session["info"]

        # Check cache first
        cache_key = self.session_store.create_search_key(
            info["origin"],
            info["destination"],
            info["departure_date"],
            info.get("return_date"),
            info.get("passengers", 1)
        )
        cached_results = self.session_store.get_cached_search(cache_key)

        if cached_results:
            # Return cached results immediately
            return self._format_results(cached_results, info, from_cache=True)

        # Mark session as searching
        session["searching"] = True
        self.session_store.set(user_id, session)

        # Execute search
        try:
            results = self.amadeus_client.search_flights(
                origin=info["origin"],
                destination=info["destination"],
                dep_date=info["departure_date"],
                ret_date=info.get("return_date"),
                adults=info.get("passengers", 1)
            )

            # Cache the results
            self.session_store.cache_search(cache_key, results)

            # Transform and format results
            from app.amadeus.transform import from_amadeus
            from app.rank.selector import rank_top
            options = from_amadeus(results)
            ranked = rank_top(options)

            # Store user preference based on selection
            self._update_preferences(user_id, session, ranked)

            return format_reply(IntentSchema(**info), ranked)

        except Exception as e:
            return f"I'm having trouble searching flights right now. Could you try again in a moment?"

    def _format_results(self, results: Any, info: Dict, from_cache: bool = False) -> str:
        from app.amadeus.transform import from_amadeus
        from app.rank.selector import rank_top
        options = from_amadeus(results)
        ranked = rank_top(options)

        response = format_reply(IntentSchema(**info), ranked)
        if from_cache:
            response = "Here are the flights (from recent searches):\n\n" + response
        return response

    def _update_preferences(self, user_id: str, session: Dict, results: RankedResults):
        # Track user preferences based on searches
        prefs = session.get("preferences", {})
        info = session["info"]

        # Track route preferences
        route = f"{info['origin']}-{info['destination']}"
        prefs.setdefault("frequent_routes", {})[route] = prefs.get("frequent_routes", {}).get(route, 0) + 1

        # Track time preferences
        if info.get("departure_date"):
            # Extract day of week preference
            try:
                dep_date = datetime.fromisoformat(info["departure_date"])
                day_name = dep_date.strftime("%A")
                prefs.setdefault("preferred_days", {})[day_name] = prefs.get("preferred_days", {}).get(day_name, 0) + 1
            except:
                pass

        session["preferences"] = prefs
        self.session_store.set(user_id, session)
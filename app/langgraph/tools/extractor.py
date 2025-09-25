"""
Information Extraction Tool for LangGraph Travel Assistant

Combines fast regex parsing with LLM extraction for robust travel entity recognition
with confidence scoring and ambiguity detection.
"""

from typing import Dict, List, Optional, Any, Tuple
from pydantic import BaseModel
# from langchain_core.tools import BaseTool  # Simplified for now
from langchain_openai import ChatOpenAI
import re
from datetime import datetime

from app.langgraph.state import TravelState


class ExtractionResult(BaseModel):
    """Result of travel information extraction"""
    extracted_fields: Dict[str, Any]
    field_confidence: Dict[str, float]
    ambiguous_fields: List[str]
    suggested_clarifications: List[str]
    extraction_method: str  # "fast_parse", "llm", "hybrid"


class InformationExtractorTool:
    """Extract travel entities with confidence scoring"""

    def __init__(self, llm: Optional[ChatOpenAI] = None):
        self.llm = llm
        self.correction_patterns = self._compile_correction_patterns()

    def _compile_correction_patterns(self) -> Dict[str, re.Pattern]:
        """Compile patterns for detecting corrections and modifications"""
        return {
            "date_correction": re.compile(r"(?:no,?\s+)?(?:on\s+)?(?:the\s+)?(\d+(?:st|nd|rd|th)?|\w+\s+\d+|[A-Za-z]+\s+\d+)", re.I),
            "change_destination": re.compile(r"(?:change|make|switch).*(?:to|destination).*?([A-Z]{3}|[A-Za-z]+)", re.I),
            "change_origin": re.compile(r"(?:change|make|switch).*(?:from|origin).*?([A-Z]{3}|[A-Za-z]+)", re.I),
            "change_passengers": re.compile(r"(?:change|make|now|actually).*?(\d+).*?(?:people|passengers|adults|person)", re.I),
            "add_return": re.compile(r"(?:add|include|with|need).*?return.*?(?:on\s+)?(\d+|\w+\s+\d+)", re.I),
            "make_oneway": re.compile(r"(?:one.way|oneway|no return|just one way)", re.I),
            "make_roundtrip": re.compile(r"(?:round.trip|roundtrip|return|coming back)", re.I),
        }

    def _run(self, message: str, current_state: TravelState) -> ExtractionResult:
        """Extract travel information from user message"""

        # First try fast parse for structured inputs
        fast_result = self._try_fast_parse(message, current_state)

        # Then try LLM for natural language with context
        llm_result = self._try_llm_extraction(message, current_state) if self.llm else None

        # Detect corrections to existing state
        corrections = self._detect_corrections(message, current_state)

        # Combine results intelligently
        final_result = self._combine_results(fast_result, llm_result, corrections, current_state)

        return final_result

    def _try_fast_parse(self, message: str, current_state: TravelState = None) -> Optional[Dict[str, Any]]:
        """Try fast regex-based parsing with inline patterns and context awareness"""
        try:
            # Quick patterns for structured inputs
            result = {
                "method": "fast_parse",
                "confidence": 0.95,
                "fields": {}
            }

            # Origin/destination patterns
            from_to = re.search(r'from\s+([A-Z]{3}|\w+)\s+to\s+([A-Z]{3}|\w+)', message, re.I)
            if from_to:
                result["fields"]["origin"] = from_to.group(1).upper()
                result["fields"]["destination"] = from_to.group(2).upper()

            # Date patterns
            date_match = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2}(?:st|nd|rd|th)?)', message, re.I)
            if date_match:
                result["fields"]["departure_date"] = date_match.group(1)

            # Passenger patterns
            pax_match = re.search(r'(\d+)\s*(?:passengers?|people|persons?|pax)', message, re.I)
            if pax_match:
                result["fields"]["passengers"] = int(pax_match.group(1))

            # Context-aware single city name parsing
            if not result["fields"] and current_state:
                single_city = re.search(r'^([A-Za-z]{3,}(?:\s+[A-Za-z]+)?)$', message.strip())
                if single_city:
                    city_name = single_city.group(1).strip()

                    # Get the last bot message to understand context
                    conversation_history = current_state.get("conversation_history", [])
                    last_bot_message = ""

                    if conversation_history:
                        for turn in reversed(conversation_history):
                            if "bot" in turn:
                                last_bot_message = turn["bot"].lower()
                                break

                    # Map single city to appropriate field based on context
                    if "flying from" in last_bot_message or "where are you from" in last_bot_message:
                        result["fields"]["origin"] = city_name.upper()
                        result["confidence"] = 0.90  # High confidence for context match
                        print(f"[DEBUG] Fast parse context: '{city_name}' mapped to origin based on '{last_bot_message[:50]}...'")
                    elif "where would you like to go" in last_bot_message or "destination" in last_bot_message:
                        result["fields"]["destination"] = city_name.upper()
                        result["confidence"] = 0.90
                        print(f"[DEBUG] Fast parse context: '{city_name}' mapped to destination based on '{last_bot_message[:50]}...'")

            return result if result["fields"] else None
        except Exception as e:
            print(f"[DEBUG] Fast parse error: {e}")
            return None

    def _try_llm_extraction(self, message: str, current_state: TravelState = None) -> Optional[Dict[str, Any]]:
        """Try LLM-based extraction for natural language with context awareness"""
        if not self.llm:
            return None

        try:
            # Get conversation context
            conversation_history = current_state.get("conversation_history", []) if current_state else []
            last_bot_message = ""

            if conversation_history:
                # Get the most recent bot message for context
                for turn in reversed(conversation_history):
                    if "bot" in turn:
                        last_bot_message = turn["bot"]
                        break

            # Build context-aware prompt
            system_prompt = """Extract travel information from the user's message. Consider the conversation context.

Return a JSON object with extracted fields:
{
  "origin": "departure city/airport code",
  "destination": "arrival city/airport code",
  "departure_date": "date string",
  "return_date": "return date if mentioned",
  "passengers": number,
  "trip_type": "one_way" or "round_trip"
}

Context clues:
- If bot asked "Where are you flying from?" and user gives a city → map to "origin"
- If bot asked "Where would you like to go?" and user gives a city → map to "destination"
- If user says just a city name, use the last bot question to determine if it's origin or destination
- Extract only fields that are clearly mentioned or implied by context

Only return the JSON object, no other text."""

            user_prompt = f"""Last bot message: "{last_bot_message}"
User's response: "{message}"

Extract travel information:"""

            # Call LLM with context
            response = self.llm.invoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ])

            # Parse JSON response
            import json
            try:
                extracted = json.loads(response.content.strip())

                # Filter out None/empty values
                fields = {k: v for k, v in extracted.items() if v is not None and v != ""}

                if fields:
                    result = {
                        "method": "llm",
                        "confidence": 0.85,  # Good confidence for context-aware extraction
                        "fields": fields
                    }
                    print(f"[DEBUG] LLM extracted with context: {fields}")
                    return result

            except (json.JSONDecodeError, AttributeError) as e:
                print(f"[DEBUG] LLM response parsing error: {e}")
                print(f"[DEBUG] Raw LLM response: {response.content}")

        except Exception as e:
            print(f"[DEBUG] LLM extraction error: {e}")

        return None

    def _detect_corrections(self, message: str, current_state: TravelState) -> Dict[str, Any]:
        """Detect corrections to existing information"""
        corrections = {}

        for correction_type, pattern in self.correction_patterns.items():
            match = pattern.search(message)
            if match:
                if correction_type == "date_correction":
                    # Parse the new date
                    from app.utils.dates import to_iso_date
                    date_str = match.group(1)
                    new_date = to_iso_date(date_str)
                    if new_date:
                        corrections["departure_date"] = new_date

                elif correction_type == "change_destination":
                    new_dest = match.group(1).strip().upper()
                    corrections["destination"] = new_dest

                elif correction_type == "change_origin":
                    new_origin = match.group(1).strip().upper()
                    corrections["origin"] = new_origin

                elif correction_type == "change_passengers":
                    try:
                        new_count = int(match.group(1))
                        if 1 <= new_count <= 9:
                            corrections["passengers"] = new_count
                    except ValueError:
                        pass

                elif correction_type == "add_return":
                    from app.utils.dates import to_iso_date
                    date_str = match.group(1)
                    return_date = to_iso_date(date_str)
                    if return_date:
                        corrections["return_date"] = return_date
                        corrections["trip_type"] = "round_trip"

                elif correction_type == "make_oneway":
                    corrections["trip_type"] = "one_way"
                    corrections["return_date"] = None

                elif correction_type == "make_roundtrip":
                    corrections["trip_type"] = "round_trip"

        return corrections

    def _combine_results(self, fast_result: Optional[Dict], llm_result: Optional[Dict],
                        corrections: Dict[str, Any], current_state: TravelState) -> ExtractionResult:
        """Intelligently combine extraction results"""

        extracted_fields = {}
        field_confidence = {}
        ambiguous_fields = []
        suggested_clarifications = []
        method = "none"

        # Apply corrections first (highest priority)
        if corrections:
            extracted_fields.update(corrections)
            for field in corrections:
                field_confidence[field] = 0.98  # Very high confidence for explicit corrections
            method = "correction"

        # Apply fast parse results (high confidence)
        if fast_result:
            for field, value in fast_result["fields"].items():
                if field not in extracted_fields:  # Don't override corrections
                    extracted_fields[field] = value
                    field_confidence[field] = fast_result["confidence"]
            method = "fast_parse" if method == "none" else f"{method}+fast_parse"

        # Apply LLM results (lower confidence, fill gaps)
        if llm_result:
            for field, value in llm_result["fields"].items():
                if field not in extracted_fields:  # Don't override corrections or fast parse
                    extracted_fields[field] = value
                    field_confidence[field] = llm_result["confidence"]
                elif field in extracted_fields and field_confidence.get(field, 0) < 0.9:
                    # Check for conflicts between methods
                    if extracted_fields[field] != value:
                        ambiguous_fields.append(field)
                        suggested_clarifications.append(
                            f"I found conflicting information for {field}: {extracted_fields[field]} vs {value}. Which is correct?"
                        )
            method = "llm" if method == "none" else f"{method}+llm"

        # Detect ambiguities and suggest clarifications
        self._detect_ambiguities(extracted_fields, field_confidence, ambiguous_fields, suggested_clarifications)

        return ExtractionResult(
            extracted_fields=extracted_fields,
            field_confidence=field_confidence,
            ambiguous_fields=ambiguous_fields,
            suggested_clarifications=suggested_clarifications,
            extraction_method=method if method != "none" else "no_extraction"
        )

    def _detect_ambiguities(self, fields: Dict[str, Any], confidence: Dict[str, float],
                           ambiguous: List[str], clarifications: List[str]) -> None:
        """Detect potential ambiguities that need clarification"""

        # Check for low confidence fields
        for field, conf in confidence.items():
            if conf < 0.7 and field not in ambiguous:
                ambiguous.append(field)
                clarifications.append(f"Just to confirm, {field} is {fields[field]}?")

        # Check for missing return date when departure is present
        if "departure_date" in fields and "return_date" not in fields:
            if "trip_type" not in fields:
                clarifications.append("Is this a one-way trip, or do you need a return flight?")

        # Check for unusual passenger counts
        if "passengers" in fields:
            count = fields["passengers"]
            if count > 6:
                clarifications.append(f"Just checking - you need {count} passenger tickets?")


# Helper function to create tool with LLM
def create_extraction_tool(llm: Optional[ChatOpenAI] = None) -> InformationExtractorTool:
    """Create information extraction tool with optional LLM"""
    return InformationExtractorTool(llm=llm)
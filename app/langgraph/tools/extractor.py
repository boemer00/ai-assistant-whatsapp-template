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

            # CONSERVATIVE Context-aware single city parsing (PHASE 1)
            if not result["fields"] and current_state:
                self._try_conservative_context_extraction(message, current_state, result)

            print(f"[DEBUG] Fast parse extracted: {result['fields'] if result['fields'] else 'nothing'}")
            return result if result["fields"] else None
        except Exception as e:
            print(f"[DEBUG] Fast parse error: {e}")
            return None

    def _try_conservative_context_extraction(self, message: str, current_state: TravelState, result: Dict[str, Any]):
        """PHASE 1: Ultra-conservative context-aware extraction with strict safety constraints"""
        try:
            # SAFETY CHECK 1: Only process simple single city names
            single_city_match = re.match(r'^([A-Za-z]{3,}(?:\s+[A-Za-z]+){0,2})$', message.strip())
            if not single_city_match:
                print(f"[DEBUG] Context extraction: '{message}' is not a simple city name - skipping")
                return

            city_name = single_city_match.group(1).strip()

            # SAFETY CHECK 1.5: Never extract common greetings/non-travel words as travel fields
            forbidden_words = {
                'hello', 'hi', 'hey', 'good', 'morning', 'afternoon', 'evening', 'thanks', 'thank', 'you',
                'please', 'yes', 'no', 'okay', 'ok', 'sure', 'great', 'perfect', 'excellent', 'nice'
            }
            if city_name.lower() in forbidden_words:
                print(f"[DEBUG] Context extraction: '{city_name}' is a forbidden word - never extract as travel field")
                return

            # SAFETY CHECK 2: Get conversation context
            conversation_history = current_state.get("conversation_history", [])
            if not conversation_history:
                print(f"[DEBUG] Context extraction: No conversation history - skipping")
                return

            # Get the most recent bot message
            last_bot_message = ""
            for turn in reversed(conversation_history):
                if "bot" in turn and turn["bot"]:
                    last_bot_message = turn["bot"].lower()
                    break

            if not last_bot_message:
                print(f"[DEBUG] Context extraction: No bot message found - skipping")
                return

            print(f"[DEBUG] Context extraction: Analyzing '{city_name}' in context of bot question: '{last_bot_message[:60]}...'")

            # SAFETY CHECK 3: Don't overwrite existing fields
            current_origin = current_state.get("origin")
            current_destination = current_state.get("destination")

            # ULTRA-CONSERVATIVE CONTEXT MAPPING - Only crystal clear cases
            extracted_field = None
            extracted_value = None

            # Case 1: Bot asked for origin, map to origin (if not already set)
            if ("where are you flying from" in last_bot_message or
                "flying from" in last_bot_message) and not current_origin:
                extracted_field = "origin"
                extracted_value = city_name.upper()
                print(f"[DEBUG] Context extraction: Bot asked for origin, mapping '{city_name}' to origin")

            # Case 2: Bot asked for destination, map to destination (if not already set)
            elif ("where would you like to go" in last_bot_message or
                  "where to" in last_bot_message or
                  "destination" in last_bot_message) and not current_destination:
                extracted_field = "destination"
                extracted_value = city_name.upper()
                print(f"[DEBUG] Context extraction: Bot asked for destination, mapping '{city_name}' to destination")

            else:
                print(f"[DEBUG] Context extraction: No clear context match - skipping extraction")
                return

            # SAFETY CHECK 4: Final validation before setting
            if extracted_field and extracted_value:
                # Double-check we're not creating conflicts
                if (extracted_field == "origin" and current_destination and
                    extracted_value.upper() == current_destination.upper()):
                    print(f"[DEBUG] Context extraction: Would create origin=destination conflict - skipping")
                    return

                if (extracted_field == "destination" and current_origin and
                    extracted_value.upper() == current_origin.upper()):
                    print(f"[DEBUG] Context extraction: Would create origin=destination conflict - skipping")
                    return

                # Safe to extract
                result["fields"][extracted_field] = extracted_value
                result["confidence"] = 0.90  # High confidence for clear context
                print(f"[DEBUG] Context extraction: SUCCESS - {extracted_field}={extracted_value}")

        except Exception as e:
            print(f"[DEBUG] Context extraction error: {e}")
            # Fail safely - don't extract anything if there's an error

    def _try_llm_extraction(self, message: str, current_state: TravelState = None) -> Optional[Dict[str, Any]]:
        """Try LLM-based extraction - temporarily disabled to isolate issues"""
        if not self.llm:
            return None

        # TEMPORARILY DISABLED: Return None to isolate if LLM extraction is causing issues
        print(f"[DEBUG] LLM extraction temporarily disabled for isolation testing")
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
"""
LangGraph Travel State Schema and Reducers

Defines the core TravelState schema and reducer functions for systematic
travel information collection and validation.
"""

from typing import Dict, List, Optional, Any, Literal
from typing_extensions import TypedDict
from datetime import datetime
import copy


class TravelState(TypedDict):
    """Core state schema for travel assistant conversations"""

    # Core Travel Intent
    origin: Optional[str]
    destination: Optional[str]
    departure_date: Optional[str]  # ISO format YYYY-MM-DD
    return_date: Optional[str]     # ISO format YYYY-MM-DD
    passengers: Optional[int]

    # Trip Classification
    trip_type: Literal["one_way", "round_trip", "undecided"]
    trip_type_confirmed: bool

    # Validation Pipeline
    required_fields_complete: bool
    field_confidence: Dict[str, float]
    validation_errors: List[str]
    ready_for_api: bool  # Critical gate keeper

    # Conversation Management
    conversation_history: List[Dict[str, Any]]
    missing_fields: List[str]
    clarification_attempts: int
    user_message: str
    bot_response: str

    # Search Results (populated after API call)
    search_results: Optional[Dict[str, Any]]
    search_cached: bool


def create_initial_state() -> TravelState:
    """Create initial empty state"""
    return TravelState(
        # Core fields
        origin=None,
        destination=None,
        departure_date=None,
        return_date=None,
        passengers=None,

        # Trip classification
        trip_type="undecided",
        trip_type_confirmed=False,

        # Validation
        required_fields_complete=False,
        field_confidence={},
        validation_errors=[],
        ready_for_api=False,

        # Conversation
        conversation_history=[],
        missing_fields=[],
        clarification_attempts=0,
        user_message="",
        bot_response="",

        # Results
        search_results=None,
        search_cached=False
    )


# State Reducer Functions
def add_extracted_info(current: TravelState, update: Dict[str, Any]) -> TravelState:
    """Add extracted travel information to state"""
    new_state = copy.deepcopy(current)

    for field, value in update.items():
        if field in ["origin", "destination", "departure_date", "return_date", "passengers"]:
            if value is not None:
                new_state[field] = value

    return new_state


def add_field_confidence(current: TravelState, field: str, confidence: float) -> TravelState:
    """Add confidence score for extracted field"""
    new_state = copy.deepcopy(current)
    new_state["field_confidence"][field] = confidence
    return new_state


def set_trip_type(current: TravelState, trip_type: Literal["one_way", "round_trip"],
                  confirmed: bool = True) -> TravelState:
    """Set trip type with confirmation status"""
    new_state = copy.deepcopy(current)
    new_state["trip_type"] = trip_type
    new_state["trip_type_confirmed"] = confirmed
    return new_state


def increment_clarification_attempts(current: TravelState) -> TravelState:
    """Increment clarification attempt counter"""
    new_state = copy.deepcopy(current)
    new_state["clarification_attempts"] += 1
    return new_state


def set_validation_status(current: TravelState, valid: bool, errors: List[str] = None) -> TravelState:
    """Set validation status and errors"""
    new_state = copy.deepcopy(current)
    new_state["required_fields_complete"] = valid
    new_state["validation_errors"] = errors or []
    return new_state


def set_api_ready(current: TravelState, ready: bool) -> TravelState:
    """Set API readiness gate"""
    new_state = copy.deepcopy(current)
    new_state["ready_for_api"] = ready
    return new_state


def update_conversation(current: TravelState, user_msg: str, bot_msg: str) -> TravelState:
    """Update conversation history and current messages"""
    new_state = copy.deepcopy(current)

    # Add previous turn to history if it exists and wasn't already added
    if current["user_message"] and current["bot_response"]:
        # Check if this turn is already in history
        last_turn = current["conversation_history"][-1] if current["conversation_history"] else {}
        if (last_turn.get("user") != current["user_message"] or
            last_turn.get("bot") != current["bot_response"]):
            new_state["conversation_history"].append({
                "user": current["user_message"],
                "bot": current["bot_response"],
                "timestamp": datetime.now().isoformat()
            })

    # Set current messages
    new_state["user_message"] = user_msg
    new_state["bot_response"] = bot_msg

    # Add current turn to history
    new_state["conversation_history"].append({
        "user": user_msg,
        "bot": bot_msg,
        "timestamp": datetime.now().isoformat()
    })

    return new_state


def set_missing_fields(current: TravelState, missing: List[str]) -> TravelState:
    """Set list of missing required fields"""
    new_state = copy.deepcopy(current)
    new_state["missing_fields"] = missing
    return new_state


def set_search_results(current: TravelState, results: Dict[str, Any], cached: bool = False) -> TravelState:
    """Set search results and cache status"""
    new_state = copy.deepcopy(current)
    new_state["search_results"] = results
    new_state["search_cached"] = cached
    return new_state


# Helper functions for state analysis
def get_required_fields() -> List[str]:
    """Get list of required fields for API call"""
    return ["origin", "destination", "departure_date"]


def has_required_fields(state: TravelState) -> bool:
    """Check if all required fields are present"""
    required = get_required_fields()
    return all(state.get(field) is not None for field in required)


def has_trip_type_decision(state: TravelState) -> bool:
    """Check if trip type has been decided"""
    return state["trip_type"] in ["one_way", "round_trip"] and state["trip_type_confirmed"]


def is_complete_for_api(state: TravelState) -> bool:
    """Check if state is complete for API call"""
    if not has_required_fields(state):
        return False

    if not has_trip_type_decision(state):
        return False

    # If round trip, must have return date
    if state["trip_type"] == "round_trip" and not state.get("return_date"):
        return False

    # Must have valid passenger count
    if not state.get("passengers") or state["passengers"] < 1 or state["passengers"] > 9:
        return False

    return True


def get_completion_percentage(state: TravelState) -> float:
    """Calculate completion percentage for progress tracking"""
    total_required = 4  # origin, destination, departure_date, trip_type
    completed = 0

    if state.get("origin"):
        completed += 1
    if state.get("destination"):
        completed += 1
    if state.get("departure_date"):
        completed += 1
    if has_trip_type_decision(state):
        completed += 1

    return completed / total_required
"""
LangGraph State Machine Definition

Defines the core StateGraph with nodes and edges for systematic
travel information collection and validation.
"""

from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, END
from app.langgraph.state import TravelState, create_initial_state


# Placeholder node functions (will be implemented in subsequent steps)
def collect_info_node(state: TravelState) -> TravelState:
    """COLLECT_INFO node - extract and accumulate travel entities"""
    # Placeholder implementation - just increment clarification attempts to prevent infinite loop
    from app.langgraph.state import increment_clarification_attempts
    return increment_clarification_attempts(state)


def validate_complete_node(state: TravelState) -> TravelState:
    """VALIDATE_COMPLETE node - comprehensive validation gate"""
    # Placeholder implementation - set ready_for_api to False to route to clarification
    from app.langgraph.state import set_api_ready
    return set_api_ready(state, False)


def search_flights_node(state: TravelState) -> TravelState:
    """SEARCH_FLIGHTS node - execute Amadeus API call with validated parameters"""
    # Placeholder implementation - set empty search results to route to clarification
    from app.langgraph.state import set_search_results
    return set_search_results(state, {}, False)


def present_options_node(state: TravelState) -> TravelState:
    """PRESENT_OPTIONS node - format and return flight results (Phase 1 endpoint)"""
    # Placeholder implementation - just return state (this ends the flow)
    return state


def needs_clarification_node(state: TravelState) -> TravelState:
    """NEEDS_CLARIFICATION node - handle corrections, missing info, ambiguity"""
    # Placeholder implementation - increment attempts to eventually hit termination
    from app.langgraph.state import increment_clarification_attempts
    return increment_clarification_attempts(state)


# Routing functions
def should_validate(state: TravelState) -> Literal["validate_complete", "needs_clarification"]:
    """Route from collect_info based on extracted information"""
    from app.langgraph.state import has_required_fields

    # If we have some information, attempt validation
    if (state.get("origin") or state.get("destination") or
            state.get("departure_date") or state["trip_type"] != "undecided"):
        return "validate_complete"

    # Need more clarification
    return "needs_clarification"


def should_search(state: TravelState) -> Literal["search_flights", "needs_clarification"]:
    """Route from validate_complete based on validation results"""
    # Only proceed to search if validation passed
    if state.get("ready_for_api", False):
        return "search_flights"

    # Return to clarification if validation failed
    return "needs_clarification"


def should_present(state: TravelState) -> Literal["present_options", "needs_clarification"]:
    """Route from search_flights based on search results"""
    # If search was successful, present results
    if state.get("search_results") is not None:
        return "present_options"

    # If search failed, return to clarification
    return "needs_clarification"


def should_continue_clarification(state: TravelState) -> Literal["collect_info", END]:
    """Route from needs_clarification based on attempts and state"""
    # If too many clarification attempts, end conversation
    if state.get("clarification_attempts", 0) >= 3:
        return END

    # Continue collecting information
    return "collect_info"


def create_travel_graph() -> StateGraph:
    """Create the main travel assistant state graph"""

    # Initialize the StateGraph with TravelState schema
    workflow = StateGraph(TravelState)

    # Add nodes
    workflow.add_node("collect_info", collect_info_node)
    workflow.add_node("validate_complete", validate_complete_node)
    workflow.add_node("search_flights", search_flights_node)
    workflow.add_node("present_options", present_options_node)
    workflow.add_node("needs_clarification", needs_clarification_node)

    # Set entry point
    workflow.set_entry_point("collect_info")

    # Add conditional edges
    workflow.add_conditional_edges(
        "collect_info",
        should_validate,
        {
            "validate_complete": "validate_complete",
            "needs_clarification": "needs_clarification"
        }
    )

    workflow.add_conditional_edges(
        "validate_complete",
        should_search,
        {
            "search_flights": "search_flights",
            "needs_clarification": "needs_clarification"
        }
    )

    workflow.add_conditional_edges(
        "search_flights",
        should_present,
        {
            "present_options": "present_options",
            "needs_clarification": "needs_clarification"
        }
    )

    # Present options is the end of Phase 1
    workflow.add_edge("present_options", END)

    # Clarification can either continue or end
    workflow.add_conditional_edges(
        "needs_clarification",
        should_continue_clarification,
        {
            "collect_info": "collect_info",
            END: END
        }
    )

    return workflow


def compile_travel_graph() -> Any:
    """Compile the travel state graph for execution"""
    workflow = create_travel_graph()
    return workflow.compile()


# Helper function to start a new conversation
def start_conversation(user_message: str) -> Dict[str, Any]:
    """Start a new conversation with initial user message"""
    initial_state = create_initial_state()
    initial_state["user_message"] = user_message

    return initial_state
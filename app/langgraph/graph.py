"""
LangGraph State Machine Definition

Defines the core StateGraph with nodes and edges for systematic
travel information collection and validation.
"""

from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, END
from app.langgraph.state import TravelState, create_initial_state


# Import real node implementations
from app.langgraph.nodes.collect_info import CollectInfoNode
from app.langgraph.nodes.validate_complete import ValidateCompleteNode
from app.langgraph.nodes.search_flights import SearchFlightsNode
from app.langgraph.nodes.present_options import PresentOptionsNode


def collect_info_node(state: TravelState, llm=None) -> TravelState:
    """COLLECT_INFO node - extract and accumulate travel entities"""
    node = CollectInfoNode(llm)
    return node(state)


def validate_complete_node(state: TravelState) -> TravelState:
    """VALIDATE_COMPLETE node - comprehensive validation gate"""
    node = ValidateCompleteNode()
    return node(state)


def search_flights_node(state: TravelState, amadeus_client=None, cache_manager=None) -> TravelState:
    """SEARCH_FLIGHTS node - execute Amadeus API call with validated parameters"""
    if amadeus_client:
        node = SearchFlightsNode(amadeus_client, cache_manager)
        return node(state)
    else:
        # Fallback for testing - set empty search results to route to clarification
        from app.langgraph.state import set_search_results
        return set_search_results(state, {}, False)


def present_options_node(state: TravelState) -> TravelState:
    """PRESENT_OPTIONS node - format and return flight results (Phase 1 endpoint)"""
    node = PresentOptionsNode()
    return node(state)


def needs_clarification_node(state: TravelState) -> TravelState:
    """NEEDS_CLARIFICATION node - handle corrections, missing info, ambiguity"""
    # Placeholder implementation - increment attempts to eventually hit termination
    from app.langgraph.state import increment_clarification_attempts
    return increment_clarification_attempts(state)


# Routing functions
def should_validate(state: TravelState) -> Literal["validate_complete", "needs_clarification"]:
    """Route from collect_info based on extracted information"""
    from app.langgraph.state import has_required_fields

    # FIXED: Only validate when we actually have all required fields
    # This prevents premature validation with partial/corrupted data
    if has_required_fields(state):
        print(f"[DEBUG] All required fields present - routing to validation")
        return "validate_complete"

    # REMOVED: Premature validation logic that caused false errors
    # Old logic: if (state.get("origin") or state.get("destination") or state.get("departure_date")):
    #     return "validate_complete"

    # Continue collecting information when fields are missing
    print(f"[DEBUG] Missing required fields - staying in collect_info")
    return "needs_clarification"


def should_search(state: TravelState) -> Literal["search_flights", "needs_clarification"]:
    """Route from validate_complete based on validation results"""
    # CRITICAL: Only proceed to search if validation explicitly passed
    ready_for_api = state.get("ready_for_api", False)

    print(f"[DEBUG] Routing decision: ready_for_api={ready_for_api}")

    if ready_for_api:
        print("[DEBUG] VALIDATION GATE PASSED - Routing to search_flights")
        return "search_flights"

    # Return to clarification if validation failed
    print("[DEBUG] VALIDATION GATE BLOCKED - Routing to needs_clarification")
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


def create_travel_graph(llm=None, amadeus_client=None, cache_manager=None) -> StateGraph:
    """Create the main travel assistant state graph"""

    # Initialize the StateGraph with TravelState schema
    workflow = StateGraph(TravelState)

    # Create node functions with dependencies
    def collect_info_with_llm(state: TravelState) -> TravelState:
        return collect_info_node(state, llm)

    def search_flights_with_client(state: TravelState) -> TravelState:
        return search_flights_node(state, amadeus_client, cache_manager)

    # Add nodes
    workflow.add_node("collect_info", collect_info_with_llm)
    workflow.add_node("validate_complete", validate_complete_node)
    workflow.add_node("search_flights", search_flights_with_client)
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


def compile_travel_graph(llm=None, amadeus_client=None, cache_manager=None) -> Any:
    """Compile the travel state graph for execution"""
    workflow = create_travel_graph(llm, amadeus_client, cache_manager)
    return workflow.compile()


# Helper function to start a new conversation
def start_conversation(user_message: str) -> Dict[str, Any]:
    """Start a new conversation with initial user message"""
    initial_state = create_initial_state()
    initial_state["user_message"] = user_message

    return initial_state
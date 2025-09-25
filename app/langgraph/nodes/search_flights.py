"""
SEARCH_FLIGHTS Node for LangGraph Travel Assistant

Executes validated Amadeus API calls and transforms results for presentation.
Only operates on fully validated state with ready_for_api=True.
"""

from typing import Dict, Any, Optional

from app.langgraph.state import (
    TravelState,
    set_search_results,
    update_conversation,
    increment_clarification_attempts
)
from app.langgraph.tools.amadeus_search import AmadeusSearchTool, SearchResult
from app.amadeus.client import AmadeusClient
from app.cache.flight_cache import FlightCacheManager


class SearchFlightsNode:
    """SEARCH_FLIGHTS node implementation"""

    def __init__(self, amadeus_client: AmadeusClient, cache_manager: Optional[FlightCacheManager] = None):
        self.amadeus_client = amadeus_client
        self.cache_manager = cache_manager
        self.search_tool = AmadeusSearchTool(amadeus_client, cache_manager)

    def __call__(self, state: TravelState) -> TravelState:
        """Execute flight search with validated parameters"""
        print(f"[DEBUG] SEARCH_FLIGHTS node executing...")

        # CRITICAL: Double-check validation gate
        if not state.get("ready_for_api", False):
            print(f"[ERROR] CRITICAL: SEARCH_FLIGHTS called without ready_for_api=True")
            print(f"[ERROR] This should never happen - validation gate bypassed!")

            # Emergency fallback - treat as validation error
            error_response = "Internal error - please try your search again."
            return update_conversation(
                increment_clarification_attempts(state),
                state.get("user_message", ""),
                error_response
            )

        # Execute search
        search_result = self.search_tool.search(state)
        print(f"[DEBUG] Search result: success={search_result.success}, cached={search_result.cached}")

        # Update state based on search outcome
        if search_result.success:
            updated_state = self._handle_search_success(state, search_result)
        else:
            updated_state = self._handle_search_failure(state, search_result)

        return updated_state

    def _handle_search_success(self, state: TravelState, result: SearchResult) -> TravelState:
        """Handle successful search results"""
        print(f"[DEBUG] Processing successful search results...")

        # Update state with search results
        updated_state = set_search_results(state, result.results, result.cached)

        # Generate appropriate response
        if result.cached:
            response = self._generate_cached_response(state, result)
        else:
            response = self._generate_fresh_response(state, result)

        # Update conversation
        final_state = update_conversation(
            updated_state,
            state.get("user_message", ""),
            response
        )

        print(f"[DEBUG] Search success - results ready for presentation")
        return final_state

    def _handle_search_failure(self, state: TravelState, result: SearchResult) -> TravelState:
        """Handle search failures with graceful error messages"""
        print(f"[DEBUG] Handling search failure: {result.error}")

        # Generate user-friendly error response
        response = self._generate_error_response(result.error)

        # Update conversation with error
        final_state = update_conversation(
            state,
            state.get("user_message", ""),
            response
        )

        # Don't increment clarification attempts for API failures
        # This wasn't user error, it was system error
        print(f"[DEBUG] Search failed - returning error response")
        return final_state

    def _generate_cached_response(self, state: TravelState, result: SearchResult) -> str:
        """Generate response for cached results"""
        trip_summary = self._get_trip_summary(state)
        return f"Found flights {trip_summary} (from recent search). Let me show you the options..."

    def _generate_fresh_response(self, state: TravelState, result: SearchResult) -> str:
        """Generate response for fresh API results"""
        trip_summary = self._get_trip_summary(state)

        if result.search_duration_ms:
            if result.search_duration_ms < 1000:
                speed_note = "quickly"
            elif result.search_duration_ms < 3000:
                speed_note = "in a moment"
            else:
                speed_note = "after checking all options"

            return f"Found flights {trip_summary} {speed_note}! Here are your best options..."
        else:
            return f"Found flights {trip_summary}! Here are your options..."

    def _generate_error_response(self, error: Optional[str]) -> str:
        """Generate user-friendly error response"""
        if not error:
            return "I had trouble searching for flights. Please try again in a moment."

        error_lower = error.lower()

        # Handle specific error types with helpful messages
        if "timeout" in error_lower or "network" in error_lower:
            return "The flight search is taking longer than usual. Please try again in a moment."

        elif "rate limit" in error_lower or "too many" in error_lower:
            return "We're experiencing high demand. Please wait a moment and try again."

        elif "not found" in error_lower or "no flights" in error_lower:
            return "No flights found for your search. Try adjusting your dates or destinations."

        elif "invalid" in error_lower and ("airport" in error_lower or "code" in error_lower):
            return "I couldn't recognize one of the airports. Could you check your departure and arrival cities?"

        elif "date" in error_lower:
            return "There was an issue with your travel dates. Could you double-check them?"

        else:
            # Generic error for unknown issues
            return "I'm having trouble searching for flights right now. Please try again in a moment."

    def _get_trip_summary(self, state: TravelState) -> str:
        """Generate brief trip summary for responses"""
        origin = state.get("origin", "your departure city")
        destination = state.get("destination", "your destination")
        passengers = state.get("passengers", 1) or 1

        summary = f"from {origin} to {destination}"

        if passengers and passengers > 1:
            summary += f" for {passengers} passengers"

        trip_type = state.get("trip_type")
        if trip_type == "round_trip":
            summary += " (round-trip)"
        elif trip_type == "one_way":
            summary += " (one-way)"

        return summary


# Node function for LangGraph integration
def create_search_flights_node(amadeus_client: AmadeusClient,
                              cache_manager: Optional[FlightCacheManager] = None):
    """Create SEARCH_FLIGHTS node instance"""
    return SearchFlightsNode(amadeus_client, cache_manager)


# Direct callable for graph registration
def search_flights_node(state: TravelState, amadeus_client: AmadeusClient = None,
                       cache_manager: Optional[FlightCacheManager] = None) -> TravelState:
    """SEARCH_FLIGHTS node function for LangGraph StateGraph"""
    if not amadeus_client:
        # Fallback error if no client provided
        error_response = "Flight search unavailable. Please try again later."
        return update_conversation(
            state,
            state.get("user_message", ""),
            error_response
        )

    node = SearchFlightsNode(amadeus_client, cache_manager)
    return node(state)
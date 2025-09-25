"""
PRESENT_OPTIONS Node for LangGraph Travel Assistant

Formats flight search results naturally using the existing enhanced WhatsApp formatter
while preserving conversational state for future phases.
"""

from typing import Dict, Any, Optional

from app.langgraph.state import (
    TravelState,
    update_conversation
)
from app.formatters.enhanced_whatsapp import NaturalFormatter


class PresentOptionsNode:
    """PRESENT_OPTIONS node implementation - Phase 1 endpoint"""

    def __init__(self):
        self.formatter = NaturalFormatter()

    def __call__(self, state: TravelState) -> TravelState:
        """Format and present flight search results"""
        print(f"[DEBUG] PRESENT_OPTIONS node executing...")

        # Verify we have search results to present
        if not state.get("search_results"):
            print(f"[ERROR] PRESENT_OPTIONS called without search results")
            error_response = "Internal error - no results to display. Please try searching again."
            return update_conversation(
                state,
                state.get("user_message", ""),
                error_response
            )

        # Format results using existing natural formatter
        formatted_response = self._format_search_results(state)

        # Update conversation with formatted results
        final_state = update_conversation(
            state,
            state.get("user_message", ""),
            formatted_response
        )

        print(f"[DEBUG] Results presented - Phase 1 complete")
        return final_state

    def _format_search_results(self, state: TravelState) -> str:
        """Format search results using natural formatter"""
        search_results = state.get("search_results", {})
        search_cached = state.get("search_cached", False)

        # Transform Amadeus API results into formatter-compatible format
        formatted_results = self._transform_amadeus_results(search_results)

        if not formatted_results:
            return self._handle_empty_results(state)

        # Use existing natural formatter with cache indication
        response = self.formatter.format_results_conversational(
            formatted_results,
            from_cache=search_cached
        )

        # Add trip summary context for better UX
        trip_summary = self._get_trip_summary(state)
        if trip_summary:
            response = f"**{trip_summary}**\n\n{response}"

        return response

    def _transform_amadeus_results(self, amadeus_results: Dict[str, Any]) -> Dict[str, Any]:
        """Transform Amadeus API results into formatter-compatible format"""
        if not amadeus_results or not amadeus_results.get("data"):
            return {}

        flights = amadeus_results["data"]
        if not flights:
            return {}

        # Sort flights by price and duration for categorization
        sorted_by_price = sorted(flights, key=lambda f: float(f.get("price", {}).get("total", "999999")))
        sorted_by_duration = sorted(flights, key=lambda f: self._get_total_duration(f))

        result = {}

        # Get cheapest option
        if sorted_by_price:
            cheapest = sorted_by_price[0]
            cheapest_formatted = self._format_flight_for_display(cheapest)
            if cheapest_formatted:  # Only add if formatting succeeded
                result["cheapest"] = cheapest_formatted

        # Get fastest option (different from cheapest)
        if len(sorted_by_duration) > 0:
            fastest = sorted_by_duration[0]
            # Only show fastest if it's different from cheapest
            if len(flights) > 1 and fastest != cheapest:
                fastest_formatted = self._format_flight_for_display(fastest)
                if fastest_formatted:  # Only add if formatting succeeded
                    result["fastest"] = fastest_formatted

        # Calculate price difference if we have both options
        if "fastest" in result and "cheapest" in result:
            cheapest_price = float(result["cheapest"]["price"])
            fastest_price = float(result["fastest"]["price"])
            if fastest_price > cheapest_price:
                result["price_difference"] = fastest_price - cheapest_price

                # Calculate time saved
                cheapest_duration = result["cheapest"]["duration_minutes"]
                fastest_duration = result["fastest"]["duration_minutes"]
                time_saved_mins = cheapest_duration - fastest_duration
                if time_saved_mins > 60:
                    result["time_saved"] = f"{time_saved_mins // 60}h {time_saved_mins % 60}m"
                else:
                    result["time_saved"] = f"{time_saved_mins}m"

        return result

    def _format_flight_for_display(self, flight: Dict[str, Any]) -> Dict[str, Any]:
        """Format single flight for display"""
        price_info = flight.get("price", {})
        itineraries = flight.get("itineraries", [])

        if not itineraries:
            return {}

        first_itinerary = itineraries[0]
        segments = first_itinerary.get("segments", [])

        if not segments:
            return {}

        first_segment = segments[0]
        last_segment = segments[-1]

        # Build route
        origin = first_segment.get("departure", {}).get("iataCode", "?")
        destination = last_segment.get("arrival", {}).get("iataCode", "?")
        route = f"{origin} → {destination}"

        # Get carrier name
        carrier_code = first_segment.get("carrierCode", "")
        flight_number = first_segment.get("number", "")
        carrier = f"{carrier_code} {flight_number}" if carrier_code else "Airline"

        # Calculate total duration
        duration_minutes = self._get_total_duration(flight)

        # Count stops
        stops = len(segments) - 1

        # Handle missing price gracefully
        try:
            price = float(price_info.get("total", "0"))
        except (ValueError, TypeError):
            price = 0.0

        return {
            "carrier": carrier,
            "route": route,
            "duration_minutes": duration_minutes,
            "stops": stops,
            "price": price,
            "currency": price_info.get("currency", "USD")
        }

    def _get_total_duration(self, flight: Dict[str, Any]) -> int:
        """Calculate total flight duration in minutes"""
        itineraries = flight.get("itineraries", [])
        if not itineraries:
            return 999999  # Large number for sorting

        # Parse duration from first itinerary (format: PT10H30M)
        duration_str = itineraries[0].get("duration", "PT0M")

        try:
            # Remove PT prefix and parse
            if not duration_str.startswith('PT'):
                return 999999  # Invalid format

            duration_str = duration_str[2:]  # Remove 'PT'
            hours = 0
            minutes = 0

            if 'H' in duration_str:
                hours_str = duration_str.split('H')[0]
                hours = int(hours_str)
                duration_str = duration_str.split('H')[1]

            if 'M' in duration_str:
                minutes_str = duration_str.split('M')[0]
                if minutes_str:  # Check for empty string
                    minutes = int(minutes_str)

            return hours * 60 + minutes
        except (ValueError, IndexError):
            return 999999  # Large number for sorting

    def _handle_empty_results(self, state: TravelState) -> str:
        """Handle cases where no flights were found"""
        trip_summary = self._get_trip_summary(state)

        base_message = "I couldn't find any flights for your search."

        if trip_summary:
            base_message = f"I couldn't find any flights {trip_summary.lower()}."

        suggestions = [
            "• Try different dates (weekdays are often cheaper)",
            "• Check nearby airports",
            "• Consider flexible departure times"
        ]

        return f"{base_message}\n\n**Suggestions:**\n" + "\n".join(suggestions)

    def _get_trip_summary(self, state: TravelState) -> str:
        """Generate brief trip summary for display"""
        origin = state.get("origin", "")
        destination = state.get("destination", "")
        departure_date = state.get("departure_date", "")
        passengers = state.get("passengers", 1)
        trip_type = state.get("trip_type", "")

        if not origin or not destination:
            return ""

        summary = f"{origin} → {destination}"

        if departure_date:
            try:
                from datetime import datetime
                date_obj = datetime.fromisoformat(departure_date)
                summary += f" on {date_obj.strftime('%B %d')}"
            except:
                summary += f" on {departure_date}"

        if passengers and passengers > 1:
            summary += f" for {passengers} passengers"

        if trip_type == "round_trip":
            return_date = state.get("return_date")
            if return_date:
                try:
                    ret_date_obj = datetime.fromisoformat(return_date)
                    summary += f" (returning {ret_date_obj.strftime('%B %d')})"
                except:
                    summary += f" (round-trip)"
            else:
                summary += " (round-trip)"

        return summary


# Node function for LangGraph integration
def create_present_options_node():
    """Create PRESENT_OPTIONS node instance"""
    return PresentOptionsNode()


# Direct callable for graph registration
def present_options_node(state: TravelState) -> TravelState:
    """PRESENT_OPTIONS node function for LangGraph StateGraph"""
    node = PresentOptionsNode()
    return node(state)
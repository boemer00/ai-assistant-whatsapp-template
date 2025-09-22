from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import random


class NaturalFormatter:
    def __init__(self):
        self.greetings = [
            "Hey there! 👋",
            "Hi! ✈️",
            "Hello!",
            "Hey!",
        ]
        self.confirmations = [
            "Perfect!",
            "Great!",
            "Awesome!",
            "Got it!",
            "Excellent!",
        ]
        self.thinking_phrases = [
            "Let me check that for you...",
            "Searching for the best options...",
            "Looking for great deals...",
            "Finding your flights...",
        ]

    def format_greeting(self, time_of_day: str = None) -> str:
        if not time_of_day:
            hour = datetime.now().hour
            if hour < 12:
                time_of_day = "morning"
            elif hour < 17:
                time_of_day = "afternoon"
            else:
                time_of_day = "evening"

        greeting = random.choice(self.greetings)
        return f"{greeting} Ready to find your perfect flight!"

    def format_confirmation_natural(self, info: Dict, suggestions: List[Dict] = None) -> str:
        parts = []

        # Start with a confirmation phrase
        parts.append(random.choice(self.confirmations))

        # Build natural sentence
        journey = []
        journey.append(f"flights from **{info['origin']}** to **{info['destination']}**")

        # Format date naturally
        dep_date = datetime.fromisoformat(info['departure_date'])
        days_until = (dep_date - datetime.now()).days

        if days_until == 0:
            journey.append("for **today**")
        elif days_until == 1:
            journey.append("for **tomorrow**")
        elif days_until < 7:
            journey.append(f"for **{dep_date.strftime('%A')}** ({dep_date.strftime('%b %d')})")
        else:
            journey.append(f"on **{dep_date.strftime('%B %d')}**")

        if info.get('return_date'):
            ret_date = datetime.fromisoformat(info['return_date'])
            trip_length = (ret_date - dep_date).days
            journey.append(f"returning after **{trip_length} days**")

        passengers = info.get('passengers', 1)
        if passengers > 1:
            journey.append(f"for **{passengers} travelers**")

        parts.append(f"So you need {' '.join(journey)}.")

        # Add smart suggestions if available
        if suggestions:
            parts.append("\n💡 **Quick tip:**")
            for suggestion in suggestions[:2]:
                parts.append(f"• {suggestion}")

        parts.append("\n**Ready to search?** (Reply 'yes' to continue)")

        return "\n".join(parts)

    def format_missing_info_conversational(self, missing: List[str], context: Dict) -> str:
        responses = {
            "origin": {
                "first": "Where are you starting your journey from?",
                "with_dest": f"Great! ✈️ to **{context.get('destination')}**. Where are you flying from?",
                "with_date": f"Nice! Planning to travel on **{context.get('departure_date')}**. What's your departure city?"
            },
            "destination": {
                "first": "Where would you like to go? 🌍",
                "with_origin": f"Got it! Flying from **{context.get('origin')}**. Where to?",
                "with_date": f"Traveling on **{context.get('departure_date')}**. What's your destination?"
            },
            "departure_date": {
                "first": "When would you like to travel?",
                "with_route": f"**{context.get('origin')} → {context.get('destination')}** - what date works for you?"
            }
        }

        field = missing[0]
        options = responses.get(field, {})

        # Choose contextual response
        if context.get('destination') and field == "origin":
            return options.get("with_dest", options.get("first"))
        elif context.get('origin') and field == "destination":
            return options.get("with_origin", options.get("first"))
        elif (context.get('origin') and context.get('destination') and field == "departure_date"):
            return options.get("with_route", options.get("first"))

        return options.get("first", "Could you tell me more about your trip?")

    def format_results_conversational(self, results: Dict, from_cache: bool = False) -> str:
        lines = []

        if from_cache:
            lines.append("✨ **Found these flights** (from recent searches):\n")
        else:
            lines.append("✨ **Here are your best options:**\n")

        # Format each flight option conversationally
        if "fastest" in results and results["fastest"]:
            flight = results["fastest"]
            lines.append("**⚡ Fastest Option**")
            lines.append(self._format_single_flight_natural(flight))
            lines.append("")

        if "cheapest" in results and results["cheapest"]:
            flight = results["cheapest"]
            lines.append("**💰 Best Value**")
            lines.append(self._format_single_flight_natural(flight))
            lines.append("")

        # Add helpful context
        if results.get("price_difference"):
            diff = results["price_difference"]
            lines.append(f"💡 The fastest option is ${diff:.0f} more but saves you {results.get('time_saved', 'time')}")

        # Add quick actions
        lines.append("\n**What would you like to do?**")
        lines.append("• Reply 'book cheapest' or 'book fastest'")
        lines.append("• Reply 'more options' to see alternatives")
        lines.append("• Reply 'different dates' to check other days")

        return "\n".join(lines)

    def _format_single_flight_natural(self, flight: Dict) -> str:
        parts = []

        # Airline and route
        parts.append(f"**{flight.get('carrier', 'Airline')}** • {flight.get('route', 'Route')}")

        # Duration in natural language
        duration_mins = flight.get('duration_minutes', 0)
        hours = duration_mins // 60
        mins = duration_mins % 60
        if hours > 0:
            duration_str = f"{hours}h {mins}m" if mins > 0 else f"{hours} hours"
        else:
            duration_str = f"{mins} minutes"
        parts.append(f"✈️ {duration_str} flight")

        # Stops
        stops = flight.get('stops', 0)
        if stops == 0:
            parts.append("• Direct flight")
        elif stops == 1:
            parts.append("• 1 stop")
        else:
            parts.append(f"• {stops} stops")

        # Price
        price = flight.get('price', 0)
        parts.append(f"💵 **${price:.2f}** per person")

        return "\n".join(parts)

    def format_searching_message(self) -> str:
        return random.choice(self.thinking_phrases) + " ⏳"

    def format_error_friendly(self, error_type: str = "general") -> str:
        errors = {
            "general": "Oops! Something went wrong. Could you try that again?",
            "no_results": "I couldn't find any flights for those dates. Try different dates?",
            "api_error": "Having trouble reaching the flight systems. Give me a moment and try again?",
            "invalid_input": "I didn't quite understand that. Could you rephrase?",
        }
        return errors.get(error_type, errors["general"])

    def format_correction_response(self, field: str, old_value: str, new_value: str) -> str:
        responses = {
            "destination": f"Changed destination from **{old_value}** to **{new_value}** ✓",
            "origin": f"Updated departure city to **{new_value}** ✓",
            "departure_date": f"Changed date to **{new_value}** ✓",
            "passengers": f"Updated to **{new_value}** passengers ✓",
        }
        return responses.get(field, f"Updated **{field}** ✓") + "\n\nShall I search now?"

    def format_smart_suggestions(self, context: Dict) -> List[str]:
        suggestions = []

        # Date-based suggestions
        if context.get("departure_date"):
            dep_date = datetime.fromisoformat(context["departure_date"])
            if dep_date.weekday() in [4, 5, 6]:  # Friday, Saturday, Sunday
                suggestions.append("Weekend flights tend to be pricier. Consider Thursday departure for better rates.")

        # Route-based suggestions
        route = f"{context.get('origin')}-{context.get('destination')}"
        if route in ["NYC-LON", "LON-NYC"]:
            suggestions.append("This route often has red-eye flights that are 30% cheaper.")

        # Passenger suggestions
        if context.get("passengers", 1) >= 4:
            suggestions.append("Group bookings sometimes have better rates when booked directly.")

        # Time of year suggestions
        month = datetime.now().month
        if month in [6, 7, 8, 12]:
            suggestions.append("Peak season pricing detected. Flexible dates could save you money.")

        return suggestions[:2]  # Return max 2 suggestions

    def format_quick_actions(self, session: Dict) -> str:
        if not session.get("history"):
            return ""

        # Suggest quick actions based on user history
        actions = []

        if session.get("preferences", {}).get("frequent_routes"):
            top_route = max(session["preferences"]["frequent_routes"].items(),
                          key=lambda x: x[1])[0]
            actions.append(f"'search {top_route}' for your usual route")

        if session.get("last_search"):
            actions.append("'repeat last' to search again")

        if actions:
            return "\n**Quick actions:** " + " | ".join(actions)

        return ""
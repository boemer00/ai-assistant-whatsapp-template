from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import json


class UserPreferenceManager:
    def __init__(self, redis_store):
        self.redis_store = redis_store
        self.prefix = "user_pref:"

    def get_user_profile(self, user_id: str) -> Dict:
        key = f"{self.prefix}{user_id}"
        profile = self.redis_store.client.get(key)
        if profile:
            return json.loads(profile)

        # Initialize new profile
        return self._create_default_profile(user_id)

    def _create_default_profile(self, user_id: str) -> Dict:
        return {
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
            "preferences": {
                "preferred_airlines": [],
                "avoided_airlines": [],
                "typical_class": "ECONOMY",
                "prefers_direct": False,
                "flexible_dates": False,
                "preferred_departure_times": [],  # morning, afternoon, evening, night
                "budget_conscious": None,  # Will be inferred from choices
            },
            "travel_patterns": {
                "frequent_routes": {},  # route: count
                "common_destinations": {},  # city: count
                "typical_trip_length": None,  # days
                "advance_booking_days": None,  # How far in advance they book
                "travel_frequency": None,  # trips per month
            },
            "history": {
                "searches": [],  # Last 20 searches
                "bookings": [],  # Confirmed bookings
                "quick_actions": [],  # Frequently used shortcuts
            },
            "insights": {
                "total_searches": 0,
                "total_bookings": 0,
                "average_price_searched": 0,
                "price_sensitivity": "unknown",  # low, medium, high
                "last_active": None,
            }
        }

    def update_from_search(self, user_id: str, search_params: Dict, selected_option: str = None):
        profile = self.get_user_profile(user_id)

        # Update search count
        profile["insights"]["total_searches"] += 1
        profile["insights"]["last_active"] = datetime.now().isoformat()

        # Track route frequency
        route = f"{search_params['origin']}-{search_params['destination']}"
        profile["travel_patterns"]["frequent_routes"][route] = \
            profile["travel_patterns"]["frequent_routes"].get(route, 0) + 1

        # Track destinations
        dest = search_params["destination"]
        profile["travel_patterns"]["common_destinations"][dest] = \
            profile["travel_patterns"]["common_destinations"].get(dest, 0) + 1

        # Add to search history (keep last 20)
        search_record = {
            "timestamp": datetime.now().isoformat(),
            "params": search_params,
            "selected": selected_option
        }
        profile["history"]["searches"].append(search_record)
        profile["history"]["searches"] = profile["history"]["searches"][-20:]

        # Infer preferences from selection
        if selected_option:
            self._infer_preferences(profile, selected_option)

        # Calculate patterns
        self._calculate_travel_patterns(profile)

        # Save updated profile
        self._save_profile(user_id, profile)
        return profile

    def _infer_preferences(self, profile: Dict, selection: str):
        # Infer budget consciousness
        if "cheapest" in selection.lower():
            profile["preferences"]["budget_conscious"] = True
            profile["insights"]["price_sensitivity"] = "high"
        elif "fastest" in selection.lower():
            profile["preferences"]["budget_conscious"] = False
            profile["insights"]["price_sensitivity"] = "low"

        # Could add more inference logic here

    def _calculate_travel_patterns(self, profile: Dict):
        searches = profile["history"]["searches"]
        if len(searches) < 3:
            return

        # Calculate average advance booking
        booking_advances = []
        for search in searches[-10:]:  # Last 10 searches
            if "departure_date" in search["params"]:
                dep_date = datetime.fromisoformat(search["params"]["departure_date"])
                search_date = datetime.fromisoformat(search["timestamp"])
                advance = (dep_date - search_date).days
                if advance > 0:
                    booking_advances.append(advance)

        if booking_advances:
            profile["travel_patterns"]["advance_booking_days"] = sum(booking_advances) // len(booking_advances)

        # Calculate typical trip length
        trip_lengths = []
        for search in searches[-10:]:
            params = search["params"]
            if params.get("departure_date") and params.get("return_date"):
                dep = datetime.fromisoformat(params["departure_date"])
                ret = datetime.fromisoformat(params["return_date"])
                trip_lengths.append((ret - dep).days)

        if trip_lengths:
            profile["travel_patterns"]["typical_trip_length"] = sum(trip_lengths) // len(trip_lengths)

    def _save_profile(self, user_id: str, profile: Dict):
        key = f"{self.prefix}{user_id}"
        self.redis_store.client.setex(
            key,
            86400 * 30,  # 30 days TTL
            json.dumps(profile)
        )

    def get_personalized_suggestions(self, user_id: str, current_search: Dict = None) -> List[str]:
        profile = self.get_user_profile(user_id)
        suggestions = []

        # Suggest based on frequent routes
        if profile["travel_patterns"]["frequent_routes"]:
            top_route = max(profile["travel_patterns"]["frequent_routes"].items(), key=lambda x: x[1])[0]
            origin, dest = top_route.split("-")
            suggestions.append(f"Search your usual {origin} to {dest} route")

        # Suggest based on price sensitivity
        if profile["insights"]["price_sensitivity"] == "high":
            suggestions.append("I'll prioritize the most affordable options for you")
        elif profile["insights"]["price_sensitivity"] == "low":
            suggestions.append("I'll focus on the fastest, most convenient flights")

        # Suggest based on booking patterns
        if profile["travel_patterns"]["advance_booking_days"]:
            days = profile["travel_patterns"]["advance_booking_days"]
            if days > 21:
                suggestions.append("You typically book well in advance - great for finding deals!")
            elif days < 7:
                suggestions.append("For last-minute bookings, I'll check flexible date options")

        # Context-aware suggestions
        if current_search:
            # Check if this is a frequent route
            route = f"{current_search.get('origin', '')}-{current_search.get('destination', '')}"
            if route in profile["travel_patterns"]["frequent_routes"]:
                count = profile["travel_patterns"]["frequent_routes"][route]
                suggestions.append(f"You've searched this route {count} times before")

        return suggestions[:3]  # Return top 3 suggestions

    def get_quick_actions(self, user_id: str) -> List[Dict]:
        profile = self.get_user_profile(user_id)
        actions = []

        # Most frequent route
        if profile["travel_patterns"]["frequent_routes"]:
            top_routes = sorted(profile["travel_patterns"]["frequent_routes"].items(),
                              key=lambda x: x[1], reverse=True)[:3]
            for route, count in top_routes:
                origin, dest = route.split("-")
                actions.append({
                    "type": "route",
                    "command": f"search {origin} to {dest}",
                    "description": f"Your frequent {route} route"
                })

        # Repeat last search
        if profile["history"]["searches"]:
            last = profile["history"]["searches"][-1]["params"]
            actions.append({
                "type": "repeat",
                "command": "repeat last",
                "description": f"Search {last['origin']}-{last['destination']} again"
            })

        # Flexible date search for budget conscious users
        if profile["preferences"]["budget_conscious"]:
            actions.append({
                "type": "flexible",
                "command": "flexible dates",
                "description": "Find cheapest dates for your route"
            })

        return actions[:5]

    def should_offer_help(self, user_id: str) -> bool:
        profile = self.get_user_profile(user_id)

        # New user
        if profile["insights"]["total_searches"] == 0:
            return True

        # Returning user after long absence
        if profile["insights"]["last_active"]:
            last_active = datetime.fromisoformat(profile["insights"]["last_active"])
            if (datetime.now() - last_active).days > 30:
                return True

        return False

    def format_welcome_back(self, user_id: str) -> str:
        profile = self.get_user_profile(user_id)

        if profile["insights"]["total_searches"] == 0:
            return "Welcome! I'm here to help you find the perfect flight. Just tell me where you want to go!"

        # Personalized welcome
        messages = []

        if profile["travel_patterns"]["frequent_routes"]:
            top_route = max(profile["travel_patterns"]["frequent_routes"].items(), key=lambda x: x[1])[0]
            messages.append(f"Welcome back! Looking for {top_route} flights again?")
        else:
            messages.append("Welcome back! Where are we flying today?")

        # Add quick actions
        quick_actions = self.get_quick_actions(user_id)
        if quick_actions:
            action_text = " | ".join([a["command"] for a in quick_actions[:2]])
            messages.append(f"Quick actions: {action_text}")

        return "\n".join(messages)
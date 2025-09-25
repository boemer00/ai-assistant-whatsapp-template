"""
LangGraph Integration Handler

Main handler that integrates the LangGraph travel assistant with the existing
WhatsApp infrastructure, preserving Redis sessions, middleware, and caching.
"""

from typing import Dict, Any, Optional
from langchain_openai import ChatOpenAI

from app.session.redis_store import RedisSessionStore
from app.amadeus.client import AmadeusClient
from app.cache.flight_cache import FlightCacheManager
from app.user.preferences import UserPreferenceManager
from app.langgraph.graph import compile_travel_graph, start_conversation
from app.langgraph.state import TravelState


class LangGraphHandler:
    """LangGraph integration handler for WhatsApp travel assistant"""

    def __init__(
        self,
        session_store: RedisSessionStore,
        llm: ChatOpenAI,
        amadeus_client: AmadeusClient,
        cache_manager: FlightCacheManager,
        user_preferences: UserPreferenceManager = None,
        iata_db = None
    ):
        self.session_store = session_store
        self.llm = llm
        self.amadeus_client = amadeus_client
        self.cache_manager = cache_manager
        self.user_preferences = user_preferences
        self.iata_db = iata_db

        # Compile the travel graph with dependencies
        self.travel_graph = compile_travel_graph(
            llm=self.llm,
            amadeus_client=self.amadeus_client,
            cache_manager=self.cache_manager
        )

        print("[INFO] LangGraph handler initialized with complete travel pipeline")

    def handle_message(self, user_id: str, message: str) -> str:
        """Handle incoming WhatsApp message using LangGraph pipeline"""
        print(f"[DEBUG] LangGraph handler processing message from {user_id}: '{message}'")

        try:
            # Get or create session for state persistence
            session_data = self.session_store.get(user_id) or {}

            # Check if we have an ongoing conversation state
            travel_state = self._get_or_create_travel_state(session_data, message)

            # Execute LangGraph pipeline
            final_state = self.travel_graph.invoke(travel_state)

            # Save updated state to session
            self._save_travel_state(user_id, session_data, final_state)

            # Return the bot response
            response = final_state.get("bot_response", "I'm having trouble processing that. Could you try again?")

            print(f"[DEBUG] LangGraph response: {response}")
            return response

        except Exception as e:
            print(f"[ERROR] LangGraph handler error: {type(e).__name__}: {str(e)}")
            import traceback
            print(f"[ERROR] Full traceback: {traceback.format_exc()}")

            # Graceful fallback
            return "I'm experiencing some technical difficulties. Please try your request again in a moment."

    def _get_or_create_travel_state(self, session_data: Dict[str, Any], message: str) -> TravelState:
        """Get existing travel state or create new one from session"""
        # Check if we have stored LangGraph state
        stored_state = session_data.get("langgraph_state")

        if stored_state:
            # Continue existing conversation
            print(f"[DEBUG] Continuing existing LangGraph conversation")
            # Update the current message
            stored_state["user_message"] = message
            return stored_state
        else:
            # Start new conversation
            print(f"[DEBUG] Starting new LangGraph conversation")
            return start_conversation(message)

    def _save_travel_state(self, user_id: str, session_data: Dict[str, Any], travel_state: TravelState):
        """Save travel state back to Redis session"""
        try:
            # Update session with LangGraph state
            session_data["langgraph_state"] = travel_state

            # Also preserve legacy session structure for compatibility
            session_data.update({
                "info": {
                    "origin": travel_state.get("origin"),
                    "destination": travel_state.get("destination"),
                    "departure_date": travel_state.get("departure_date"),
                    "return_date": travel_state.get("return_date"),
                    "passengers": travel_state.get("passengers"),
                    "trip_type": travel_state.get("trip_type"),
                },
                "last_message": travel_state.get("user_message"),
                "last_response": travel_state.get("bot_response"),
                "validation_complete": travel_state.get("ready_for_api", False),
                "clarification_attempts": travel_state.get("clarification_attempts", 0)
            })

            # Save to Redis
            self.session_store.set(user_id, session_data)

            print(f"[DEBUG] Saved LangGraph state for user {user_id}")

        except Exception as e:
            print(f"[ERROR] Failed to save travel state: {e}")

    def get_user_session_info(self, user_id: str) -> Dict[str, Any]:
        """Get user session information for debugging/admin purposes"""
        session_data = self.session_store.get(user_id) or {}
        travel_state = session_data.get("langgraph_state")

        if not travel_state:
            return {"status": "no_active_conversation", "session_exists": bool(session_data)}

        return {
            "status": "active_conversation",
            "ready_for_api": travel_state.get("ready_for_api", False),
            "origin": travel_state.get("origin"),
            "destination": travel_state.get("destination"),
            "departure_date": travel_state.get("departure_date"),
            "trip_type": travel_state.get("trip_type"),
            "trip_type_confirmed": travel_state.get("trip_type_confirmed", False),
            "passengers": travel_state.get("passengers"),
            "clarification_attempts": travel_state.get("clarification_attempts", 0),
            "has_search_results": travel_state.get("search_results") is not None,
            "conversation_turns": len(travel_state.get("conversation_history", []))
        }

    def reset_user_conversation(self, user_id: str) -> bool:
        """Reset user's conversation state (for admin/debugging)"""
        try:
            session_data = self.session_store.get(user_id) or {}

            # Clear LangGraph state but preserve user preferences
            if "langgraph_state" in session_data:
                del session_data["langgraph_state"]

            # Clear legacy info but keep user preferences
            session_data["info"] = {}
            session_data["last_message"] = ""
            session_data["last_response"] = ""
            session_data["validation_complete"] = False

            self.session_store.set(user_id, session_data)

            print(f"[DEBUG] Reset conversation for user {user_id}")
            return True

        except Exception as e:
            print(f"[ERROR] Failed to reset conversation: {e}")
            return False

    def get_conversation_metrics(self) -> Dict[str, Any]:
        """Get metrics about LangGraph conversations"""
        # This could be expanded to track conversation metrics
        return {
            "handler_type": "langgraph",
            "pipeline_nodes": ["collect_info", "validate_complete", "search_flights", "present_options"],
            "status": "active"
        }


def create_langgraph_handler(
    session_store: RedisSessionStore,
    llm: ChatOpenAI,
    amadeus_client: AmadeusClient,
    cache_manager: FlightCacheManager,
    user_preferences: UserPreferenceManager = None,
    iata_db = None
) -> LangGraphHandler:
    """Factory function to create LangGraph handler"""
    return LangGraphHandler(
        session_store=session_store,
        llm=llm,
        amadeus_client=amadeus_client,
        cache_manager=cache_manager,
        user_preferences=user_preferences,
        iata_db=iata_db
    )
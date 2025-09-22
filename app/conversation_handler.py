"""
Module for handling WhatsApp conversation flow for flight fare queries.

This module implements a simple state machine to manage multi-turn conversations,
extracting flight details progressively, maintaining session memory, confirming
information, and delivering flight options.
"""

import os
import re
from enum import Enum
from typing import Dict, Optional, Any
from dotenv import load_dotenv
from app.session.store import SessionStore
from app.parse.fast_intent import fast_parse
from app.llm.extract_intent import extract_intent, IntentSchema
from langchain_openai import ChatOpenAI
from app.amadeus.client import AmadeusClient
from app.formatters.whatsapp import format_reply, format_confirmation, format_missing_date, format_missing_passengers
from app.config import settings
from app.types import RankedResults, FlightOption

# Load environment variables
load_dotenv()

class ConversationState(Enum):
    """Enum representing the states of the conversation flow."""
    START = "start"
    COLLECT_ORIGIN = "collect_origin"
    COLLECT_DESTINATION = "collect_destination"
    COLLECT_DATES = "collect_dates"
    COLLECT_PREFERENCES = "collect_preferences"
    CONFIRM = "confirm"
    DELIVER = "deliver"


class ConversationHandler:
    """
    Handles the conversation flow for extracting flight information and delivering fares.

    This class manages a state machine to guide users through providing flight details
    in a natural, memory-enabled way, confirming info before fetching and presenting
    options.
    """

    def __init__(
        self,
        session_store: SessionStore,
        amadeus_client: AmadeusClient,
        intent_parser: Optional[Any] = None,
        formatter: Optional[Any] = None
    ) -> None:
        """
        Initialize the ConversationHandler with required dependencies.

        Args:
            session_store: Instance for managing user sessions.
            intent_parser: Optional instance for parsing user intents (uses fast_parse if None).
            amadeus_client: Instance for fetching flight data.
            formatter: Optional instance for formatting WhatsApp responses.
        """
        self.session_store = session_store
        self.intent_parser = intent_parser or fast_parse
        self.amadeus_client = amadeus_client
        self.formatter = formatter
        # Initialize LLM for advanced parsing if needed
        self.llm = ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL
        )

    def handle_message(self, user_id: str, message: str) -> str:
        """
        Process an incoming user message and generate a response based on current state.

        This method extracts information from the message, updates the session state,
        and returns a formatted WhatsApp response.

        Args:
            user_id: Unique identifier for the user.
            message: The user's input message.

        Returns:
            str: Formatted response for WhatsApp.
        """
        session = self.get_session(user_id)
        if not session:
            session = {"state": ConversationState.START.value, "info": {}}
        extracted = self._extract_entities(message)
        session["info"].update(extracted)
        next_state = self._transition_state(session, extracted)
        session["state"] = next_state.value
        self.session_store.set(user_id, session)
        self.session_store.touch(user_id)
        return self._generate_response(next_state, session)

    def get_session(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve the current session data for a user.

        Args:
            user_id: Unique identifier for the user.

        Returns:
            Dict[str, Any]: The session data.
        """
        return self.session_store.get(user_id)

    def reset_session(self, user_id: str) -> None:
        """
        Reset the session for a user.

        Args:
            user_id: Unique identifier for the user.
        """
        self.session_store.clear(user_id)

    def _extract_entities(self, message: str) -> Dict[str, Any]:
        """
        Extract key entities (e.g., origin, destination, dates) from the message.

        Args:
            message: The user's input message.

        Returns:
            Dict[str, Any]: Extracted entities.
        """
        # Try fast parsing first for efficiency
        intent = fast_parse(message)
        if intent:
            return {
                "origin": intent.origin,
                "destination": intent.destination,
                "departure_date": intent.departure_date,
                "return_date": intent.return_date,
                "passengers": intent.passengers
            }
        # Fallback to LLM for complex messages
        intent = extract_intent(self.llm, message)
        return {
            "origin": intent.origin,
            "destination": intent.destination,
            "departure_date": intent.departure_date,
            "return_date": intent.return_date,
            "passengers": intent.passengers or 1
        }

    def _transition_state(self, session: Dict[str, Any], extracted: Dict[str, Any]) -> ConversationState:
        """
        Determine the next state based on current session and extracted info.

        Args:
            session: Current session data.
            extracted: Extracted entities from the message.

        Returns:
            ConversationState: The next state.
        """
        current_state = ConversationState(session["state"])
        info = session["info"]

        if current_state == ConversationState.START:
            if info.get("origin"):
                return ConversationState.COLLECT_DESTINATION
            return ConversationState.COLLECT_ORIGIN

        if current_state == ConversationState.COLLECT_ORIGIN:
            if info.get("destination"):
                return ConversationState.COLLECT_DATES
            return ConversationState.COLLECT_DESTINATION

        if current_state == ConversationState.COLLECT_DESTINATION:
            if info.get("departure_date"):
                return ConversationState.COLLECT_PREFERENCES
            return ConversationState.COLLECT_DATES

        if current_state == ConversationState.COLLECT_DATES:
            if info.get("passengers", 1) > 1 or extracted.get("passengers", 1) > 1:
                return ConversationState.COLLECT_PREFERENCES
            return ConversationState.CONFIRM

        if current_state == ConversationState.COLLECT_PREFERENCES:
            return ConversationState.CONFIRM

        if current_state == ConversationState.CONFIRM:
            # Assume user confirms with "yes" or similar; for simplicity, always proceed
            return ConversationState.DELIVER

        return current_state  # Stay in current state if no progress

    def _generate_response(self, state: ConversationState, session: Dict[str, Any]) -> str:
        """
        Generate a natural response based on the current state.

        Args:
            state: Current conversation state.
            session: Current session data.

        Returns:
            str: The response string.
        """
        info = session.get("info", {})

        if state == ConversationState.START:
            return "Hi! I'm here to help find your perfect flight. Let's start with where you're flying from."

        if state == ConversationState.COLLECT_ORIGIN:
            return "Got it! What's your destination?"

        if state == ConversationState.COLLECT_DESTINATION:
            return "Great! When are you planning to fly?"

        if state == ConversationState.COLLECT_DATES:
            if not info.get("passengers"):
                return "How many passengers? (e.g., '2 adults')"
            return "Thanks! Just to confirm, you're looking for flights. Reply 'yes' to proceed."

        if state == ConversationState.COLLECT_PREFERENCES:
            return "Just to confirm, you're looking for flights. Reply 'yes' to proceed."

        if state == ConversationState.CONFIRM:
            # Use formatter for confirmation
            intent = IntentSchema(**info)
            return format_confirmation(intent, info.get("origin", ""), info.get("destination", ""))

        if state == ConversationState.DELIVER:
            # Use real Amadeus API
            try:
                data = self.amadeus_client.search_flights(
                    origin=info["origin"],
                    destination=info["destination"],
                    dep_date=info["departure_date"],
                    ret_date=info.get("return_date"),
                    adults=info.get("passengers", 1)
                )
                from app.amadeus.transform import from_amadeus
                from app.rank.selector import rank_top
                options = from_amadeus(data)
                ranked = rank_top(options)
                return format_reply(IntentSchema(**info), ranked)
            except Exception as e:
                return f"Sorry, I couldn't search flights at this time. Error: {str(e)}"

        return "I'm not sure how to help with that. Can you clarify?"


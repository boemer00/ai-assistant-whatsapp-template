"""
Conversation Manager Tool for LangGraph Travel Assistant

Generates context-aware follow-up questions and manages conversation flow
to systematically collect travel information while maintaining natural dialogue.
"""

from typing import Dict, List, Optional, Any, Literal
from pydantic import BaseModel
# from langchain_core.tools import BaseTool  # Simplified for now
import re
from datetime import datetime, timedelta

from app.langgraph.state import TravelState, get_required_fields, has_required_fields, has_trip_type_decision


class ConversationAction(BaseModel):
    """Action to take in conversation"""
    question: str
    question_type: Literal["missing_info", "clarification", "confirmation", "greeting"]
    priority: int  # Lower number = higher priority
    context_used: List[str]
    follow_up_suggestions: List[str] = []


class ConversationManagerTool:
    """Generate contextual follow-up questions"""

    def _run(self, state: TravelState, extraction_result: Optional[Dict] = None) -> ConversationAction:
        """Generate appropriate conversational response based on state"""

        # Handle greetings first
        if self._is_greeting(state["user_message"]):
            return self._generate_greeting_response()

        # Handle confirmations
        if self._is_confirmation(state["user_message"]):
            return self._generate_confirmation_response(state)

        # Check if we have extraction results to acknowledge
        if extraction_result and extraction_result.get("extracted_fields"):
            return self._generate_extraction_acknowledgment(state, extraction_result)

        # Check what's missing and generate appropriate question
        missing_fields = self._get_missing_critical_info(state)
        print(f"[DEBUG] Missing fields: {missing_fields}")
        print(f"[DEBUG] Current state: origin={state.get('origin')}, destination={state.get('destination')}, date={state.get('departure_date')}")

        if missing_fields:
            return self._generate_missing_info_question(state, missing_fields)

        # If we have all required fields, move to trip type confirmation
        if not has_trip_type_decision(state):
            return self._generate_trip_type_question(state)

        # If everything looks complete, generate confirmation
        return self._generate_final_confirmation(state)

    def _is_greeting(self, message: str) -> bool:
        """Check if message is a greeting"""
        greeting_patterns = [
            r'^(hi|hello|hey|good\s+(morning|afternoon|evening)|greetings?|howdy)(?:\s|!|\.)?$',
            r'^(what\'s up|sup|yo)(?:\s|!|\.)?$'
        ]
        message_lower = message.lower().strip()
        return any(re.match(pattern, message_lower, re.I) for pattern in greeting_patterns)

    def _is_confirmation(self, message: str) -> bool:
        """Check if message is a confirmation"""
        confirmation_patterns = [
            r'^(yes|yep|yeah|correct|right|perfect|exactly|that\'s right|looks good|confirm)(?:\s|!|\.)?$',
            r'^(ok|okay|alright|sure|sounds good)(?:\s|!|\.)?$'
        ]
        message_lower = message.lower().strip()
        return any(re.match(pattern, message_lower, re.I) for pattern in confirmation_patterns)

    def _generate_greeting_response(self) -> ConversationAction:
        """Generate friendly greeting response"""
        hour = datetime.now().hour
        if hour < 12:
            time_greeting = "Good morning!"
        elif hour < 17:
            time_greeting = "Good afternoon!"
        else:
            time_greeting = "Good evening!"

        question = f"{time_greeting} ✈️ I'm here to help you find the perfect flight. Where would you like to go today?"

        return ConversationAction(
            question=question,
            question_type="greeting",
            priority=1,
            context_used=["time_of_day"],
            follow_up_suggestions=[
                "Try: 'NYC to London tomorrow'",
                "Try: 'I need a flight to Paris'",
                "Try: '2 tickets to Tokyo next week'"
            ]
        )

    def _generate_confirmation_response(self, state: TravelState) -> ConversationAction:
        """Generate response to user confirmation"""
        if has_required_fields(state) and has_trip_type_decision(state):
            question = "Perfect! Let me search for flights now..."
            return ConversationAction(
                question=question,
                question_type="confirmation",
                priority=1,
                context_used=["complete_info"]
            )
        else:
            # Still missing info, continue collection
            missing = self._get_missing_critical_info(state)
            return self._generate_missing_info_question(state, missing)

    def _generate_extraction_acknowledgment(self, state: TravelState, extraction_result: Dict) -> ConversationAction:
        """Acknowledge extracted information and ask for what's missing"""
        extracted = extraction_result.get("extracted_fields", {})
        context_parts = []

        # Build acknowledgment based on what was extracted
        ack_parts = []
        if extracted.get("origin"):
            ack_parts.append(f"from {extracted['origin']}")
            context_parts.append("origin")
        if extracted.get("destination"):
            ack_parts.append(f"to {extracted['destination']}")
            context_parts.append("destination")
        if extracted.get("departure_date"):
            ack_parts.append(f"on {extracted['departure_date']}")
            context_parts.append("departure_date")
        if extracted.get("passengers") and extracted["passengers"] > 1:
            ack_parts.append(f"for {extracted['passengers']} people")
            context_parts.append("passengers")

        # Check what's still missing
        missing = self._get_missing_critical_info(state)

        if ack_parts and missing:
            # Acknowledge what we got and ask for what's missing
            acknowledgment = f"Great! Flying {' '.join(ack_parts)}. "
            follow_up = self._generate_missing_info_question_text(state, missing)
            question = acknowledgment + follow_up

            return ConversationAction(
                question=question,
                question_type="missing_info",
                priority=2,
                context_used=context_parts
            )

        elif ack_parts and not missing:
            # We have everything, move to trip type or confirmation
            if not has_trip_type_decision(state):
                question = f"Perfect! Flying {' '.join(ack_parts)}. Is this a one-way trip, or do you need a return flight?"
                return ConversationAction(
                    question=question,
                    question_type="clarification",
                    priority=2,
                    context_used=context_parts
                )
            else:
                return self._generate_final_confirmation(state)

        else:
            # No clear extraction, ask for missing info
            return self._generate_missing_info_question(state, missing or get_required_fields())

    def _get_missing_critical_info(self, state: TravelState) -> List[str]:
        """Get list of missing critical information"""
        missing = []

        if not state.get("origin"):
            missing.append("origin")
        if not state.get("destination"):
            missing.append("destination")
        if not state.get("departure_date"):
            missing.append("departure_date")

        # Check passenger count (default to 1 if not specified)
        if not state.get("passengers"):
            # Don't consider this critical missing - we can default to 1
            pass

        return missing

    def _generate_missing_info_question(self, state: TravelState, missing_fields: List[str]) -> ConversationAction:
        """Generate question for missing information"""
        question = self._generate_missing_info_question_text(state, missing_fields)

        return ConversationAction(
            question=question,
            question_type="missing_info",
            priority=3,
            context_used=[f for f in ["origin", "destination", "departure_date"] if state.get(f)],
            follow_up_suggestions=self._get_follow_up_suggestions(missing_fields[0] if missing_fields else "")
        )

    def _generate_missing_info_question_text(self, state: TravelState, missing_fields: List[str]) -> str:
        """Generate the actual question text for missing information"""
        if not missing_fields:
            return "I have all the information I need!"

        # Context-aware questions based on what we already know
        origin = state.get("origin")
        destination = state.get("destination")
        departure_date = state.get("departure_date")

        primary_missing = missing_fields[0]
        print(f"[DEBUG] Question selection: primary_missing='{primary_missing}', origin='{origin}', destination='{destination}', date='{departure_date}'")

        if primary_missing == "origin" and destination:
            question = f"Perfect! You want to go to {destination}. Where are you flying from?"
            print(f"[DEBUG] Selected question type: origin with destination context")
            return question

        elif primary_missing == "destination" and origin:
            question = f"Great! Flying from {origin}. Where would you like to go?"
            print(f"[DEBUG] Selected question type: destination with origin context")
            return question

        elif primary_missing == "departure_date" and origin and destination:
            question = f"Excellent! {origin} to {destination}. What date would you like to travel?"
            print(f"[DEBUG] Selected question type: date with full context")
            return question

        elif primary_missing == "departure_date":
            question = "When would you like to travel?"
            print(f"[DEBUG] Selected question type: date only - THIS IS WRONG FOR GREETING!")
            return question

        # Fallback questions
        question_map = {
            "origin": "Where are you flying from?",
            "destination": "Where would you like to go?",
            "departure_date": "When would you like to depart?"
        }

        fallback_question = question_map.get(primary_missing, "Could you provide more details about your trip?")
        print(f"[DEBUG] Selected fallback question for '{primary_missing}': {fallback_question}")
        return fallback_question

    def _generate_trip_type_question(self, state: TravelState) -> ConversationAction:
        """Generate question about trip type (one-way vs round-trip)"""
        origin = state.get("origin", "your departure city")
        destination = state.get("destination", "your destination")

        question = f"Is this a one-way trip to {destination}, or do you need a return flight back to {origin}?"

        return ConversationAction(
            question=question,
            question_type="clarification",
            priority=2,
            context_used=["origin", "destination", "departure_date"],
            follow_up_suggestions=[
                "Say: 'One-way please'",
                "Say: 'Return on [date]'",
                "Say: 'Round trip, returning next week'"
            ]
        )

    def _generate_final_confirmation(self, state: TravelState) -> ConversationAction:
        """Generate final confirmation before search"""
        parts = []

        if state.get("origin") and state.get("destination"):
            parts.append(f"from {state['origin']} to {state['destination']}")

        if state.get("departure_date"):
            parts.append(f"departing {state['departure_date']}")

        if state.get("return_date"):
            parts.append(f"returning {state['return_date']}")
        elif state.get("trip_type") == "one_way":
            parts.append("(one-way)")

        passengers = state.get("passengers", 1)
        if passengers > 1:
            parts.append(f"for {passengers} passengers")

        if parts:
            trip_summary = " ".join(parts)
            question = f"Perfect! Let me search for flights {trip_summary}. Shall I proceed?"
        else:
            question = "Ready to search for your flights?"

        return ConversationAction(
            question=question,
            question_type="confirmation",
            priority=1,
            context_used=list(state.keys()),
            follow_up_suggestions=["Say: 'Yes, search now'", "Say: 'Actually, change [detail]'"]
        )

    def _get_follow_up_suggestions(self, field: str) -> List[str]:
        """Get helpful follow-up suggestions for specific fields"""
        suggestions = {
            "origin": [
                "Try: 'NYC' or 'New York'",
                "Try: 'LAX' or 'Los Angeles'",
                "Try: 'LHR' or 'London'"
            ],
            "destination": [
                "Try: 'Paris' or 'CDG'",
                "Try: 'Tokyo' or 'NRT'",
                "Try: 'London' or 'LHR'"
            ],
            "departure_date": [
                "Try: 'tomorrow' or 'next Friday'",
                "Try: 'December 15' or '2025-01-15'",
                "Try: 'next week'"
            ]
        }
        return suggestions.get(field, [])


# Helper function to create conversation manager
def create_conversation_manager() -> ConversationManagerTool:
    """Create conversation manager tool"""
    return ConversationManagerTool()
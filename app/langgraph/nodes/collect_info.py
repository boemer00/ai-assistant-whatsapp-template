"""
COLLECT_INFO Node for LangGraph Travel Assistant

Orchestrates information extraction and conversation management to systematically
gather travel requirements through natural dialogue.
"""

from typing import Dict, Any, Optional
from langchain_openai import ChatOpenAI

from app.langgraph.state import (
    TravelState,
    add_extracted_info,
    add_field_confidence,
    set_trip_type,
    update_conversation,
    increment_clarification_attempts,
    set_missing_fields
)
from app.langgraph.tools.extractor import create_extraction_tool, ExtractionResult
from app.langgraph.tools.conversation_manager import create_conversation_manager, ConversationAction


class CollectInfoNode:
    """COLLECT_INFO node implementation"""

    def __init__(self, llm: Optional[ChatOpenAI] = None):
        self.llm = llm
        self.extractor = create_extraction_tool(llm)
        self.conversation_manager = create_conversation_manager()

    def __call__(self, state: TravelState) -> TravelState:
        """Process user message and collect travel information"""
        print(f"[DEBUG] COLLECT_INFO node processing: '{state['user_message']}'")

        # Extract information from user message
        extraction_result = self._extract_information(state)
        print(f"[DEBUG] Extraction result: {extraction_result.extraction_method} - {extraction_result.extracted_fields}")

        # Update state with extracted information
        updated_state = self._update_state_with_extraction(state, extraction_result)

        # Generate conversational response
        conversation_action = self._generate_response(updated_state, extraction_result)
        print(f"[DEBUG] Generated response: {conversation_action.question_type} - {conversation_action.question}")

        # Update conversation history
        final_state = update_conversation(
            updated_state,
            state["user_message"],
            conversation_action.question
        )

        # Update missing fields for routing decisions
        missing_fields = self._identify_missing_fields(final_state)
        final_state = set_missing_fields(final_state, missing_fields)

        print(f"[DEBUG] Final state: origin={final_state.get('origin')}, dest={final_state.get('destination')}, date={final_state.get('departure_date')}")
        return final_state

    def _extract_information(self, state: TravelState) -> ExtractionResult:
        """Extract travel information from user message"""
        try:
            return self.extractor._run(state["user_message"], state)
        except Exception as e:
            print(f"[ERROR] Extraction failed: {e}")
            # Return empty result on error
            return ExtractionResult(
                extracted_fields={},
                field_confidence={},
                ambiguous_fields=[],
                suggested_clarifications=[],
                extraction_method="error"
            )

    def _update_state_with_extraction(self, state: TravelState, result: ExtractionResult) -> TravelState:
        """Update state with extraction results"""
        updated_state = state

        # Add extracted fields
        if result.extracted_fields:
            updated_state = add_extracted_info(updated_state, result.extracted_fields)

            # Add confidence scores
            for field, confidence in result.field_confidence.items():
                updated_state = add_field_confidence(updated_state, field, confidence)

            # Handle trip type updates
            if "trip_type" in result.extracted_fields:
                trip_type = result.extracted_fields["trip_type"]
                if trip_type in ["one_way", "round_trip"]:
                    updated_state = set_trip_type(updated_state, trip_type, True)

            # Infer trip type from return date
            elif "return_date" in result.extracted_fields:
                if result.extracted_fields["return_date"]:
                    updated_state = set_trip_type(updated_state, "round_trip", True)

            # Default passenger count if not specified
            if "passengers" not in updated_state or not updated_state["passengers"]:
                updated_state = add_extracted_info(updated_state, {"passengers": 1})

        return updated_state

    def _generate_response(self, state: TravelState, extraction_result: ExtractionResult) -> ConversationAction:
        """Generate appropriate conversational response"""
        try:
            # Convert extraction result to dict for conversation manager
            extraction_dict = {
                "extracted_fields": extraction_result.extracted_fields,
                "field_confidence": extraction_result.field_confidence,
                "extraction_method": extraction_result.extraction_method
            }

            return self.conversation_manager._run(state, extraction_dict)
        except Exception as e:
            print(f"[ERROR] Conversation generation failed: {e}")
            # Fallback response
            return ConversationAction(
                question="I'm sorry, could you tell me more about your travel plans?",
                question_type="missing_info",
                priority=10,
                context_used=[]
            )

    def _identify_missing_fields(self, state: TravelState) -> list[str]:
        """Identify what critical information is still missing"""
        missing = []

        if not state.get("origin"):
            missing.append("origin")
        if not state.get("destination"):
            missing.append("destination")
        if not state.get("departure_date"):
            missing.append("departure_date")

        return missing

    def _should_proceed_to_validation(self, state: TravelState) -> bool:
        """Check if we have enough information to proceed to validation"""
        from app.langgraph.state import has_required_fields
        return has_required_fields(state)


# Node function for LangGraph integration
def create_collect_info_node(llm: Optional[ChatOpenAI] = None):
    """Create COLLECT_INFO node instance"""
    node = CollectInfoNode(llm)
    return node


# Direct callable for graph registration
def collect_info_node(state: TravelState, llm: Optional[ChatOpenAI] = None) -> TravelState:
    """COLLECT_INFO node function for LangGraph StateGraph"""
    node = CollectInfoNode(llm)
    return node(state)
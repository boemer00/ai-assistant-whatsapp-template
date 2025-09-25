"""
Test suite for COLLECT_INFO node functionality

Tests information extraction, conversation management, and state updates
for the COLLECT_INFO node in various scenarios.
"""

import pytest
from unittest.mock import Mock, patch
from langchain_openai import ChatOpenAI

from app.langgraph.state import (
    create_initial_state,
    add_extracted_info,
    update_conversation
)
from app.langgraph.nodes.collect_info import CollectInfoNode, collect_info_node
from app.langgraph.tools.extractor import ExtractionResult
from app.langgraph.tools.conversation_manager import ConversationAction


class TestCollectInfoNode:
    """Test CollectInfoNode functionality"""

    def test_collect_info_node_creation(self):
        """Test creating COLLECT_INFO node"""
        node = CollectInfoNode()
        assert node is not None
        assert node.extractor is not None
        assert node.conversation_manager is not None

    def test_collect_info_node_with_llm(self):
        """Test creating COLLECT_INFO node with LLM"""
        mock_llm = Mock(spec=ChatOpenAI)
        node = CollectInfoNode(mock_llm)
        assert node.llm == mock_llm

    def test_greeting_handling(self):
        """Test handling of greeting messages"""
        node = CollectInfoNode()
        state = create_initial_state()
        state["user_message"] = "Hello"

        result = node(state)

        assert "Good" in result["bot_response"]  # Should contain greeting
        assert "✈️" in result["bot_response"]  # Should contain flight emoji
        assert len(result["conversation_history"]) == 1

    def test_structured_input_extraction(self):
        """Test extraction from structured input (fast parse)"""
        node = CollectInfoNode()
        state = create_initial_state()
        state["user_message"] = "NYC to London tomorrow"

        result = node(state)

        # Should extract information
        assert result["origin"] == "NYC"
        assert result["destination"] == "London"
        assert result["departure_date"] is not None
        assert result["bot_response"] != ""

    def test_partial_information_handling(self):
        """Test handling partial information and follow-up questions"""
        node = CollectInfoNode()
        state = create_initial_state()
        state["user_message"] = "I need a flight to Paris"

        result = node(state)

        # Should extract destination
        assert result["destination"] == "Paris"
        # Should ask for missing information
        assert "from" in result["bot_response"].lower() or "where" in result["bot_response"].lower()
        assert len(result["missing_fields"]) > 0

    def test_multi_turn_conversation(self):
        """Test multi-turn conversation building information"""
        node = CollectInfoNode()

        # First turn - destination only
        state1 = create_initial_state()
        state1["user_message"] = "I want to go to Tokyo"
        result1 = node(state1)

        assert result1["destination"] == "Tokyo"
        assert "origin" in result1["missing_fields"]

        # Second turn - add origin
        state2 = result1.copy()
        state2["user_message"] = "From New York"
        result2 = node(state2)

        assert result2["origin"] == "New York"
        assert result2["destination"] == "Tokyo"  # Should preserve previous info
        assert "departure_date" in result2["missing_fields"]

    def test_correction_handling(self):
        """Test handling corrections to previously extracted information"""
        node = CollectInfoNode()

        # Initial state with some information
        state = create_initial_state()
        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "Paris",
            "departure_date": "2025-01-15"
        })
        state["user_message"] = "Actually, make that London instead of Paris"

        result = node(state)

        # Should update destination
        assert result["destination"] == "London"
        assert result["origin"] == "NYC"  # Should preserve other info

    def test_passenger_count_handling(self):
        """Test extraction and handling of passenger counts"""
        node = CollectInfoNode()
        state = create_initial_state()
        state["user_message"] = "NYC to London tomorrow for 3 people"

        result = node(state)

        assert result["passengers"] == 3
        assert "3" in result["bot_response"] or "three" in result["bot_response"].lower()

    def test_return_date_handling(self):
        """Test handling return dates and trip type inference"""
        node = CollectInfoNode()
        state = create_initial_state()
        state["user_message"] = "NYC to London Jan 15, returning Jan 22"

        result = node(state)

        assert result["departure_date"] == "2025-01-15"
        assert result["return_date"] == "2025-01-22"
        assert result["trip_type"] == "round_trip"
        assert result["trip_type_confirmed"] is True

    def test_one_way_trip_confirmation(self):
        """Test one-way trip handling"""
        node = CollectInfoNode()
        state = create_initial_state()
        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "London",
            "departure_date": "2025-01-15"
        })
        state["user_message"] = "One-way please"

        result = node(state)

        assert result["trip_type"] == "one_way"
        assert result["trip_type_confirmed"] is True
        assert result["return_date"] is None

    def test_missing_fields_identification(self):
        """Test proper identification of missing fields"""
        node = CollectInfoNode()

        # Test with no information
        state1 = create_initial_state()
        state1["user_message"] = "I need help"
        result1 = node(state1)

        expected_missing = {"origin", "destination", "departure_date"}
        assert set(result1["missing_fields"]) == expected_missing

        # Test with partial information
        state2 = create_initial_state()
        state2 = add_extracted_info(state2, {"origin": "NYC"})
        state2["user_message"] = "From New York"
        result2 = node(state2)

        assert "destination" in result2["missing_fields"]
        assert "departure_date" in result2["missing_fields"]
        assert "origin" not in result2["missing_fields"]

    def test_error_handling(self):
        """Test error handling in extraction and conversation"""
        node = CollectInfoNode()

        # Mock extraction failure
        with patch.object(node.extractor, '_run', side_effect=Exception("Test error")):
            state = create_initial_state()
            state["user_message"] = "Test message"
            result = node(state)

            # Should handle error gracefully
            assert result["bot_response"] != ""
            assert "sorry" in result["bot_response"].lower() or "more" in result["bot_response"].lower()

    def test_conversation_history_preservation(self):
        """Test that conversation history is properly maintained"""
        node = CollectInfoNode()

        # First interaction
        state1 = create_initial_state()
        state1["user_message"] = "Hello"
        result1 = node(state1)

        assert result1["user_message"] == "Hello"
        assert len(result1["conversation_history"]) == 1

        # Second interaction - should preserve history
        state2 = result1.copy()
        state2["user_message"] = "NYC to London"
        result2 = node(state2)

        assert len(result2["conversation_history"]) == 2
        assert result2["conversation_history"][0]["user"] == "Hello"
        assert result2["conversation_history"][0]["bot"] == result1["bot_response"]

    def test_field_confidence_tracking(self):
        """Test that field confidence scores are tracked"""
        node = CollectInfoNode()
        state = create_initial_state()
        state["user_message"] = "NYC to LON 2025-01-15"  # Structured format

        result = node(state)

        assert "field_confidence" in result
        assert len(result["field_confidence"]) > 0
        # Fast parse should give high confidence
        for field, confidence in result["field_confidence"].items():
            assert 0.0 <= confidence <= 1.0


class TestIntegrationScenarios:
    """Test realistic conversation scenarios"""

    def test_complete_booking_flow(self):
        """Test complete information collection flow"""
        node = CollectInfoNode()

        # Start with greeting
        state = create_initial_state()
        state["user_message"] = "Hi there"
        result = node(state)
        assert "help" in result["bot_response"].lower()

        # Provide partial info
        state = result.copy()
        state["user_message"] = "I need to go to Paris"
        result = node(state)
        assert result["destination"] == "Paris"
        assert "from" in result["bot_response"].lower()

        # Add origin
        state = result.copy()
        state["user_message"] = "From New York"
        result = node(state)
        assert result["origin"] == "New York"
        assert "when" in result["bot_response"].lower()

        # Add date
        state = result.copy()
        state["user_message"] = "Next Friday"
        result = node(state)
        assert result["departure_date"] is not None
        assert ("one-way" in result["bot_response"].lower() or
                "return" in result["bot_response"].lower())

    def test_correction_scenario(self):
        """Test correction handling scenario"""
        node = CollectInfoNode()

        # Initial complete request
        state = create_initial_state()
        state["user_message"] = "NYC to Paris tomorrow, 2 people"
        result = node(state)

        assert result["destination"] == "Paris"
        assert result["passengers"] == 2

        # Correction
        state = result.copy()
        state["user_message"] = "Actually, make that London instead"
        result = node(state)

        assert result["destination"] == "London"  # Should be corrected
        assert result["passengers"] == 2  # Should preserve
        assert result["origin"] == "NYC"  # Should preserve

    def test_ambiguous_input_scenario(self):
        """Test handling ambiguous or unclear input"""
        node = CollectInfoNode()
        state = create_initial_state()
        state["user_message"] = "I want to travel next week"

        result = node(state)

        # Should ask for clarification
        assert result["bot_response"] != ""
        assert ("where" in result["bot_response"].lower() or
                "destination" in result["bot_response"].lower())


# Functional tests
def test_collect_info_node_function():
    """Test the standalone collect_info_node function"""
    state = create_initial_state()
    state["user_message"] = "NYC to London"

    result = collect_info_node(state)

    assert isinstance(result, dict)
    assert result["origin"] == "NYC"
    assert result["destination"] == "London"
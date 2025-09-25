"""
Test suite for LangGraph foundation components

Tests TravelState schema, reducers, and basic StateGraph functionality.
"""

import pytest
from typing import Dict, Any
from app.langgraph.state import (
    TravelState,
    create_initial_state,
    add_extracted_info,
    add_field_confidence,
    set_trip_type,
    increment_clarification_attempts,
    set_validation_status,
    set_api_ready,
    update_conversation,
    set_missing_fields,
    set_search_results,
    get_required_fields,
    has_required_fields,
    has_trip_type_decision,
    is_complete_for_api,
    get_completion_percentage
)
from app.langgraph.graph import (
    create_travel_graph,
    compile_travel_graph,
    start_conversation
)


class TestTravelState:
    """Test TravelState schema and creation"""

    def test_create_initial_state(self):
        """Test initial state creation"""
        state = create_initial_state()

        # Check core fields are None
        assert state["origin"] is None
        assert state["destination"] is None
        assert state["departure_date"] is None
        assert state["return_date"] is None
        assert state["passengers"] is None

        # Check trip type is undecided
        assert state["trip_type"] == "undecided"
        assert state["trip_type_confirmed"] is False

        # Check validation defaults
        assert state["required_fields_complete"] is False
        assert state["field_confidence"] == {}
        assert state["validation_errors"] == []
        assert state["ready_for_api"] is False

        # Check conversation defaults
        assert state["conversation_history"] == []
        assert state["missing_fields"] == []
        assert state["clarification_attempts"] == 0
        assert state["user_message"] == ""
        assert state["bot_response"] == ""

    def test_state_immutability(self):
        """Test that state updates are immutable"""
        initial = create_initial_state()
        updated = add_extracted_info(initial, {"origin": "NYC"})

        # Original state should be unchanged
        assert initial["origin"] is None
        # Updated state should have new value
        assert updated["origin"] == "NYC"


class TestStateReducers:
    """Test state reducer functions"""

    def test_add_extracted_info(self):
        """Test adding extracted information"""
        state = create_initial_state()
        update = {
            "origin": "NYC",
            "destination": "LON",
            "passengers": 2
        }

        new_state = add_extracted_info(state, update)

        assert new_state["origin"] == "NYC"
        assert new_state["destination"] == "LON"
        assert new_state["passengers"] == 2
        # Other fields unchanged
        assert new_state["departure_date"] is None

    def test_add_extracted_info_ignores_none(self):
        """Test that None values are ignored in updates"""
        state = create_initial_state()
        update = {
            "origin": "NYC",
            "destination": None,  # Should be ignored
            "invalid_field": "test"  # Should be ignored
        }

        new_state = add_extracted_info(state, update)

        assert new_state["origin"] == "NYC"
        assert new_state["destination"] is None
        # Invalid field should not be added
        assert "invalid_field" not in new_state

    def test_add_field_confidence(self):
        """Test adding confidence scores"""
        state = create_initial_state()
        new_state = add_field_confidence(state, "origin", 0.95)

        assert new_state["field_confidence"]["origin"] == 0.95

    def test_set_trip_type(self):
        """Test setting trip type"""
        state = create_initial_state()

        # Test one-way
        new_state = set_trip_type(state, "one_way", True)
        assert new_state["trip_type"] == "one_way"
        assert new_state["trip_type_confirmed"] is True

        # Test round-trip
        new_state = set_trip_type(state, "round_trip", False)
        assert new_state["trip_type"] == "round_trip"
        assert new_state["trip_type_confirmed"] is False

    def test_increment_clarification_attempts(self):
        """Test incrementing clarification attempts"""
        state = create_initial_state()

        new_state = increment_clarification_attempts(state)
        assert new_state["clarification_attempts"] == 1

        new_state = increment_clarification_attempts(new_state)
        assert new_state["clarification_attempts"] == 2

    def test_set_validation_status(self):
        """Test setting validation status"""
        state = create_initial_state()
        errors = ["Missing origin", "Missing date"]

        new_state = set_validation_status(state, False, errors)
        assert new_state["required_fields_complete"] is False
        assert new_state["validation_errors"] == errors

        new_state = set_validation_status(state, True)
        assert new_state["required_fields_complete"] is True
        assert new_state["validation_errors"] == []

    def test_set_api_ready(self):
        """Test setting API readiness"""
        state = create_initial_state()

        new_state = set_api_ready(state, True)
        assert new_state["ready_for_api"] is True

        new_state = set_api_ready(new_state, False)
        assert new_state["ready_for_api"] is False

    def test_update_conversation(self):
        """Test updating conversation history"""
        state = create_initial_state()

        # First update
        state1 = update_conversation(state, "Hello", "Hi there!")
        assert state1["user_message"] == "Hello"
        assert state1["bot_response"] == "Hi there!"
        assert len(state1["conversation_history"]) == 1  # First interaction added to history

        # Second update should add previous to history and current
        state2 = update_conversation(state1, "NYC to London", "Great choice!")
        assert state2["user_message"] == "NYC to London"
        assert state2["bot_response"] == "Great choice!"
        assert len(state2["conversation_history"]) == 2
        assert state2["conversation_history"][0]["user"] == "Hello"
        assert state2["conversation_history"][0]["bot"] == "Hi there!"
        assert state2["conversation_history"][1]["user"] == "NYC to London"
        assert state2["conversation_history"][1]["bot"] == "Great choice!"

    def test_set_search_results(self):
        """Test setting search results"""
        state = create_initial_state()
        results = {"flights": ["flight1", "flight2"]}

        new_state = set_search_results(state, results, True)
        assert new_state["search_results"] == results
        assert new_state["search_cached"] is True


class TestStateAnalysis:
    """Test state analysis helper functions"""

    def test_get_required_fields(self):
        """Test getting required fields list"""
        required = get_required_fields()
        assert "origin" in required
        assert "destination" in required
        assert "departure_date" in required

    def test_has_required_fields(self):
        """Test checking required fields"""
        state = create_initial_state()
        assert has_required_fields(state) is False

        # Add some fields
        state = add_extracted_info(state, {"origin": "NYC"})
        assert has_required_fields(state) is False

        # Add all required fields
        state = add_extracted_info(state, {
            "destination": "LON",
            "departure_date": "2025-01-15"
        })
        assert has_required_fields(state) is True

    def test_has_trip_type_decision(self):
        """Test checking trip type decision"""
        state = create_initial_state()
        assert has_trip_type_decision(state) is False

        # Set trip type but not confirmed
        state = set_trip_type(state, "one_way", False)
        assert has_trip_type_decision(state) is False

        # Confirm trip type
        state = set_trip_type(state, "one_way", True)
        assert has_trip_type_decision(state) is True

    def test_is_complete_for_api(self):
        """Test checking if state is complete for API call"""
        state = create_initial_state()
        assert is_complete_for_api(state) is False

        # Add required fields
        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": "2025-01-15",
            "passengers": 2
        })
        assert is_complete_for_api(state) is False  # No trip type decision

        # Add trip type decision
        state = set_trip_type(state, "one_way", True)
        assert is_complete_for_api(state) is True

        # Test round trip without return date
        state = set_trip_type(state, "round_trip", True)
        assert is_complete_for_api(state) is False  # Missing return date

        # Add return date
        state = add_extracted_info(state, {"return_date": "2025-01-20"})
        assert is_complete_for_api(state) is True

    def test_get_completion_percentage(self):
        """Test completion percentage calculation"""
        state = create_initial_state()
        assert get_completion_percentage(state) == 0.0

        # Add origin (25%)
        state = add_extracted_info(state, {"origin": "NYC"})
        assert get_completion_percentage(state) == 0.25

        # Add destination (50%)
        state = add_extracted_info(state, {"destination": "LON"})
        assert get_completion_percentage(state) == 0.5

        # Add departure date (75%)
        state = add_extracted_info(state, {"departure_date": "2025-01-15"})
        assert get_completion_percentage(state) == 0.75

        # Add trip type decision (100%)
        state = set_trip_type(state, "one_way", True)
        assert get_completion_percentage(state) == 1.0


class TestStateGraph:
    """Test StateGraph creation and compilation"""

    def test_create_travel_graph(self):
        """Test creating travel graph"""
        graph = create_travel_graph()
        assert graph is not None

        # Check nodes are added
        nodes = list(graph.nodes.keys())
        expected_nodes = [
            "collect_info",
            "validate_complete",
            "search_flights",
            "present_options",
            "needs_clarification"
        ]
        for node in expected_nodes:
            assert node in nodes

    def test_compile_travel_graph(self):
        """Test compiling travel graph"""
        compiled_graph = compile_travel_graph()
        assert compiled_graph is not None

    def test_start_conversation(self):
        """Test starting a new conversation"""
        message = "I need a flight to London"
        state = start_conversation(message)

        assert isinstance(state, dict)
        assert state["user_message"] == message
        assert state["origin"] is None  # Not yet extracted
        assert state["trip_type"] == "undecided"


class TestGraphExecution:
    """Test basic graph execution (with placeholder nodes)"""

    def test_graph_execution_basic(self):
        """Test that graph can execute without errors"""
        compiled_graph = compile_travel_graph()
        initial_state = start_conversation("Test message")

        # This should run without errors (placeholder nodes do nothing)
        result = compiled_graph.invoke(initial_state)

        assert isinstance(result, dict)
        assert result["user_message"] == "Test message"
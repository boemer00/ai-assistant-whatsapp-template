"""
Test suite for VALIDATE_COMPLETE node functionality

Tests comprehensive validation logic, business rules, and API gate enforcement
to ensure no incomplete requests can reach the Amadeus API.
"""

import pytest
from datetime import datetime, timedelta

from app.langgraph.state import (
    create_initial_state,
    add_extracted_info,
    set_trip_type
)
from app.langgraph.nodes.validate_complete import ValidateCompleteNode, validate_complete_node
from app.langgraph.tools.validator import StateValidatorTool, ValidationResult


class TestValidationTool:
    """Test StateValidatorTool functionality"""

    def test_validator_creation(self):
        """Test creating validator tool"""
        validator = StateValidatorTool()
        assert validator is not None

    def test_empty_state_validation(self):
        """Test validation of empty state"""
        validator = StateValidatorTool()
        state = create_initial_state()

        result = validator.validate(state)

        assert not result.is_valid
        assert not result.ready_for_api
        assert "origin" in result.missing_required
        assert "destination" in result.missing_required
        assert "departure_date" in result.missing_required

    def test_partial_state_validation(self):
        """Test validation of partially filled state"""
        validator = StateValidatorTool()
        state = create_initial_state()
        state = add_extracted_info(state, {"origin": "NYC", "destination": "LON"})

        result = validator.validate(state)

        assert not result.is_valid
        assert not result.ready_for_api
        assert "departure_date" in result.missing_required
        assert "origin" not in result.missing_required
        assert "destination" not in result.missing_required

    def test_complete_valid_state(self):
        """Test validation of complete valid state"""
        validator = StateValidatorTool()
        state = create_initial_state()

        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": tomorrow,
            "passengers": 2
        })
        state = set_trip_type(state, "one_way", True)

        result = validator.validate(state)

        assert result.is_valid
        assert result.ready_for_api
        assert len(result.missing_required) == 0
        assert len(result.validation_errors) == 0

    def test_round_trip_validation(self):
        """Test validation of round trip requirements"""
        validator = StateValidatorTool()
        state = create_initial_state()

        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        next_week = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')

        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": tomorrow,
            "return_date": next_week,
            "passengers": 1
        })
        state = set_trip_type(state, "round_trip", True)

        result = validator.validate(state)

        assert result.is_valid
        assert result.ready_for_api

    def test_round_trip_missing_return_date(self):
        """Test validation fails for round trip without return date"""
        validator = StateValidatorTool()
        state = create_initial_state()

        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": tomorrow,
            "passengers": 1
        })
        state = set_trip_type(state, "round_trip", True)

        result = validator.validate(state)

        assert not result.is_valid
        assert not result.ready_for_api
        assert "Round trip must have return date" in result.validation_errors

    def test_past_date_validation(self):
        """Test validation fails for past dates"""
        validator = StateValidatorTool()
        state = create_initial_state()

        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": yesterday,
            "passengers": 1
        })
        state = set_trip_type(state, "one_way", True)

        result = validator.validate(state)

        assert not result.is_valid
        assert not result.ready_for_api
        assert any("past" in error.lower() for error in result.validation_errors)

    def test_same_origin_destination_validation(self):
        """Test validation fails for same origin and destination"""
        validator = StateValidatorTool()
        state = create_initial_state()

        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "NYC",
            "departure_date": tomorrow,
            "passengers": 1
        })
        state = set_trip_type(state, "one_way", True)

        result = validator.validate(state)

        assert not result.is_valid
        assert not result.ready_for_api
        assert any("same" in error.lower() for error in result.validation_errors)

    def test_invalid_passenger_count(self):
        """Test validation fails for invalid passenger counts"""
        validator = StateValidatorTool()

        # Test zero passengers
        state = create_initial_state()
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": tomorrow,
            "passengers": 0
        })
        state = set_trip_type(state, "one_way", True)

        result = validator.validate(state)
        assert not result.ready_for_api
        assert any("at least 1" in error for error in result.validation_errors)

        # Test too many passengers
        state = add_extracted_info(state, {"passengers": 15})
        result = validator.validate(state)
        assert not result.ready_for_api
        assert any("more than 9" in error for error in result.validation_errors)

    def test_trip_type_confirmation_required(self):
        """Test validation fails without trip type confirmation"""
        validator = StateValidatorTool()
        state = create_initial_state()

        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": tomorrow,
            "passengers": 1
        })
        # Don't confirm trip type
        state["trip_type"] = "one_way"
        state["trip_type_confirmed"] = False

        result = validator.validate(state)

        assert not result.ready_for_api
        assert any("not confirmed" in error for error in result.validation_errors)

    def test_return_date_logic(self):
        """Test return date must be after departure date"""
        validator = StateValidatorTool()
        state = create_initial_state()

        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        today = datetime.now().strftime('%Y-%m-%d')

        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": tomorrow,
            "return_date": today,  # Before departure
            "passengers": 1
        })
        state = set_trip_type(state, "round_trip", True)

        result = validator.validate(state)

        assert not result.ready_for_api
        assert any("after departure" in error.lower() for error in result.validation_errors)


class TestValidateCompleteNode:
    """Test ValidateCompleteNode functionality"""

    def test_node_creation(self):
        """Test creating VALIDATE_COMPLETE node"""
        node = ValidateCompleteNode()
        assert node is not None
        assert node.validator is not None

    def test_validation_success_flow(self):
        """Test successful validation flow"""
        node = ValidateCompleteNode()
        state = create_initial_state()

        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": tomorrow,
            "passengers": 2
        })
        state = set_trip_type(state, "one_way", True)
        state["user_message"] = "Test message"

        result = node(state)

        assert result["ready_for_api"] is True
        assert result["required_fields_complete"] is True
        assert len(result["validation_errors"]) == 0
        assert "searching" in result["bot_response"].lower()

    def test_validation_failure_flow(self):
        """Test validation failure flow"""
        node = ValidateCompleteNode()
        state = create_initial_state()

        # Missing required fields
        state = add_extracted_info(state, {"origin": "NYC"})
        state["user_message"] = "Test message"

        result = node(state)

        assert result["ready_for_api"] is False
        assert result["required_fields_complete"] is False
        assert len(result["missing_fields"]) > 0
        assert result["bot_response"] != ""

    def test_missing_origin_response(self):
        """Test response for missing origin"""
        node = ValidateCompleteNode()
        state = create_initial_state()

        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        state = add_extracted_info(state, {
            "destination": "LON",
            "departure_date": tomorrow
        })
        state["user_message"] = "Test"

        result = node(state)

        assert "flying from" in result["bot_response"].lower()

    def test_missing_destination_response(self):
        """Test response for missing destination"""
        node = ValidateCompleteNode()
        state = create_initial_state()

        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        state = add_extracted_info(state, {
            "origin": "NYC",
            "departure_date": tomorrow
        })
        state["user_message"] = "Test"

        result = node(state)

        assert ("going" in result["bot_response"].lower() or
                "where to" in result["bot_response"].lower() or
                "where would you like to go" in result["bot_response"].lower())

    def test_missing_date_response(self):
        """Test response for missing departure date"""
        node = ValidateCompleteNode()
        state = create_initial_state()

        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON"
        })
        state["user_message"] = "Test"

        result = node(state)

        assert ("date" in result["bot_response"].lower() or
                "when" in result["bot_response"].lower())

    def test_past_date_error_response(self):
        """Test response for past date error"""
        node = ValidateCompleteNode()
        state = create_initial_state()

        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": yesterday,
            "passengers": 1
        })
        state = set_trip_type(state, "one_way", True)
        state["user_message"] = "Test"

        result = node(state)

        assert result["ready_for_api"] is False
        assert "past" in result["bot_response"].lower()

    def test_same_location_error_response(self):
        """Test response for same origin/destination error"""
        node = ValidateCompleteNode()
        state = create_initial_state()

        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "NYC",
            "departure_date": tomorrow,
            "passengers": 1
        })
        state = set_trip_type(state, "one_way", True)
        state["user_message"] = "Test"

        result = node(state)

        assert result["ready_for_api"] is False
        assert "same" in result["bot_response"].lower()

    def test_trip_type_confirmation_response(self):
        """Test response for unconfirmed trip type"""
        node = ValidateCompleteNode()
        state = create_initial_state()

        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": tomorrow,
            "passengers": 1
        })
        # Don't confirm trip type
        state["trip_type"] = "one_way"
        state["trip_type_confirmed"] = False
        state["user_message"] = "Test"

        result = node(state)

        assert result["ready_for_api"] is False
        assert ("one-way" in result["bot_response"].lower() or
                "return" in result["bot_response"].lower())

    def test_conversation_history_update(self):
        """Test conversation history is updated"""
        node = ValidateCompleteNode()
        state = create_initial_state()

        state["user_message"] = "Test message"
        result = node(state)

        assert len(result["conversation_history"]) > 0
        assert result["user_message"] == "Test message"
        assert result["bot_response"] != ""


class TestValidationGateEnforcement:
    """Test the critical validation gate enforcement"""

    def test_api_gate_blocks_incomplete_state(self):
        """Test that ready_for_api is False for incomplete state"""
        node = ValidateCompleteNode()

        # Test various incomplete states
        incomplete_states = [
            # Missing origin
            {"destination": "LON", "departure_date": "2025-12-25", "passengers": 1},
            # Missing destination
            {"origin": "NYC", "departure_date": "2025-12-25", "passengers": 1},
            # Missing date
            {"origin": "NYC", "destination": "LON", "passengers": 1},
            # Unconfirmed trip type
            {"origin": "NYC", "destination": "LON", "departure_date": "2025-12-25", "passengers": 1},
        ]

        for incomplete_data in incomplete_states:
            state = create_initial_state()
            state = add_extracted_info(state, incomplete_data)
            state["user_message"] = "Test"

            result = node(state)

            assert result["ready_for_api"] is False, f"Should block incomplete state: {incomplete_data}"

    def test_api_gate_allows_complete_state(self):
        """Test that ready_for_api is True only for complete valid state"""
        node = ValidateCompleteNode()
        state = create_initial_state()

        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": tomorrow,
            "passengers": 2
        })
        state = set_trip_type(state, "one_way", True)
        state["user_message"] = "Test"

        result = node(state)

        assert result["ready_for_api"] is True
        assert result["required_fields_complete"] is True
        assert len(result["validation_errors"]) == 0


# Functional tests
def test_validate_complete_node_function():
    """Test the standalone validate_complete_node function"""
    state = create_initial_state()
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

    state = add_extracted_info(state, {
        "origin": "NYC",
        "destination": "LON",
        "departure_date": tomorrow,
        "passengers": 1
    })
    state = set_trip_type(state, "one_way", True)

    result = validate_complete_node(state)

    assert isinstance(result, dict)
    assert result["ready_for_api"] is True
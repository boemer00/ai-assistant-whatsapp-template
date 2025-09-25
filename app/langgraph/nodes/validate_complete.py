"""
VALIDATE_COMPLETE Node for LangGraph Travel Assistant

Critical validation gate that prevents incomplete API calls by ensuring all
required information is present and valid according to business rules.
"""

from typing import Dict, Any, Optional, List

from app.langgraph.state import (
    TravelState,
    set_validation_status,
    set_api_ready,
    update_conversation,
    set_missing_fields,
    increment_clarification_attempts
)
from app.langgraph.tools.validator import create_validator, ValidationResult


class ValidateCompleteNode:
    """VALIDATE_COMPLETE node implementation"""

    def __init__(self):
        self.validator = create_validator()

    def __call__(self, state: TravelState) -> TravelState:
        """Validate state completeness and readiness for API call"""
        print(f"[DEBUG] VALIDATE_COMPLETE node validating state...")

        # Perform comprehensive validation
        validation_result = self.validator.validate(state)
        print(f"[DEBUG] Validation result: valid={validation_result.is_valid}, ready={validation_result.ready_for_api}")
        print(f"[DEBUG] Missing: {validation_result.missing_required}")
        print(f"[DEBUG] Errors: {validation_result.validation_errors}")

        # Update state with validation results
        updated_state = self._update_state_with_validation(state, validation_result)

        # Generate appropriate response based on validation
        if validation_result.ready_for_api:
            response = self._generate_success_response(validation_result)
            print(f"[DEBUG] VALIDATION PASSED - Ready for API call")
        else:
            response = self._generate_failure_response(validation_result)
            print(f"[DEBUG] VALIDATION FAILED - Routing to clarification")

        # Update conversation with validation response
        final_state = update_conversation(
            updated_state,
            state.get("user_message", ""),
            response
        )

        return final_state

    def _update_state_with_validation(self, state: TravelState, result: ValidationResult) -> TravelState:
        """Update state with validation results"""
        updated_state = state

        # Set validation status
        updated_state = set_validation_status(
            updated_state,
            result.is_valid,
            result.validation_errors
        )

        # Set API readiness - this is the critical gate
        updated_state = set_api_ready(updated_state, result.ready_for_api)

        # Set missing fields for routing decisions
        updated_state = set_missing_fields(updated_state, result.missing_required)

        return updated_state

    def _generate_success_response(self, result: ValidationResult) -> str:
        """Generate response when validation passes"""
        return "Perfect! All information verified. Searching for flights now..."

    def _generate_failure_response(self, result: ValidationResult) -> str:
        """Generate response when validation fails"""
        if result.missing_required:
            return self._generate_missing_info_response(result.missing_required)
        elif result.validation_errors:
            return self._generate_error_response(result.validation_errors)
        else:
            return "I need to verify some details before searching for flights."

    def _generate_missing_info_response(self, missing_fields: List[str]) -> str:
        """Generate response for missing required information"""
        if len(missing_fields) == 1:
            field = missing_fields[0]
            field_prompts = {
                "origin": "Where are you flying from?",
                "destination": "Where would you like to go?",
                "departure_date": "What date would you like to travel?"
            }
            return field_prompts.get(field, f"I still need your {field}.")

        elif len(missing_fields) == 2:
            if "origin" in missing_fields and "destination" in missing_fields:
                return "I need to know where you're flying from and where you're going."
            elif "origin" in missing_fields and "departure_date" in missing_fields:
                return "I need to know where you're flying from and what date."
            elif "destination" in missing_fields and "departure_date" in missing_fields:
                return "I need to know where you're going and what date."

        # Multiple missing fields
        missing_text = ", ".join(missing_fields[:-1]) + f", and {missing_fields[-1]}"
        return f"I still need: {missing_text}."

    def _generate_error_response(self, errors: List[str]) -> str:
        """Generate response for validation errors"""
        if len(errors) == 1:
            error = errors[0]

            # Provide helpful responses for common errors
            if "past" in error.lower():
                return "The date you provided is in the past. Could you give me a future date?"
            elif "same" in error.lower():
                return "The origin and destination appear to be the same. Where would you like to fly to?"
            elif "return date" in error.lower():
                return "For a round trip, I need both departure and return dates."
            elif "trip type" in error.lower():
                return "Is this a one-way trip or do you need a return flight?"
            elif "passenger" in error.lower():
                return "How many passengers will be traveling?"
            else:
                return f"There's an issue: {error}. Could you clarify?"

        else:
            # Multiple errors - pick the most critical one
            critical_errors = [e for e in errors if any(keyword in e.lower()
                             for keyword in ["past", "trip type", "passenger"])]

            if critical_errors:
                return self._generate_error_response([critical_errors[0]])
            else:
                return f"I found several issues that need clarification: {'; '.join(errors[:2])}."

    def _should_increment_attempts(self, state: TravelState, result: ValidationResult) -> bool:
        """Determine if we should increment clarification attempts"""
        # Increment attempts if we have validation errors (not just missing info)
        return len(result.validation_errors) > 0


# Node function for LangGraph integration
def create_validate_complete_node():
    """Create VALIDATE_COMPLETE node instance"""
    return ValidateCompleteNode()


# Direct callable for graph registration
def validate_complete_node(state: TravelState) -> TravelState:
    """VALIDATE_COMPLETE node function for LangGraph StateGraph"""
    node = ValidateCompleteNode()
    return node(state)
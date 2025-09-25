"""
State Validation Tool for LangGraph Travel Assistant

Comprehensive validation to ensure all required information is present and valid
before allowing API calls. This is the critical gate that prevents incomplete requests.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel
from datetime import datetime, timedelta
import re

from app.langgraph.state import TravelState, get_required_fields, has_required_fields, has_trip_type_decision


class ValidationResult(BaseModel):
    """Result of state validation"""
    is_valid: bool
    missing_required: List[str]
    validation_errors: List[str]
    recommendations: List[str]
    ready_for_api: bool


class StateValidatorTool:
    """Comprehensive pre-API validation tool"""

    def __init__(self):
        self.airport_code_pattern = re.compile(r'^[A-Z]{3}$')
        self.date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')

    def validate(self, state: TravelState) -> ValidationResult:
        """Perform comprehensive validation of travel state"""
        missing_required = []
        validation_errors = []
        recommendations = []

        # 1. Check required fields presence
        missing_required.extend(self._validate_required_fields(state))

        # 2. Validate field formats and content
        validation_errors.extend(self._validate_field_formats(state))

        # 3. Validate business logic rules
        validation_errors.extend(self._validate_business_rules(state))

        # 4. Validate trip type consistency
        validation_errors.extend(self._validate_trip_type_logic(state))

        # 5. Validate passenger count
        validation_errors.extend(self._validate_passenger_count(state))

        # 6. Generate recommendations
        recommendations.extend(self._generate_recommendations(state))

        # Determine if ready for API
        is_valid = len(missing_required) == 0 and len(validation_errors) == 0
        ready_for_api = is_valid and has_trip_type_decision(state)

        return ValidationResult(
            is_valid=is_valid,
            missing_required=missing_required,
            validation_errors=validation_errors,
            recommendations=recommendations,
            ready_for_api=ready_for_api
        )

    def _validate_required_fields(self, state: TravelState) -> List[str]:
        """Validate presence of required fields"""
        missing = []

        if not state.get("origin"):
            missing.append("origin")
        if not state.get("destination"):
            missing.append("destination")
        if not state.get("departure_date"):
            missing.append("departure_date")

        return missing

    def _validate_field_formats(self, state: TravelState) -> List[str]:
        """Validate field formats and content"""
        errors = []

        # Validate origin format
        if state.get("origin"):
            origin = str(state["origin"]).strip()
            if len(origin) < 2:
                errors.append("Origin too short")
            elif len(origin) > 50:
                errors.append("Origin too long")

        # Validate destination format
        if state.get("destination"):
            destination = str(state["destination"]).strip()
            if len(destination) < 2:
                errors.append("Destination too short")
            elif len(destination) > 50:
                errors.append("Destination too long")

        # Validate departure date format
        if state.get("departure_date"):
            departure_date = str(state["departure_date"])
            if not self.date_pattern.match(departure_date):
                errors.append("Departure date must be in YYYY-MM-DD format")
            else:
                # Validate date is not in the past
                try:
                    dep_date = datetime.fromisoformat(departure_date)
                    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    if dep_date.date() < today.date():
                        errors.append("Departure date cannot be in the past")
                except ValueError:
                    errors.append("Invalid departure date format")

        # Validate return date format if present
        if state.get("return_date"):
            return_date = str(state["return_date"])
            if not self.date_pattern.match(return_date):
                errors.append("Return date must be in YYYY-MM-DD format")
            else:
                try:
                    ret_date = datetime.fromisoformat(return_date)
                    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    if ret_date.date() < today.date():
                        errors.append("Return date cannot be in the past")
                except ValueError:
                    errors.append("Invalid return date format")

        return errors

    def _validate_business_rules(self, state: TravelState) -> List[str]:
        """Validate business logic rules"""
        errors = []

        # Validate origin != destination
        if (state.get("origin") and state.get("destination") and
                str(state["origin"]).upper() == str(state["destination"]).upper()):
            errors.append("Origin and destination cannot be the same")

        # Validate return date is after departure date
        if state.get("departure_date") and state.get("return_date"):
            try:
                dep_date = datetime.fromisoformat(str(state["departure_date"]))
                ret_date = datetime.fromisoformat(str(state["return_date"]))

                if ret_date.date() <= dep_date.date():
                    errors.append("Return date must be after departure date")

                # Check for reasonable trip duration (not more than 1 year)
                duration = ret_date - dep_date
                if duration.days > 365:
                    errors.append("Trip duration cannot exceed 1 year")

            except ValueError:
                # Date format errors already caught in format validation
                pass

        # Validate departure date is not too far in future (2 years max)
        if state.get("departure_date"):
            try:
                dep_date = datetime.fromisoformat(str(state["departure_date"]))
                max_future = datetime.now() + timedelta(days=730)  # 2 years
                if dep_date > max_future:
                    errors.append("Departure date cannot be more than 2 years in the future")
            except ValueError:
                pass

        return errors

    def _validate_trip_type_logic(self, state: TravelState) -> List[str]:
        """Validate trip type consistency"""
        errors = []

        trip_type = state.get("trip_type")
        return_date = state.get("return_date")
        trip_type_confirmed = state.get("trip_type_confirmed", False)

        # Trip type must be decided and confirmed
        if not trip_type_confirmed:
            errors.append("Trip type not confirmed")
        elif trip_type not in ["one_way", "round_trip"]:
            errors.append("Trip type must be 'one_way' or 'round_trip'")

        # Round trip must have return date
        if trip_type == "round_trip" and not return_date:
            errors.append("Round trip must have return date")

        # One way should not have return date
        if trip_type == "one_way" and return_date:
            errors.append("One-way trip should not have return date")

        return errors

    def _validate_passenger_count(self, state: TravelState) -> List[str]:
        """Validate passenger count"""
        errors = []

        passengers = state.get("passengers")

        # Must have passenger count
        if passengers is None:
            errors.append("Passenger count is required")
        else:
            try:
                count = int(passengers)
                if count < 1:
                    errors.append("Must have at least 1 passenger")
                elif count > 9:
                    errors.append("Cannot book more than 9 passengers")
            except (ValueError, TypeError):
                errors.append("Passenger count must be a number")

        return errors

    def _generate_recommendations(self, state: TravelState) -> List[str]:
        """Generate helpful recommendations"""
        recommendations = []

        # Recommend airport codes if city names are used
        origin = str(state.get("origin", "")).strip()
        destination = str(state.get("destination", "")).strip()

        if origin and not self.airport_code_pattern.match(origin.upper()):
            if origin.lower() in ["new york", "nyc"]:
                recommendations.append("Consider using airport code JFK, LGA, or EWR for New York")
            elif origin.lower() in ["london"]:
                recommendations.append("Consider using airport code LHR, LGW, or STN for London")
            elif origin.lower() in ["paris"]:
                recommendations.append("Consider using airport code CDG or ORY for Paris")

        if destination and not self.airport_code_pattern.match(destination.upper()):
            if destination.lower() in ["new york", "nyc"]:
                recommendations.append("Consider using airport code JFK, LGA, or EWR for New York")
            elif destination.lower() in ["london"]:
                recommendations.append("Consider using airport code LHR, LGW, or STN for London")
            elif destination.lower() in ["paris"]:
                recommendations.append("Consider using airport code CDG or ORY for Paris")

        # Recommend advance booking
        if state.get("departure_date"):
            try:
                dep_date = datetime.fromisoformat(str(state["departure_date"]))
                days_ahead = (dep_date - datetime.now()).days

                if days_ahead < 7:
                    recommendations.append("Last-minute booking - prices may be higher")
                elif days_ahead > 60:
                    recommendations.append("Booking far ahead - consider flexible dates for better prices")
            except ValueError:
                pass

        # Recommend trip type clarification if ambiguous
        if not has_trip_type_decision(state):
            recommendations.append("Please confirm if this is a one-way or round trip")

        return recommendations

    def get_validation_summary(self, result: ValidationResult) -> str:
        """Get human-readable validation summary"""
        if result.ready_for_api:
            return "✅ All validation checks passed! Ready to search for flights."

        summary_parts = []

        if result.missing_required:
            missing_text = ", ".join(result.missing_required)
            summary_parts.append(f"❌ Missing required information: {missing_text}")

        if result.validation_errors:
            for error in result.validation_errors:
                summary_parts.append(f"❌ {error}")

        if result.recommendations:
            for rec in result.recommendations:
                summary_parts.append(f"💡 {rec}")

        return "\n".join(summary_parts)


# Helper function to create validator
def create_validator() -> StateValidatorTool:
    """Create state validator tool"""
    return StateValidatorTool()
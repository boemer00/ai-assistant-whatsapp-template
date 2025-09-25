"""
Test suite for PresentOptions node

Tests result formatting, state preservation, and integration with
the existing enhanced WhatsApp formatter.
"""

import pytest
from unittest.mock import Mock, patch
from typing import Dict, Any

from app.langgraph.state import (
    TravelState,
    create_initial_state,
    add_extracted_info,
    set_trip_type,
    set_search_results
)
from app.langgraph.nodes.present_options import PresentOptionsNode


class TestPresentOptionsNode:
    """Test PresentOptionsNode functionality"""

    @pytest.fixture
    def sample_amadeus_results(self):
        """Sample Amadeus API results for testing"""
        return {
            "data": [
                {
                    "id": "flight1",
                    "price": {
                        "total": "500.00",
                        "currency": "USD"
                    },
                    "itineraries": [
                        {
                            "duration": "PT8H30M",
                            "segments": [
                                {
                                    "departure": {
                                        "iataCode": "JFK",
                                        "at": "2025-12-15T08:00:00"
                                    },
                                    "arrival": {
                                        "iataCode": "LHR",
                                        "at": "2025-12-15T16:30:00"
                                    },
                                    "carrierCode": "AA",
                                    "number": "100"
                                }
                            ]
                        }
                    ]
                },
                {
                    "id": "flight2",
                    "price": {
                        "total": "650.00",
                        "currency": "USD"
                    },
                    "itineraries": [
                        {
                            "duration": "PT6H15M",
                            "segments": [
                                {
                                    "departure": {
                                        "iataCode": "JFK",
                                        "at": "2025-12-15T10:00:00"
                                    },
                                    "arrival": {
                                        "iataCode": "LHR",
                                        "at": "2025-12-15T16:15:00"
                                    },
                                    "carrierCode": "BA",
                                    "number": "178"
                                }
                            ]
                        }
                    ]
                }
            ]
        }

    @pytest.fixture
    def complete_state_with_results(self, sample_amadeus_results):
        """Complete travel state with search results"""
        state = create_initial_state()
        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "London",
            "departure_date": "2025-12-15",
            "passengers": 2
        })
        state = set_trip_type(state, "one_way", True)
        state = set_search_results(state, sample_amadeus_results, False)
        state["user_message"] = "Find flights from NYC to London"
        return state

    def test_node_creation(self):
        """Test creating presentation node"""
        node = PresentOptionsNode()
        assert node is not None
        assert node.formatter is not None

    def test_successful_presentation(self, complete_state_with_results):
        """Test successful result presentation"""
        node = PresentOptionsNode()
        result_state = node(complete_state_with_results)

        # Check conversation was updated
        assert result_state["bot_response"] != ""
        assert result_state["user_message"] == complete_state_with_results["user_message"]

        # Check response contains expected elements
        response = result_state["bot_response"]
        assert "NYC → London" in response
        assert "December 15" in response
        assert "best options" in response.lower() or "found" in response.lower()

    def test_cached_results_indication(self, complete_state_with_results):
        """Test that cached results are properly indicated"""
        # Set results as cached
        state = complete_state_with_results.copy()
        state["search_cached"] = True

        node = PresentOptionsNode()
        result_state = node(state)

        response = result_state["bot_response"]
        assert "recent search" in response.lower() or "from cache" in response.lower()

    def test_empty_results_handling(self):
        """Test handling of empty search results"""
        state = create_initial_state()
        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "London",
            "departure_date": "2025-12-15"
        })
        state = set_search_results(state, {"data": []}, False)
        state["user_message"] = "Find flights"

        node = PresentOptionsNode()
        result_state = node(state)

        response = result_state["bot_response"]
        assert "couldn't find any flights" in response.lower()
        assert "suggestions" in response.lower()

    def test_no_results_error_handling(self):
        """Test error handling when no search results exist"""
        state = create_initial_state()
        state["user_message"] = "Find flights"

        node = PresentOptionsNode()
        result_state = node(state)

        response = result_state["bot_response"]
        assert "error" in response.lower()
        assert "try searching again" in response.lower()

    def test_amadeus_results_transformation(self, sample_amadeus_results):
        """Test transformation of Amadeus results to formatter format"""
        node = PresentOptionsNode()
        transformed = node._transform_amadeus_results(sample_amadeus_results)

        assert "cheapest" in transformed
        assert "fastest" in transformed

        # Check cheapest option (should be flight1 - $500)
        cheapest = transformed["cheapest"]
        assert cheapest["price"] == 500.0
        assert cheapest["carrier"] == "AA 100"
        assert cheapest["route"] == "JFK → LHR"
        assert cheapest["duration_minutes"] == 510  # 8h30m

        # Check fastest option (should be flight2 - 6h15m)
        fastest = transformed["fastest"]
        assert fastest["price"] == 650.0
        assert fastest["carrier"] == "BA 178"
        assert fastest["duration_minutes"] == 375  # 6h15m

        # Check price difference calculation
        assert transformed["price_difference"] == 150.0
        assert "time_saved" in transformed

    def test_single_flight_formatting(self):
        """Test formatting of single flight"""
        flight = {
            "price": {"total": "500.00", "currency": "USD"},
            "itineraries": [{
                "duration": "PT8H30M",
                "segments": [{
                    "departure": {"iataCode": "JFK"},
                    "arrival": {"iataCode": "LHR"},
                    "carrierCode": "AA",
                    "number": "100"
                }]
            }]
        }

        node = PresentOptionsNode()
        formatted = node._format_flight_for_display(flight)

        assert formatted["carrier"] == "AA 100"
        assert formatted["route"] == "JFK → LHR"
        assert formatted["price"] == 500.0
        assert formatted["currency"] == "USD"
        assert formatted["duration_minutes"] == 510
        assert formatted["stops"] == 0

    def test_duration_parsing(self):
        """Test parsing of flight duration from ISO format"""
        node = PresentOptionsNode()

        # Test various duration formats
        flight_8h30m = {"itineraries": [{"duration": "PT8H30M"}]}
        assert node._get_total_duration(flight_8h30m) == 510  # 8*60 + 30

        flight_2h = {"itineraries": [{"duration": "PT2H"}]}
        assert node._get_total_duration(flight_2h) == 120  # 2*60

        flight_45m = {"itineraries": [{"duration": "PT45M"}]}
        assert node._get_total_duration(flight_45m) == 45

        # Test invalid format
        flight_invalid = {"itineraries": [{"duration": "INVALID"}]}
        assert node._get_total_duration(flight_invalid) == 999999

    def test_multi_segment_flight_handling(self):
        """Test handling of flights with multiple segments (stops)"""
        flight_with_stop = {
            "price": {"total": "400.00", "currency": "USD"},
            "itineraries": [{
                "duration": "PT12H45M",
                "segments": [
                    {
                        "departure": {"iataCode": "JFK"},
                        "arrival": {"iataCode": "FRA"},
                        "carrierCode": "LH",
                        "number": "401"
                    },
                    {
                        "departure": {"iataCode": "FRA"},
                        "arrival": {"iataCode": "LHR"},
                        "carrierCode": "LH",
                        "number": "925"
                    }
                ]
            }]
        }

        node = PresentOptionsNode()
        formatted = node._format_flight_for_display(flight_with_stop)

        assert formatted["route"] == "JFK → LHR"  # Origin to final destination
        assert formatted["stops"] == 1  # 2 segments = 1 stop
        assert formatted["carrier"] == "LH 401"  # Uses first segment

    def test_trip_summary_generation(self):
        """Test generation of trip summaries for different scenarios"""
        node = PresentOptionsNode()

        # One-way trip
        state_oneway = create_initial_state()
        state_oneway = add_extracted_info(state_oneway, {
            "origin": "NYC",
            "destination": "London",
            "departure_date": "2025-12-15",
            "passengers": 2
        })
        state_oneway = set_trip_type(state_oneway, "one_way", True)

        summary = node._get_trip_summary(state_oneway)
        assert "NYC → London" in summary
        assert "December 15" in summary
        assert "2 passengers" in summary

        # Round-trip
        state_roundtrip = state_oneway.copy()
        state_roundtrip = add_extracted_info(state_roundtrip, {"return_date": "2025-12-20"})
        state_roundtrip = set_trip_type(state_roundtrip, "round_trip", True)

        summary_rt = node._get_trip_summary(state_roundtrip)
        assert "round-trip" in summary_rt.lower() or "returning" in summary_rt.lower()

        # Single passenger (should not mention passengers)
        state_single = create_initial_state()
        state_single = add_extracted_info(state_single, {
            "origin": "NYC",
            "destination": "London",
            "departure_date": "2025-12-15",
            "passengers": 1
        })

        summary_single = node._get_trip_summary(state_single)
        assert "passengers" not in summary_single

    def test_empty_flight_data_handling(self):
        """Test handling of malformed or empty flight data"""
        node = PresentOptionsNode()

        # Empty data
        empty_results = {"data": []}
        transformed = node._transform_amadeus_results(empty_results)
        assert transformed == {}

        # Malformed flight data
        malformed_results = {
            "data": [
                {"id": "flight1"},  # Missing price and itineraries
                {"price": {"total": "500.00"}},  # Missing itineraries
            ]
        }
        transformed = node._transform_amadeus_results(malformed_results)
        # Should handle gracefully - malformed flights filtered out
        assert isinstance(transformed, dict)

    @patch('app.langgraph.nodes.present_options.NaturalFormatter')
    def test_formatter_integration(self, mock_formatter_class, complete_state_with_results):
        """Test integration with NaturalFormatter"""
        mock_formatter = Mock()
        mock_formatter.format_results_conversational.return_value = "Mocked formatted results"
        mock_formatter_class.return_value = mock_formatter

        node = PresentOptionsNode()
        result_state = node(complete_state_with_results)

        # Verify formatter was called
        mock_formatter.format_results_conversational.assert_called_once()
        call_args = mock_formatter.format_results_conversational.call_args

        # Check that transformed results were passed
        results_arg = call_args[0][0]
        assert isinstance(results_arg, dict)

        # Check cache flag was passed
        cache_flag = call_args[1]["from_cache"]
        assert cache_flag is False  # Not cached in this test

    def test_round_trip_summary_with_return_date(self):
        """Test trip summary with return date formatting"""
        state = create_initial_state()
        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "London",
            "departure_date": "2025-12-15",
            "return_date": "2025-12-22",
            "passengers": 1
        })
        state = set_trip_type(state, "round_trip", True)

        node = PresentOptionsNode()
        summary = node._get_trip_summary(state)

        assert "NYC → London" in summary
        assert "December 15" in summary
        assert ("returning December 22" in summary.lower() or
                "December 22" in summary)

    def test_state_preservation(self, complete_state_with_results):
        """Test that original state is preserved during presentation"""
        original_search_results = complete_state_with_results["search_results"]
        original_origin = complete_state_with_results["origin"]

        node = PresentOptionsNode()
        result_state = node(complete_state_with_results)

        # Original state should be preserved
        assert result_state["search_results"] == original_search_results
        assert result_state["origin"] == original_origin

        # Only conversation should be updated
        assert result_state["bot_response"] != ""
        assert result_state["user_message"] == complete_state_with_results["user_message"]


class TestPresentOptionsNodeIntegration:
    """Test integration scenarios"""

    @pytest.fixture
    def sample_amadeus_results(self):
        """Sample Amadeus API results for testing"""
        return {
            "data": [
                {
                    "id": "flight1",
                    "price": {"total": "500.00", "currency": "USD"},
                    "itineraries": [{
                        "duration": "PT8H30M",
                        "segments": [{
                            "departure": {"iataCode": "JFK"},
                            "arrival": {"iataCode": "LHR"},
                            "carrierCode": "AA",
                            "number": "100"
                        }]
                    }]
                }
            ]
        }

    @pytest.fixture
    def complete_state_with_results(self, sample_amadeus_results):
        """Complete travel state with search results"""
        state = create_initial_state()
        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "London",
            "departure_date": "2025-12-15",
            "passengers": 2
        })
        state = set_trip_type(state, "one_way", True)
        state = set_search_results(state, sample_amadeus_results, False)
        state["user_message"] = "Find flights from NYC to London"
        return state

    def test_node_function_integration(self):
        """Test the standalone present_options_node function"""
        from app.langgraph.nodes.present_options import present_options_node

        state = create_initial_state()
        state = set_search_results(state, {"data": []}, False)
        state["user_message"] = "test"

        result = present_options_node(state)

        assert isinstance(result, dict)
        assert result["bot_response"] != ""

    def test_phase_1_completion_marker(self, complete_state_with_results):
        """Test that Phase 1 is properly completed"""
        node = PresentOptionsNode()
        result_state = node(complete_state_with_results)

        # Phase 1 should be complete - results are formatted and presented
        assert result_state["bot_response"] != ""
        assert result_state["search_results"] is not None

        # State should be ready for potential Phase 2 extensions
        assert "origin" in result_state
        assert "destination" in result_state
        assert "departure_date" in result_state


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
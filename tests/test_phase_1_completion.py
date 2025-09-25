"""
Test suite for Phase 1 completion validation

Validates that the complete LangGraph pipeline works end-to-end
and properly terminates at the Phase 1 endpoint with preserved state.
"""

import pytest
from unittest.mock import Mock

from app.langgraph.state import create_initial_state
from app.langgraph.graph import compile_travel_graph, start_conversation


class TestPhase1Completion:
    """Test Phase 1 completion scenarios"""

    @pytest.fixture
    def mock_llm_complete_extraction(self):
        """Mock LLM that returns complete travel information"""
        llm = Mock()
        llm.invoke.return_value.content = """
        {
            "origin": "NYC",
            "destination": "London",
            "departure_date": "2025-12-15",
            "passengers": 2,
            "trip_type": "one_way",
            "confidence_scores": {
                "origin": 0.95,
                "destination": 0.95,
                "departure_date": 0.95,
                "passengers": 0.95,
                "trip_type": 0.95
            }
        }
        """
        return llm

    @pytest.fixture
    def mock_amadeus_with_results(self):
        """Mock Amadeus client with realistic flight results"""
        client = Mock()
        client.search_flights.return_value = {
            "data": [
                {
                    "id": "flight1",
                    "price": {"total": "450.00", "currency": "USD"},
                    "itineraries": [{
                        "duration": "PT7H30M",
                        "segments": [{
                            "departure": {
                                "iataCode": "JFK",
                                "at": "2025-12-15T08:00:00"
                            },
                            "arrival": {
                                "iataCode": "LHR",
                                "at": "2025-12-15T15:30:00"
                            },
                            "carrierCode": "BA",
                            "number": "117"
                        }]
                    }]
                },
                {
                    "id": "flight2",
                    "price": {"total": "380.00", "currency": "USD"},
                    "itineraries": [{
                        "duration": "PT9H15M",
                        "segments": [
                            {
                                "departure": {
                                    "iataCode": "JFK",
                                    "at": "2025-12-15T10:00:00"
                                },
                                "arrival": {
                                    "iataCode": "CDG",
                                    "at": "2025-12-15T16:00:00"
                                },
                                "carrierCode": "AF",
                                "number": "007"
                            },
                            {
                                "departure": {
                                    "iataCode": "CDG",
                                    "at": "2025-12-15T18:30:00"
                                },
                                "arrival": {
                                    "iataCode": "LHR",
                                    "at": "2025-12-15T19:15:00"
                                },
                                "carrierCode": "AF",
                                "number": "1181"
                            }
                        ]
                    }]
                }
            ]
        }
        return client

    @pytest.fixture
    def mock_cache_manager(self):
        """Mock cache manager"""
        cache = Mock()
        cache.get_cached_results.return_value = None
        return cache

    def test_complete_phase_1_pipeline(self, mock_llm_complete_extraction,
                                     mock_amadeus_with_results, mock_cache_manager):
        """Test complete Phase 1 pipeline from start to finish"""
        # Create compiled graph with all dependencies
        graph = compile_travel_graph(
            llm=mock_llm_complete_extraction,
            amadeus_client=mock_amadeus_with_results,
            cache_manager=mock_cache_manager
        )

        # Execute complete conversation flow
        initial_state = start_conversation(
            "I need a one-way flight from NYC to London on December 15th for 2 passengers"
        )

        final_state = graph.invoke(initial_state)

        # Validate Phase 1 completion
        self._validate_phase_1_completion(final_state)

        # Validate API integration worked
        mock_amadeus_with_results.search_flights.assert_called_once()

        # Validate state preservation for Phase 2
        self._validate_phase_2_readiness(final_state)

    def test_round_trip_phase_1_completion(self, mock_llm_complete_extraction,
                                         mock_amadeus_with_results, mock_cache_manager):
        """Test Phase 1 completion with round-trip scenario"""
        # Update mock for round-trip
        mock_llm_complete_extraction.invoke.return_value.content = """
        {
            "origin": "NYC",
            "destination": "London",
            "departure_date": "2025-12-15",
            "return_date": "2025-12-22",
            "passengers": 1,
            "trip_type": "round_trip",
            "confidence_scores": {
                "origin": 0.95,
                "destination": 0.95,
                "departure_date": 0.95,
                "return_date": 0.90,
                "passengers": 0.95,
                "trip_type": 0.90
            }
        }
        """

        graph = compile_travel_graph(
            llm=mock_llm_complete_extraction,
            amadeus_client=mock_amadeus_with_results,
            cache_manager=mock_cache_manager
        )

        initial_state = start_conversation(
            "I need a round-trip flight from NYC to London, December 15-22 for 1 person"
        )

        final_state = graph.invoke(initial_state)

        # Validate Phase 1 completion
        self._validate_phase_1_completion(final_state)

        # Validate round-trip specific elements
        assert final_state["trip_type"] == "round_trip"
        assert final_state["return_date"] == "2025-12-22"
        assert "round-trip" in final_state["bot_response"].lower()

        # API should have been called with return date
        call_args = mock_amadeus_with_results.search_flights.call_args
        assert call_args[1]["ret_date"] == "2025-12-22"

    def test_cached_results_phase_1_completion(self, mock_llm_complete_extraction,
                                             mock_amadeus_with_results, mock_cache_manager):
        """Test Phase 1 completion with cached results"""
        # Configure cache to return results
        cached_results = {
            "data": [{
                "id": "cached_flight",
                "price": {"total": "425.00", "currency": "USD"},
                "itineraries": [{
                    "duration": "PT8H00M",
                    "segments": [{
                        "departure": {"iataCode": "JFK"},
                        "arrival": {"iataCode": "LHR"},
                        "carrierCode": "VS",
                        "number": "003"
                    }]
                }]
            }]
        }
        mock_cache_manager.get_cached_results.return_value = cached_results

        graph = compile_travel_graph(
            llm=mock_llm_complete_extraction,
            amadeus_client=mock_amadeus_with_results,
            cache_manager=mock_cache_manager
        )

        initial_state = start_conversation(
            "Find flights from NYC to London on December 15th for 2 passengers"
        )

        final_state = graph.invoke(initial_state)

        # Validate Phase 1 completion with cache
        self._validate_phase_1_completion(final_state)

        # Should use cached results, not API
        mock_amadeus_with_results.search_flights.assert_not_called()
        assert final_state["search_cached"] is True
        assert "recent search" in final_state["bot_response"].lower()

    def test_multiple_flight_options_presentation(self, mock_llm_complete_extraction,
                                                mock_amadeus_with_results, mock_cache_manager):
        """Test that multiple flight options are properly presented"""
        graph = compile_travel_graph(
            llm=mock_llm_complete_extraction,
            amadeus_client=mock_amadeus_with_results,
            cache_manager=mock_cache_manager
        )

        initial_state = start_conversation(
            "Book a one-way flight NYC to London December 15th for 2 people"
        )

        final_state = graph.invoke(initial_state)

        response = final_state["bot_response"]

        # Should present both cheapest and fastest options
        assert "Best Value" in response
        assert "Fastest Option" in response or "best options" in response

        # Should include actionable next steps
        assert ("book" in response.lower() or
                "what would you like" in response.lower())

        # Should include trip summary
        assert "NYC → London" in response
        assert "December 15" in response
        assert "2 passengers" in response

    def test_phase_1_state_completeness(self, mock_llm_complete_extraction,
                                      mock_amadeus_with_results, mock_cache_manager):
        """Test that Phase 1 ends with complete state information"""
        graph = compile_travel_graph(
            llm=mock_llm_complete_extraction,
            amadeus_client=mock_amadeus_with_results,
            cache_manager=mock_cache_manager
        )

        initial_state = start_conversation("NYC to London Dec 15, 2 people")
        final_state = graph.invoke(initial_state)

        # All required fields should be present and valid
        required_fields = ["origin", "destination", "departure_date", "passengers"]
        for field in required_fields:
            assert final_state.get(field) is not None, f"Missing required field: {field}"

        # State should be complete and validated
        assert final_state["ready_for_api"] is True
        assert final_state["trip_type_confirmed"] is True
        assert final_state["validation_errors"] == []

        # Should have search results
        assert final_state["search_results"] is not None
        assert isinstance(final_state["search_results"], dict)

        # Should have complete conversation history
        assert len(final_state["conversation_history"]) > 0
        assert final_state["user_message"] != ""
        assert final_state["bot_response"] != ""

    def _validate_phase_1_completion(self, final_state: dict):
        """Validate that Phase 1 has completed successfully"""
        # Core Phase 1 completion checks
        assert final_state is not None
        assert isinstance(final_state, dict)

        # Search results should be present and formatted
        assert final_state.get("search_results") is not None
        assert final_state.get("bot_response") != ""

        # Response should be formatted naturally
        response = final_state["bot_response"]
        assert any(phrase in response.lower() for phrase in [
            "best options", "found flights", "here are", "best value"
        ])

        # Should include actionable elements
        assert any(phrase in response.lower() for phrase in [
            "book", "reply", "what would you like"
        ])

        # Trip information should be present in response
        assert "→" in response  # Route indicator
        assert any(phrase in response for phrase in [
            "December", "passengers", "person"
        ])

        print(f"[DEBUG] Phase 1 completion validated - response length: {len(response)} chars")

    def _validate_phase_2_readiness(self, final_state: dict):
        """Validate that state is preserved for Phase 2 extensions"""
        # All original state should be preserved
        phase_2_required_fields = [
            "origin", "destination", "departure_date", "passengers",
            "trip_type", "search_results", "conversation_history"
        ]

        for field in phase_2_required_fields:
            assert field in final_state, f"Phase 2 required field missing: {field}"
            assert final_state[field] is not None, f"Phase 2 field is None: {field}"

        # Validation flags should indicate completion
        assert final_state["ready_for_api"] is True
        assert final_state["required_fields_complete"] is True

        # State should be structured for extension
        assert isinstance(final_state["search_results"], dict)
        assert isinstance(final_state["conversation_history"], list)

        print(f"[DEBUG] Phase 2 readiness validated - state has {len(final_state)} fields")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
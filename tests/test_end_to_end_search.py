"""
End-to-end test for complete search flow through LangGraph

Tests the complete conversation flow from initial message through
information collection, validation, and flight search execution.
"""

import pytest
from unittest.mock import Mock, patch
from typing import Dict, Any

from app.langgraph.state import create_initial_state
from app.langgraph.graph import compile_travel_graph, start_conversation


class TestEndToEndSearchFlow:
    """Test complete search flow through the LangGraph system"""

    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM for testing"""
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
                "destination": 0.90,
                "departure_date": 0.85,
                "passengers": 0.95,
                "trip_type": 0.80
            }
        }
        """
        return llm

    @pytest.fixture
    def mock_amadeus_client(self):
        """Create mock Amadeus client"""
        client = Mock()
        client.search_flights.return_value = {
            "data": [
                {
                    "id": "flight1",
                    "price": {"total": "500.00", "currency": "USD"},
                    "itineraries": [
                        {
                            "segments": [
                                {
                                    "departure": {
                                        "iataCode": "JFK",
                                        "at": "2025-01-15T08:00:00"
                                    },
                                    "arrival": {
                                        "iataCode": "LHR",
                                        "at": "2025-01-15T20:00:00"
                                    },
                                    "carrierCode": "AA",
                                    "number": "100"
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        return client

    @pytest.fixture
    def mock_cache_manager(self):
        """Create mock cache manager"""
        cache = Mock()
        cache.get_cached_results.return_value = None  # No cache hits
        return cache

    def test_complete_search_flow_success(self, mock_llm, mock_amadeus_client, mock_cache_manager):
        """Test complete successful search flow"""
        # Compile graph with mocked dependencies
        compiled_graph = compile_travel_graph(
            llm=mock_llm,
            amadeus_client=mock_amadeus_client,
            cache_manager=mock_cache_manager
        )

        # Start conversation
        initial_state = start_conversation("I need a one-way flight from NYC to London on December 15th for 2 passengers")

        # Execute the graph
        final_state = compiled_graph.invoke(initial_state)

        # Verify the flow completed successfully
        assert final_state is not None
        assert isinstance(final_state, dict)

        # Check that search results were populated
        assert final_state.get("search_results") is not None
        assert final_state.get("search_cached") is False

        # Check that conversation was updated properly
        assert final_state.get("bot_response") is not None
        assert ("best options" in final_state["bot_response"] or
                "Found flights" in final_state["bot_response"])

        # Verify API was called correctly
        mock_amadeus_client.search_flights.assert_called_once()
        call_args = mock_amadeus_client.search_flights.call_args
        assert call_args[1]["origin"] == "NYC"
        assert call_args[1]["destination"] == "LHR"
        assert call_args[1]["dep_date"] == "2025-12-15"
        assert call_args[1]["adults"] == 2

    def test_search_flow_with_incomplete_info(self, mock_llm, mock_amadeus_client, mock_cache_manager):
        """Test search flow with incomplete initial information"""
        # Mock LLM to return incomplete extraction
        mock_llm.invoke.return_value.content = """
        {
            "origin": "NYC",
            "destination": null,
            "departure_date": null,
            "passengers": null,
            "trip_type": "undecided",
            "confidence_scores": {
                "origin": 0.95
            }
        }
        """

        compiled_graph = compile_travel_graph(
            llm=mock_llm,
            amadeus_client=mock_amadeus_client,
            cache_manager=mock_cache_manager
        )

        initial_state = start_conversation("I need a flight from NYC")

        final_state = compiled_graph.invoke(initial_state)

        # Should not have made API call due to incomplete information
        mock_amadeus_client.search_flights.assert_not_called()

        # Should have requested clarification
        assert final_state.get("bot_response") is not None
        assert final_state.get("ready_for_api", False) is False

    def test_search_flow_validation_gate_enforcement(self, mock_llm, mock_amadeus_client, mock_cache_manager):
        """Test that validation gate properly blocks incomplete requests"""
        # Mock LLM to return data that looks complete but fails validation
        mock_llm.invoke.return_value.content = """
        {
            "origin": "NYC",
            "destination": "NYC",
            "departure_date": "2024-12-15",
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

        compiled_graph = compile_travel_graph(
            llm=mock_llm,
            amadeus_client=mock_amadeus_client,
            cache_manager=mock_cache_manager
        )

        initial_state = start_conversation("Flight from NYC to NYC yesterday for 2 people")

        final_state = compiled_graph.invoke(initial_state)

        # Validation should have blocked this due to:
        # 1. Same origin/destination
        # 2. Past date
        mock_amadeus_client.search_flights.assert_not_called()

        # Should have validation error response
        assert final_state.get("ready_for_api", False) is False
        assert final_state.get("validation_errors") is not None
        assert len(final_state.get("validation_errors", [])) > 0

    def test_search_flow_with_api_error(self, mock_llm, mock_amadeus_client, mock_cache_manager):
        """Test search flow when API call fails"""
        # Configure API to fail
        mock_amadeus_client.search_flights.side_effect = Exception("API timeout error")

        # Mock LLM to return complete valid data
        mock_llm.invoke.return_value.content = """
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

        compiled_graph = compile_travel_graph(
            llm=mock_llm,
            amadeus_client=mock_amadeus_client,
            cache_manager=mock_cache_manager
        )

        initial_state = start_conversation("Flight from NYC to London on Jan 15th for 2 people")

        final_state = compiled_graph.invoke(initial_state)

        # API should have been called and failed
        mock_amadeus_client.search_flights.assert_called_once()

        # Should have error response
        assert final_state.get("search_results") is None
        assert final_state.get("bot_response") is not None
        assert "taking longer than usual" in final_state["bot_response"]

    def test_search_flow_with_cached_results(self, mock_llm, mock_amadeus_client, mock_cache_manager):
        """Test search flow with cached results"""
        # Configure cache to return results
        cached_results = {
            "data": [
                {
                    "id": "cached_flight",
                    "price": {"total": "450.00", "currency": "USD"}
                }
            ]
        }
        mock_cache_manager.get_cached_results.return_value = cached_results

        # Mock LLM to return complete data
        mock_llm.invoke.return_value.content = """
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

        compiled_graph = compile_travel_graph(
            llm=mock_llm,
            amadeus_client=mock_amadeus_client,
            cache_manager=mock_cache_manager
        )

        initial_state = start_conversation("Flight from NYC to London on Jan 15th for 2 people")

        final_state = compiled_graph.invoke(initial_state)

        # API should NOT have been called due to cache hit
        mock_amadeus_client.search_flights.assert_not_called()

        # Should have cached results
        assert final_state.get("search_results") == cached_results
        assert final_state.get("search_cached") is True
        assert "from recent search" in final_state["bot_response"]

    def test_round_trip_flow(self, mock_llm, mock_amadeus_client, mock_cache_manager):
        """Test complete round-trip search flow"""
        # Mock LLM to return round-trip data
        mock_llm.invoke.return_value.content = """
        {
            "origin": "NYC",
            "destination": "London",
            "departure_date": "2025-12-15",
            "return_date": "2025-12-20",
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

        compiled_graph = compile_travel_graph(
            llm=mock_llm,
            amadeus_client=mock_amadeus_client,
            cache_manager=mock_cache_manager
        )

        initial_state = start_conversation(
            "I need a round-trip flight from NYC to London, departing Dec 15th and returning Dec 20th"
        )

        final_state = compiled_graph.invoke(initial_state)

        # Verify API was called with return date
        mock_amadeus_client.search_flights.assert_called_once()
        call_args = mock_amadeus_client.search_flights.call_args
        assert call_args[1]["ret_date"] == "2025-12-20"

        # Check response mentions round-trip
        assert "round-trip" in final_state["bot_response"]

    def test_clarification_attempt_limit(self, mock_llm, mock_amadeus_client, mock_cache_manager):
        """Test that excessive clarification attempts end conversation"""
        # Mock LLM to consistently return incomplete data
        mock_llm.invoke.return_value.content = """
        {
            "origin": null,
            "destination": null,
            "departure_date": null,
            "passengers": null,
            "trip_type": "undecided",
            "confidence_scores": {}
        }
        """

        compiled_graph = compile_travel_graph(
            llm=mock_llm,
            amadeus_client=mock_amadeus_client,
            cache_manager=mock_cache_manager
        )

        # Start with a state that has high clarification attempts
        initial_state = start_conversation("unclear message")
        initial_state["clarification_attempts"] = 2  # Close to limit

        final_state = compiled_graph.invoke(initial_state)

        # Should have terminated due to too many attempts
        assert final_state.get("clarification_attempts", 0) >= 3

        # API should never have been called
        mock_amadeus_client.search_flights.assert_not_called()


class TestSearchFlowEdgeCases:
    """Test edge cases in search flow"""

    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM"""
        llm = Mock()
        return llm

    @pytest.fixture
    def mock_amadeus_client(self):
        """Create mock Amadeus client"""
        return Mock()

    def test_graph_without_dependencies(self):
        """Test graph execution without LLM or Amadeus client"""
        compiled_graph = compile_travel_graph()  # No dependencies

        initial_state = start_conversation("Test message")

        # Should complete without errors (using placeholder implementations)
        final_state = compiled_graph.invoke(initial_state)

        assert final_state is not None
        assert isinstance(final_state, dict)

    @patch('app.langgraph.nodes.search_flights.SearchFlightsNode')
    def test_node_creation_error_handling(self, mock_node_class, mock_llm, mock_amadeus_client):
        """Test error handling during node creation"""
        # Configure mock to raise error
        mock_node_class.side_effect = Exception("Node creation failed")

        compiled_graph = compile_travel_graph(
            llm=mock_llm,
            amadeus_client=mock_amadeus_client
        )

        initial_state = start_conversation("Test message")

        # Should handle error gracefully
        with pytest.raises(Exception):
            compiled_graph.invoke(initial_state)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
"""
Test suite for SearchFlights node and AmadeusSearchTool

Tests flight search functionality, validation gates, cache integration,
and error handling scenarios.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

from app.langgraph.state import (
    TravelState,
    create_initial_state,
    add_extracted_info,
    set_trip_type,
    set_api_ready,
    set_search_results
)
from app.langgraph.nodes.search_flights import SearchFlightsNode
from app.langgraph.tools.amadeus_search import AmadeusSearchTool, SearchParams, SearchResult


class TestAmadeusSearchTool:
    """Test AmadeusSearchTool functionality"""

    @pytest.fixture
    def mock_amadeus_client(self):
        """Create mock Amadeus client"""
        client = Mock()
        client.search_flights.return_value = {
            "data": [
                {
                    "id": "flight1",
                    "price": {"total": "500.00", "currency": "USD"},
                    "itineraries": []
                }
            ]
        }
        return client

    @pytest.fixture
    def mock_cache_manager(self):
        """Create mock cache manager"""
        cache = Mock()
        cache.get_cached_results.return_value = None  # No cache by default
        return cache

    @pytest.fixture
    def validated_state(self):
        """Create validated state ready for API"""
        state = create_initial_state()
        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": "2025-01-15",
            "passengers": 2
        })
        state = set_trip_type(state, "one_way", True)
        state = set_api_ready(state, True)
        return state

    def test_search_tool_creation(self, mock_amadeus_client, mock_cache_manager):
        """Test creating search tool"""
        tool = AmadeusSearchTool(mock_amadeus_client, mock_cache_manager)

        assert tool.amadeus_client == mock_amadeus_client
        assert tool.cache_manager == mock_cache_manager

    def test_search_with_validated_state(self, mock_amadeus_client, mock_cache_manager, validated_state):
        """Test successful search with validated state"""
        tool = AmadeusSearchTool(mock_amadeus_client, mock_cache_manager)

        result = tool.search(validated_state)

        assert result.success is True
        assert result.results is not None
        assert result.cached is False
        assert result.search_duration_ms is not None
        assert result.search_duration_ms >= 0

        # Verify API was called correctly
        mock_amadeus_client.search_flights.assert_called_once_with(
            origin="NYC",
            destination="LON",
            dep_date="2025-01-15",
            ret_date=None,
            adults=2
        )

    def test_search_blocks_unvalidated_state(self, mock_amadeus_client, mock_cache_manager):
        """Test that search blocks unvalidated state"""
        state = create_initial_state()
        # Don't set ready_for_api=True

        tool = AmadeusSearchTool(mock_amadeus_client, mock_cache_manager)
        result = tool.search(state)

        assert result.success is False
        assert "validation error" in result.error.lower()
        assert result.cached is False

        # Verify API was NOT called
        mock_amadeus_client.search_flights.assert_not_called()

    def test_search_with_cache_hit(self, mock_amadeus_client, mock_cache_manager, validated_state):
        """Test search with cache hit"""
        cached_results = {"data": [{"cached": True}]}
        mock_cache_manager.get_cached_results.return_value = cached_results

        tool = AmadeusSearchTool(mock_amadeus_client, mock_cache_manager)
        result = tool.search(validated_state)

        assert result.success is True
        assert result.results == cached_results
        assert result.cached is True
        assert result.cache_key is not None

        # API should not be called when cache hits
        mock_amadeus_client.search_flights.assert_not_called()

    def test_search_with_round_trip(self, mock_amadeus_client, mock_cache_manager):
        """Test search with round trip parameters"""
        state = create_initial_state()
        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": "2025-01-15",
            "return_date": "2025-01-20",
            "passengers": 1
        })
        state = set_trip_type(state, "round_trip", True)
        state = set_api_ready(state, True)

        tool = AmadeusSearchTool(mock_amadeus_client, mock_cache_manager)
        result = tool.search(state)

        assert result.success is True

        # Verify return date was passed
        mock_amadeus_client.search_flights.assert_called_once_with(
            origin="NYC",
            destination="LON",
            dep_date="2025-01-15",
            ret_date="2025-01-20",
            adults=1
        )

    def test_search_api_error_handling(self, mock_amadeus_client, mock_cache_manager, validated_state):
        """Test API error handling"""
        mock_amadeus_client.search_flights.side_effect = Exception("API timeout")

        tool = AmadeusSearchTool(mock_amadeus_client, mock_cache_manager)
        result = tool.search(validated_state)

        assert result.success is False
        assert "API timeout" in result.error
        assert result.cached is False

    def test_airport_code_resolution(self, mock_amadeus_client, mock_cache_manager):
        """Test airport code resolution"""
        tool = AmadeusSearchTool(mock_amadeus_client, mock_cache_manager)

        # Test city name resolution
        assert tool._resolve_airport_code("New York") == "JFK"
        assert tool._resolve_airport_code("London") == "LHR"
        assert tool._resolve_airport_code("Paris") == "CDG"

        # Test existing codes pass through
        assert tool._resolve_airport_code("LAX") == "LAX"
        assert tool._resolve_airport_code("JFK") == "JFK"

        # Test unknown locations pass through
        assert tool._resolve_airport_code("Unknown City") == "UNKNOWN CITY"

    def test_cache_key_generation(self, mock_amadeus_client, mock_cache_manager):
        """Test cache key generation"""
        tool = AmadeusSearchTool(mock_amadeus_client, mock_cache_manager)

        params = SearchParams(
            origin="NYC",
            destination="LON",
            departure_date="2025-01-15",
            return_date=None,
            passengers=2,
            trip_type="one_way"
        )

        cache_key = tool._create_cache_key(params)
        expected = "NYC|LON|2025-01-15|ONEWAY|2"
        assert cache_key == expected

        # Test round trip
        params.return_date = "2025-01-20"
        cache_key = tool._create_cache_key(params)
        expected = "NYC|LON|2025-01-15|2025-01-20|2"
        assert cache_key == expected


class TestSearchFlightsNode:
    """Test SearchFlightsNode functionality"""

    @pytest.fixture
    def mock_amadeus_client(self):
        """Create mock Amadeus client"""
        client = Mock()
        client.search_flights.return_value = {
            "data": [{"id": "flight1", "price": {"total": "500.00"}}]
        }
        return client

    @pytest.fixture
    def mock_cache_manager(self):
        """Create mock cache manager"""
        cache = Mock()
        cache.get_cached_results.return_value = None
        return cache

    @pytest.fixture
    def validated_state(self):
        """Create validated state ready for API"""
        state = create_initial_state()
        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": "2025-01-15",
            "passengers": 2
        })
        state = set_trip_type(state, "one_way", True)
        state = set_api_ready(state, True)
        state["user_message"] = "Find flights from NYC to London"
        return state

    def test_node_creation(self, mock_amadeus_client, mock_cache_manager):
        """Test creating search flights node"""
        node = SearchFlightsNode(mock_amadeus_client, mock_cache_manager)

        assert node.amadeus_client == mock_amadeus_client
        assert node.cache_manager == mock_cache_manager
        assert node.search_tool is not None

    def test_successful_search_execution(self, mock_amadeus_client, mock_cache_manager, validated_state):
        """Test successful search execution"""
        node = SearchFlightsNode(mock_amadeus_client, mock_cache_manager)

        result_state = node(validated_state)

        # Check search results were set
        assert result_state["search_results"] is not None
        assert result_state["search_cached"] is False

        # Check conversation was updated
        assert "Found flights from NYC to LON" in result_state["bot_response"]
        assert result_state["user_message"] == validated_state["user_message"]

    def test_blocks_unvalidated_state(self, mock_amadeus_client, mock_cache_manager):
        """Test that node blocks unvalidated state"""
        state = create_initial_state()
        state["user_message"] = "Test message"
        # ready_for_api is False

        node = SearchFlightsNode(mock_amadeus_client, mock_cache_manager)
        result_state = node(state)

        # Should return error response
        assert "Internal error" in result_state["bot_response"]
        assert result_state["clarification_attempts"] == 1

        # API should not have been called
        mock_amadeus_client.search_flights.assert_not_called()

    def test_search_failure_handling(self, mock_amadeus_client, mock_cache_manager, validated_state):
        """Test handling of search failures"""
        mock_amadeus_client.search_flights.side_effect = Exception("Network timeout")

        node = SearchFlightsNode(mock_amadeus_client, mock_cache_manager)
        result_state = node(validated_state)

        # Should handle error gracefully
        assert "taking longer than usual" in result_state["bot_response"]
        assert result_state["search_results"] is None

    def test_cached_results_handling(self, mock_amadeus_client, mock_cache_manager, validated_state):
        """Test handling of cached results"""
        cached_data = {"data": [{"id": "cached_flight"}]}
        mock_cache_manager.get_cached_results.return_value = cached_data

        node = SearchFlightsNode(mock_amadeus_client, mock_cache_manager)
        result_state = node(validated_state)

        assert result_state["search_results"] == cached_data
        assert result_state["search_cached"] is True
        assert "from recent search" in result_state["bot_response"]

    def test_response_generation_with_timing(self, mock_amadeus_client, mock_cache_manager, validated_state):
        """Test response generation includes timing information"""
        node = SearchFlightsNode(mock_amadeus_client, mock_cache_manager)

        # Mock the search tool to return timing info
        with patch.object(node.search_tool, 'search') as mock_search:
            mock_search.return_value = SearchResult(
                success=True,
                results={"data": []},
                cached=False,
                search_duration_ms=500
            )

            result_state = node(validated_state)

            assert "quickly" in result_state["bot_response"]

    def test_trip_summary_generation(self, mock_amadeus_client, mock_cache_manager):
        """Test trip summary generation for different scenarios"""
        node = SearchFlightsNode(mock_amadeus_client, mock_cache_manager)

        # Test one-way with multiple passengers
        state = create_initial_state()
        state = add_extracted_info(state, {
            "origin": "NYC",
            "destination": "LON",
            "passengers": 3
        })
        state = set_trip_type(state, "one_way", True)

        summary = node._get_trip_summary(state)
        assert "from NYC to LON for 3 passengers (one-way)" in summary

        # Test round-trip single passenger
        state = add_extracted_info(state, {"passengers": 1})
        state = set_trip_type(state, "round_trip", True)

        summary = node._get_trip_summary(state)
        assert "from NYC to LON (round-trip)" in summary

    def test_error_response_generation(self, mock_amadeus_client, mock_cache_manager):
        """Test error response generation for different error types"""
        node = SearchFlightsNode(mock_amadeus_client, mock_cache_manager)

        # Test rate limit error
        response = node._generate_error_response("Rate limit exceeded")
        assert "high demand" in response

        # Test timeout error
        response = node._generate_error_response("Network timeout")
        assert "taking longer than usual" in response

        # Test no flights found
        response = node._generate_error_response("No flights found")
        assert "adjusting your dates" in response

        # Test invalid airport code
        response = node._generate_error_response("Invalid airport code")
        assert "check your departure and arrival cities" in response


class TestSearchNodeIntegration:
    """Test integration between SearchFlightsNode and graph routing"""

    def test_successful_search_routes_to_present(self):
        """Test that successful search results route to present_options"""
        from app.langgraph.graph import should_present

        state = create_initial_state()
        state = set_search_results(state, {"data": [{"flight": "data"}]}, False)

        next_node = should_present(state)
        assert next_node == "present_options"

    def test_failed_search_routes_to_clarification(self):
        """Test that failed search routes to clarification"""
        from app.langgraph.graph import should_present

        state = create_initial_state()
        # No search results set

        next_node = should_present(state)
        assert next_node == "needs_clarification"

    @patch('app.langgraph.nodes.search_flights.AmadeusSearchTool')
    def test_node_function_integration(self, mock_tool_class):
        """Test the standalone search_flights_node function"""
        from app.langgraph.nodes.search_flights import search_flights_node

        # Create mock clients
        mock_amadeus_client = Mock()
        mock_cache_manager = Mock()

        # Create validated state
        state = create_initial_state()
        state = set_api_ready(state, True)

        result = search_flights_node(state, mock_amadeus_client, mock_cache_manager)

        # Should create SearchFlightsNode and call it
        mock_tool_class.assert_called_once()
        assert isinstance(result, dict)

    def test_node_function_without_client(self):
        """Test node function fallback without client"""
        from app.langgraph.nodes.search_flights import search_flights_node

        state = create_initial_state()
        state["user_message"] = "test"

        result = search_flights_node(state)

        assert "unavailable" in result["bot_response"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
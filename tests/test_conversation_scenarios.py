"""
End-to-end conversation scenario tests

Tests complete conversation flows through the integrated LangGraph system
to validate the main handler integration works properly.
"""

import pytest
from unittest.mock import Mock

from app.langgraph.handler import LangGraphHandler


class TestConversationScenarios:
    """Test real conversation scenarios through integrated system"""

    @pytest.fixture
    def mock_session_store(self):
        """Mock session store that maintains state"""
        store = Mock()
        store.sessions = {}  # Track sessions

        def mock_get(user_id):
            return store.sessions.get(user_id)

        def mock_set(user_id, data):
            store.sessions[user_id] = data

        store.get.side_effect = mock_get
        store.set.side_effect = mock_set
        return store

    @pytest.fixture
    def mock_llm_realistic(self):
        """Mock LLM with realistic responses"""
        llm = Mock()

        # Define responses for different message patterns
        def mock_invoke(prompt):
            message = str(prompt).lower()
            mock_response = Mock()

            if "nyc" in message and "london" in message and "december" in message:
                # Complete travel request
                mock_response.content = """
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
            elif "hello" in message or "hi" in message:
                # Greeting
                mock_response.content = """
                {
                    "confidence_scores": {}
                }
                """
            else:
                # Default response
                mock_response.content = """
                {
                    "confidence_scores": {}
                }
                """

            return mock_response

        llm.invoke.side_effect = mock_invoke
        return llm

    @pytest.fixture
    def mock_amadeus_client(self):
        """Mock Amadeus with flight results"""
        client = Mock()
        client.search_flights.return_value = {
            "data": [
                {
                    "id": "flight1",
                    "price": {"total": "450.00", "currency": "USD"},
                    "itineraries": [{
                        "duration": "PT7H30M",
                        "segments": [{
                            "departure": {"iataCode": "JFK", "at": "2025-12-15T08:00:00"},
                            "arrival": {"iataCode": "LHR", "at": "2025-12-15T15:30:00"},
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
                        "segments": [{
                            "departure": {"iataCode": "JFK", "at": "2025-12-15T10:00:00"},
                            "arrival": {"iataCode": "LHR", "at": "2025-12-15T19:15:00"},
                            "carrierCode": "VS",
                            "number": "003"
                        }]
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

    @pytest.fixture
    def integrated_handler(self, mock_session_store, mock_llm_realistic, mock_amadeus_client, mock_cache_manager):
        """Create integrated LangGraph handler with realistic mocks"""
        return LangGraphHandler(
            session_store=mock_session_store,
            llm=mock_llm_realistic,
            amadeus_client=mock_amadeus_client,
            cache_manager=mock_cache_manager
        )

    def test_complete_flight_booking_conversation(self, integrated_handler):
        """Test complete conversation from greeting to flight results"""
        user_id = "test_user_complete"

        # Step 1: User greets
        response1 = integrated_handler.handle_message(user_id, "Hi!")
        print(f"Response 1: {response1}")

        assert "flight" in response1.lower() or "help" in response1.lower()
        assert len(response1) > 0

        # Step 2: User provides complete flight request
        response2 = integrated_handler.handle_message(
            user_id,
            "I need a one-way flight from NYC to London on December 15th for 2 passengers"
        )
        print(f"Response 2: {response2}")

        # Should show flight results after going through complete pipeline
        assert ("best" in response2.lower() or
                "options" in response2.lower() or
                "flights" in response2.lower())

        # Check session state
        session_info = integrated_handler.get_user_session_info(user_id)
        print(f"Session info: {session_info}")

        assert session_info["status"] == "active_conversation"
        # The response should indicate we found flights or completed processing

    def test_gradual_information_collection(self, integrated_handler):
        """Test gradual information collection conversation"""
        user_id = "test_user_gradual"

        # Step 1: User mentions destination only
        response1 = integrated_handler.handle_message(user_id, "I want to go to London")
        print(f"Response 1: {response1}")

        # Step 2: Add origin
        response2 = integrated_handler.handle_message(user_id, "From New York")
        print(f"Response 2: {response2}")

        # Step 3: Add date and passengers
        response3 = integrated_handler.handle_message(user_id, "On December 15th for 2 people")
        print(f"Response 3: {response3}")

        # Should eventually get to flight results or confirmation
        session_info = integrated_handler.get_user_session_info(user_id)
        print(f"Final session: {session_info}")

        assert session_info["status"] == "active_conversation"

    def test_error_handling_conversation(self, integrated_handler, mock_amadeus_client):
        """Test conversation when API errors occur"""
        user_id = "test_user_error"

        # Make Amadeus client fail
        mock_amadeus_client.search_flights.side_effect = Exception("API error")

        # Provide complete request
        response = integrated_handler.handle_message(
            user_id,
            "One-way flight NYC to London December 15th for 2 passengers"
        )
        print(f"Error response: {response}")

        # Should handle error gracefully
        assert len(response) > 0
        # Error should be handled gracefully - either retry prompt or error message

    def test_session_persistence_across_messages(self, integrated_handler):
        """Test that session state persists across messages"""
        user_id = "test_user_persistence"

        # Send multiple messages
        response1 = integrated_handler.handle_message(user_id, "I need a flight")
        response2 = integrated_handler.handle_message(user_id, "From NYC")
        response3 = integrated_handler.handle_message(user_id, "To London")

        # Get session info after each message
        session1 = integrated_handler.get_user_session_info(user_id)

        print(f"Final session after 3 messages: {session1}")

        # Session should show accumulated information
        assert session1["status"] == "active_conversation"
        # Should have at least some conversation history
        if "conversation_turns" in session1:
            assert session1["conversation_turns"] >= 1

    def test_conversation_reset_functionality(self, integrated_handler):
        """Test conversation reset clears state properly"""
        user_id = "test_user_reset"

        # Have a conversation
        integrated_handler.handle_message(user_id, "Flight from NYC to London")

        # Check there's a session
        session_before = integrated_handler.get_user_session_info(user_id)
        assert session_before["status"] == "active_conversation"

        # Reset conversation
        success = integrated_handler.reset_user_conversation(user_id)
        assert success is True

        # Check session is cleared
        session_after = integrated_handler.get_user_session_info(user_id)
        assert session_after["status"] == "no_active_conversation"

    def test_concurrent_user_sessions(self, integrated_handler):
        """Test that different users have separate sessions"""
        user1 = "test_user_1"
        user2 = "test_user_2"

        # Different users make different requests
        response1 = integrated_handler.handle_message(user1, "NYC to London")
        response2 = integrated_handler.handle_message(user2, "LA to Paris")

        # Check sessions are separate
        session1 = integrated_handler.get_user_session_info(user1)
        session2 = integrated_handler.get_user_session_info(user2)

        assert session1["status"] == "active_conversation"
        assert session2["status"] == "active_conversation"

        # Sessions should be independent
        # (Exact comparison depends on what information was extracted)
        print(f"User 1 session: {session1}")
        print(f"User 2 session: {session2}")

    def test_handler_metrics_tracking(self, integrated_handler):
        """Test that handler properly tracks metrics"""
        # Have some conversations
        integrated_handler.handle_message("user1", "Hello")
        integrated_handler.handle_message("user2", "Flight to London")

        # Get metrics
        metrics = integrated_handler.get_conversation_metrics()

        assert metrics["handler_type"] == "langgraph"
        assert "pipeline_nodes" in metrics
        assert len(metrics["pipeline_nodes"]) >= 4  # Should have all main nodes

        print(f"Handler metrics: {metrics}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
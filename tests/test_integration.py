"""
Integration test suite for LangGraph main handler integration

Tests the complete integration of LangGraph with the existing WhatsApp
infrastructure, including Redis sessions, middleware, and admin endpoints.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from typing import Dict, Any

from app.langgraph.handler import LangGraphHandler
from app.session.redis_store import RedisSessionStore
from app.cache.flight_cache import FlightCacheManager


class TestLangGraphHandler:
    """Test LangGraphHandler functionality"""

    @pytest.fixture
    def mock_session_store(self):
        """Mock Redis session store"""
        store = Mock(spec=RedisSessionStore)
        store.get.return_value = None
        store.set.return_value = True
        return store

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM"""
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
    def mock_amadeus_client(self):
        """Mock Amadeus client"""
        client = Mock()
        client.search_flights.return_value = {
            "data": [{
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
            }]
        }
        return client

    @pytest.fixture
    def mock_cache_manager(self):
        """Mock cache manager"""
        cache = Mock(spec=FlightCacheManager)
        cache.get_cached_results.return_value = None
        return cache

    @pytest.fixture
    def langgraph_handler(self, mock_session_store, mock_llm, mock_amadeus_client, mock_cache_manager):
        """Create LangGraph handler with mocked dependencies"""
        return LangGraphHandler(
            session_store=mock_session_store,
            llm=mock_llm,
            amadeus_client=mock_amadeus_client,
            cache_manager=mock_cache_manager,
            user_preferences=Mock(),
            iata_db=Mock()
        )

    def test_handler_creation(self, langgraph_handler):
        """Test LangGraph handler creation"""
        assert langgraph_handler is not None
        assert langgraph_handler.travel_graph is not None
        assert langgraph_handler.session_store is not None

    def test_new_conversation_handling(self, langgraph_handler, mock_session_store):
        """Test handling new conversation"""
        # Mock no existing session
        mock_session_store.get.return_value = None

        message = "I need a one-way flight from NYC to London on December 15th for 2 passengers"
        response = langgraph_handler.handle_message("test_user", message)

        # Should get a response
        assert response is not None
        assert isinstance(response, str)
        assert len(response) > 0

        # Should have saved session
        mock_session_store.set.assert_called()

    def test_continuing_conversation(self, langgraph_handler, mock_session_store):
        """Test continuing existing conversation"""
        # Mock existing session with state
        existing_session = {
            "langgraph_state": {
                "origin": "NYC",
                "destination": None,
                "departure_date": None,
                "user_message": "I need to go to London",
                "bot_response": "Where are you flying from?",
                "conversation_history": [],
                "trip_type": "undecided",
                "ready_for_api": False
            }
        }
        mock_session_store.get.return_value = existing_session

        response = langgraph_handler.handle_message("test_user", "From NYC on December 15th")

        # Should continue the conversation
        assert response is not None
        assert isinstance(response, str)

        # Should have updated session
        mock_session_store.set.assert_called()

    def test_session_state_persistence(self, langgraph_handler, mock_session_store):
        """Test that state is properly saved to session"""
        mock_session_store.get.return_value = None

        langgraph_handler.handle_message("test_user", "NYC to London Dec 15, 2 people")

        # Verify session was saved with both LangGraph state and legacy format
        save_call = mock_session_store.set.call_args
        user_id, session_data = save_call[0]

        assert user_id == "test_user"
        assert "langgraph_state" in session_data
        assert "info" in session_data  # Legacy compatibility

        # Check legacy format is populated
        info = session_data["info"]
        assert info.get("origin") is not None
        assert info.get("destination") is not None

    def test_user_session_info(self, langgraph_handler, mock_session_store):
        """Test getting user session info"""
        # Mock session with active conversation
        mock_session_store.get.return_value = {
            "langgraph_state": {
                "origin": "NYC",
                "destination": "London",
                "ready_for_api": True,
                "trip_type": "one_way",
                "passengers": 2,
                "conversation_history": [{"user": "test", "bot": "test"}]
            }
        }

        info = langgraph_handler.get_user_session_info("test_user")

        assert info["status"] == "active_conversation"
        assert info["ready_for_api"] is True
        assert info["origin"] == "NYC"
        assert info["destination"] == "London"
        assert info["conversation_turns"] == 1

    def test_conversation_reset(self, langgraph_handler, mock_session_store):
        """Test resetting user conversation"""
        # Mock existing session
        existing_session = {
            "langgraph_state": {"origin": "NYC"},
            "info": {"destination": "London"},
            "user_preferences": {"preferred_airline": "AA"}
        }
        mock_session_store.get.return_value = existing_session

        success = langgraph_handler.reset_user_conversation("test_user")

        assert success is True

        # Should have saved cleared session but preserved preferences
        save_call = mock_session_store.set.call_args
        _, session_data = save_call[0]

        assert "langgraph_state" not in session_data
        assert session_data["info"] == {}
        assert "user_preferences" in session_data  # Preserved

    def test_error_handling(self, langgraph_handler, mock_session_store):
        """Test error handling in message processing"""
        # Mock session store to raise error
        mock_session_store.get.side_effect = Exception("Redis connection failed")

        response = langgraph_handler.handle_message("test_user", "test message")

        # Should return graceful error message
        assert "technical difficulties" in response.lower()

    def test_conversation_metrics(self, langgraph_handler):
        """Test getting conversation metrics"""
        metrics = langgraph_handler.get_conversation_metrics()

        assert metrics["handler_type"] == "langgraph"
        assert "pipeline_nodes" in metrics
        assert "collect_info" in metrics["pipeline_nodes"]
        assert "search_flights" in metrics["pipeline_nodes"]


class TestMainAppIntegration:
    """Test integration with main FastAPI application"""

    @pytest.fixture
    def mock_app_state(self):
        """Mock application state"""
        state = Mock()

        # Mock LangGraph handler
        state.conversation = Mock()
        state.conversation.handle_message.return_value = "Test response from LangGraph"
        state.conversation.get_user_session_info.return_value = {
            "status": "active_conversation",
            "ready_for_api": True
        }
        state.conversation.reset_user_conversation.return_value = True
        state.conversation.get_conversation_metrics.return_value = {
            "handler_type": "langgraph"
        }

        # Mock other components
        state.user_prefs = Mock()
        state.user_prefs.should_offer_help.return_value = False
        state.user_prefs.get_user_profile.return_value = {"user": "test"}

        state.formatter = Mock()
        state.formatter.format_error_friendly.return_value = "Error message"

        return state

    @patch('main.RequestValidator')
    @patch('main.log_event')
    @patch('main.to_twiml_message')
    def test_webhook_integration(self, mock_twiml, mock_log, mock_validator):
        """Test webhook integration with LangGraph handler"""
        # Mock validation
        mock_validator.validate_whatsapp_message.return_value = (True, None)
        mock_twiml.return_value = "<Response><Message>Test</Message></Response>"

        # Import and create test client
        import main

        # Mock the app state
        with patch.object(main.app, 'state') as mock_state:
            mock_state.conversation = Mock()
            mock_state.conversation.handle_message.return_value = "LangGraph response"
            mock_state.user_prefs = Mock()
            mock_state.user_prefs.should_offer_help.return_value = False
            mock_state.formatter = Mock()

            client = TestClient(main.app)

            response = client.post(
                "/whatsapp/webhook",
                data={
                    "Body": "I need a flight to London",
                    "From": "whatsapp:+1234567890",
                    "To": "whatsapp:+bot"
                }
            )

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/xml; charset=utf-8"

            # Verify LangGraph handler was called
            mock_state.conversation.handle_message.assert_called_once_with(
                user_id="+1234567890",
                message="I need a flight to London"
            )

    def test_admin_endpoints_integration(self):
        """Test admin endpoints work with LangGraph handler"""
        import main

        with patch.object(main.app, 'state') as mock_state:
            mock_state.conversation = Mock()
            mock_state.conversation.get_user_session_info.return_value = {
                "status": "active_conversation"
            }
            mock_state.conversation.reset_user_conversation.return_value = True
            mock_state.conversation.get_conversation_metrics.return_value = {
                "handler_type": "langgraph"
            }
            mock_state.user_prefs = Mock()
            mock_state.user_prefs.get_user_profile.return_value = {"test": "profile"}

            client = TestClient(main.app)

            # Test conversation info endpoint
            response = client.get("/admin/user/test123/conversation")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "active_conversation"

            # Test reset endpoint
            response = client.post("/admin/user/test123/reset")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "reset"

            # Test metrics endpoint
            response = client.get("/admin/langgraph/metrics")
            assert response.status_code == 200
            data = response.json()
            assert data["handler_type"] == "langgraph"

    def test_app_info_updated(self):
        """Test that app info reflects LangGraph integration"""
        import main

        client = TestClient(main.app)
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()

        assert data["version"] == "3.0.0"
        assert "LangGraph state machine" in data["features"]
        assert "Systematic information collection" in data["features"]
        assert "Bulletproof validation gates" in data["features"]


class TestBackwardCompatibility:
    """Test that LangGraph integration maintains backward compatibility"""

    def test_session_format_compatibility(self, mock_session_store, mock_llm, mock_amadeus_client, mock_cache_manager):
        """Test that session format remains compatible with existing systems"""
        handler = LangGraphHandler(
            session_store=mock_session_store,
            llm=mock_llm,
            amadeus_client=mock_amadeus_client,
            cache_manager=mock_cache_manager
        )

        # Simulate handling a message
        mock_session_store.get.return_value = None
        handler.handle_message("test_user", "NYC to London Dec 15")

        # Check that saved session has expected legacy fields
        save_call = mock_session_store.set.call_args
        _, session_data = save_call[0]

        # Legacy fields should exist for compatibility
        assert "info" in session_data
        assert "last_message" in session_data
        assert "last_response" in session_data
        assert "validation_complete" in session_data

    def test_middleware_preservation(self):
        """Test that existing middleware still works"""
        import main

        # Test that middleware is properly applied
        assert hasattr(main, 'ObservabilityMiddleware')
        assert hasattr(main, 'ProductionMiddleware')

        # The middleware should still wrap the app
        client = TestClient(main.app)
        response = client.get("/health")
        assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
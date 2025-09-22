"""
Tests for the ConversationHandler class.

This module contains unit and integration tests for the conversation flow,
ensuring proper state management, entity extraction, and response generation.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, Any
from app.conversation_handler import ConversationHandler, ConversationState
from app.llm.extract_intent import IntentSchema


class TestConversationHandler:
    """Test class for ConversationHandler."""

    @pytest.fixture
    def mock_session_store(self) -> Mock:
        """Fixture for mocking SessionStore."""
        mock_store = Mock()
        mock_store.get.return_value = None  # Simulate no existing session
        return mock_store

    @pytest.fixture
    def mock_amadeus_client(self) -> Mock:
        """Fixture for mocking AmadeusClient."""
        return Mock()

    @pytest.fixture
    def handler(self, mock_session_store: Mock, mock_amadeus_client: Mock) -> ConversationHandler:
        """Fixture for creating a ConversationHandler instance with mocks."""
        return ConversationHandler(
            session_store=mock_session_store,
            amadeus_client=mock_amadeus_client
        )

    def test_init(self, handler: ConversationHandler, mock_session_store: Mock, mock_amadeus_client: Mock) -> None:
        """
        Test initialization of ConversationHandler.

        Verifies that dependencies are correctly assigned.
        """
        assert handler.session_store == mock_session_store
        assert handler.amadeus_client == mock_amadeus_client
        assert handler.intent_parser is not None  # Uses default fast_parse
        assert handler.formatter is None  # Optional

    def test_handle_message_start_state(self, handler: ConversationHandler, mock_session_store: Mock) -> None:
        """
        Test handle_message when in START state.

        Ensures proper greeting and state transition.
        """
        with patch.object(handler, '_extract_entities', return_value={}), \
             patch.object(handler, '_generate_response', return_value="Hello!"):
            response = handler.handle_message("user1", "Hi")
            assert response == "Hello!"
            mock_session_store.set.assert_called_once()
            mock_session_store.touch.assert_called_once_with("user1")

    def test_handle_message_collect_origin(self, handler: ConversationHandler, mock_session_store: Mock) -> None:
        """
        Test handle_message when collecting origin.

        Verifies entity extraction and session update.
        """
        mock_session_store.get.return_value = {"state": ConversationState.START.value, "info": {}}
        with patch.object(handler, '_extract_entities', return_value={"origin": "NYC"}), \
             patch.object(handler, '_generate_response', return_value="Got it!"):
            response = handler.handle_message("user1", "From NYC")
            assert response == "Got it!"
            args, kwargs = mock_session_store.set.call_args
            assert args[1]["state"] == ConversationState.COLLECT_DESTINATION.value
            assert args[1]["info"]["origin"] == "NYC"

    def test_handle_message_confirm_state(self, handler: ConversationHandler, mock_session_store: Mock) -> None:
        """
        Test handle_message when confirming info.

        Checks confirmation logic and transition to DELIVER.
        """
        mock_session_store.get.return_value = {"state": ConversationState.CONFIRM.value, "info": {"origin": "NYC"}}
        with patch.object(handler, '_extract_entities', return_value={}), \
             patch.object(handler, '_generate_response', return_value="Confirmed!"):
            response = handler.handle_message("user1", "yes")
            assert response == "Confirmed!"
            args, kwargs = mock_session_store.set.call_args
            assert args[1]["state"] == ConversationState.DELIVER.value

    def test_handle_message_deliver_state(self, handler: ConversationHandler, mock_session_store: Mock) -> None:
        """
        Test handle_message when delivering results.

        Ensures flight data fetching and formatted response.
        """
        mock_session_store.get.return_value = {"state": ConversationState.DELIVER.value, "info": {"origin": "NYC"}}
        with patch.object(handler, '_extract_entities', return_value={}), \
             patch.object(handler, '_generate_response', return_value="Flights found!"):
            response = handler.handle_message("user1", "show flights")
            assert response == "Flights found!"

    def test_get_session(self, handler: ConversationHandler, mock_session_store: Mock) -> None:
        """
        Test get_session method.

        Verifies retrieval of session data.
        """
        mock_session_store.get.return_value = {"state": "start", "info": {}}
        session = handler.get_session("user1")
        assert session == {"state": "start", "info": {}}
        mock_session_store.get.assert_called_once_with("user1")

    def test_reset_session(self, handler: ConversationHandler, mock_session_store: Mock) -> None:
        """
        Test reset_session method.

        Ensures session is cleared properly.
        """
        handler.reset_session("user1")
        mock_session_store.clear.assert_called_once_with("user1")

    def test_extract_entities_fast_parse(self, handler: ConversationHandler) -> None:
        """
        Test _extract_entities with fast_parse success.

        Checks basic entity extraction from messages.
        """
        with patch('app.conversation_handler.fast_parse') as mock_fast_parse:
            mock_fast_parse.return_value = IntentSchema(origin="NYC", destination="LAX", departure_date="2025-10-10")
            extracted = handler._extract_entities("NYC to LAX on 2025-10-10")
            assert extracted == {
                "origin": "NYC",
                "destination": "LAX",
                "departure_date": "2025-10-10",
                "return_date": None,
                "passengers": 1
            }

    def test_extract_entities_llm_fallback(self, handler: ConversationHandler) -> None:
        """
        Test _extract_entities with LLM fallback.

        Simulates complex message requiring LLM parsing.
        """
        with patch('app.conversation_handler.fast_parse', return_value=None), \
             patch('app.conversation_handler.extract_intent') as mock_extract:
            mock_extract.return_value = IntentSchema(origin="Paris", destination="Tokyo")
            extracted = handler._extract_entities("I want to fly from Paris to Tokyo")
            assert extracted["origin"] == "Paris"
            assert extracted["destination"] == "Tokyo"

    def test_transition_state_start_to_collect_origin(self, handler: ConversationHandler) -> None:
        """
        Test _transition_state from START to COLLECT_ORIGIN.

        Verifies state transition logic.
        """
        session = {"state": ConversationState.START.value, "info": {}}
        extracted = {}
        next_state = handler._transition_state(session, extracted)
        assert next_state == ConversationState.COLLECT_ORIGIN

    def test_transition_state_collect_origin_to_collect_destination(self, handler: ConversationHandler) -> None:
        """
        Test _transition_state with origin provided.

        Ensures progression when origin is extracted.
        """
        session = {"state": ConversationState.COLLECT_ORIGIN.value, "info": {}}
        extracted = {"origin": "NYC"}
        next_state = handler._transition_state(session, extracted)
        assert next_state == ConversationState.COLLECT_DESTINATION

    def test_generate_response_start(self, handler: ConversationHandler) -> None:
        """
        Test _generate_response for START state.

        Ensures natural response generation based on state.
        """
        response = handler._generate_response(ConversationState.START, {})
        assert "Hi! I'm here to help" in response

    def test_generate_response_deliver(self, handler: ConversationHandler) -> None:
        """
        Test _generate_response for DELIVER state.

        Checks response with stubbed flight data.
        """
        session = {"info": {"origin": "NYC", "destination": "LAX", "departure_date": "2025-10-10"}}
        response = handler._generate_response(ConversationState.DELIVER, session)
        assert "Here are your top options:" in response  # From format_reply with stub data

    # Integration test
    def test_full_conversation_flow(self, handler: ConversationHandler, mock_session_store: Mock) -> None:
        """
        Integration test for a full conversation flow.

        Simulates a complete user interaction from start to delivery.
        """
        mock_session_store.get.return_value = None  # Start fresh

        # Step 1: Start
        with patch.object(handler, '_extract_entities', return_value={}), \
             patch.object(handler, '_generate_response', return_value="Hi! Where from?"):
            response = handler.handle_message("user1", "Hi")
            assert response == "Hi! Where from?"

        # Step 2: Collect origin
        mock_session_store.get.return_value = {"state": ConversationState.COLLECT_ORIGIN.value, "info": {}}
        with patch.object(handler, '_extract_entities', return_value={"origin": "NYC"}), \
             patch.object(handler, '_generate_response', return_value="Got NYC!"):
            response = handler.handle_message("user1", "NYC")
            assert response == "Got NYC!"

        # Step 3: Collect destination and dates
        mock_session_store.get.return_value = {"state": ConversationState.COLLECT_DESTINATION.value, "info": {"origin": "NYC"}}
        with patch.object(handler, '_extract_entities', return_value={"destination": "LAX", "departure_date": "2025-10-10"}), \
             patch.object(handler, '_generate_response', return_value="Confirmed!"):
            response = handler.handle_message("user1", "To LAX on 2025-10-10")
            assert response == "Confirmed!"

        # Step 4: Deliver
        mock_session_store.get.return_value = {"state": ConversationState.DELIVER.value, "info": {"origin": "NYC", "destination": "LAX", "departure_date": "2025-10-10"}}
        with patch.object(handler, '_extract_entities', return_value={}), \
             patch.object(handler, '_generate_response', return_value="Flights: AA, UA"):
            response = handler.handle_message("user1", "show flights")
            assert "Flights:" in response

import pytest
from unittest.mock import Mock, patch

from app.conversation.smart_handler import SmartConversationHandler
from app.session.redis_store import RedisSessionStore
from app.amadeus.client import AmadeusClient


@pytest.fixture
def mock_store():
    store = Mock(spec=RedisSessionStore)
    store.get.return_value = None
    store.set.return_value = None
    store.get_cached_search.return_value = None
    store.create_search_key.return_value = "k"
    return store


@pytest.fixture
def mock_amadeus():
    client = Mock(spec=AmadeusClient)
    client.search_flights.return_value = {"data": []}
    return client


def test_preferences_prompt_then_confirmation(mock_store, mock_amadeus):
    handler = SmartConversationHandler(mock_store, mock_amadeus, llm=None, iata_db=None)

    # First message provides all core info
    with patch.object(handler, '_extract_with_confidence') as mock_extract:
        mock_extract.return_value = (
            {"origin": "London", "destination": "Paris", "departure_date": "2025-09-29", "passengers": 2},
            type("C", (), {"scores": {}})()
        )

        resp1 = handler.handle_message("u", "London to Paris next Monday for 2 people")
        # Should offer preferences prompt
        assert "Time window" in resp1 and "Cabin" in resp1

    # Next, user says use defaults -> should ask ready to search
    mock_store.get.return_value = {"info": {"origin": "London", "destination": "Paris", "departure_date": "2025-09-29", "passengers": 2}, "history": [], "stage": "awaiting_preferences", "preferences": {}}
    with patch.object(handler, '_extract_with_confidence') as mock_extract:
        mock_extract.return_value = (
            {"origin": "London", "destination": "Paris", "departure_date": "2025-09-29", "passengers": 2},
            type("C", (), {"scores": {}})()
        )
        resp2 = handler.handle_message("u", "use defaults")
        assert "Ready to search" in resp2 or "proceed" in resp2.lower()

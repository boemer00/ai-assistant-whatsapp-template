import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
from app.conversation.smart_handler import SmartConversationHandler, IntentConfidence
from app.session.redis_store import RedisSessionStore
from app.amadeus.client import AmadeusClient
from langchain_openai import ChatOpenAI


class TestSmartConversationHandler:
    @pytest.fixture
    def mock_redis_store(self):
        store = Mock(spec=RedisSessionStore)
        store.get.return_value = None
        store.set.return_value = None
        store.get_cached_search.return_value = None
        store.create_search_key.return_value = "test_key"
        return store

    @pytest.fixture
    def mock_amadeus(self):
        client = Mock(spec=AmadeusClient)
        client.search_flights.return_value = {
            "data": [
                {
                    "price": {"total": "500.00"},
                    "itineraries": [{"duration": "PT5H30M"}]
                }
            ]
        }
        return client

    @pytest.fixture
    def mock_llm(self):
        return Mock(spec=ChatOpenAI)

    @pytest.fixture
    def handler(self, mock_redis_store, mock_amadeus, mock_llm):
        return SmartConversationHandler(mock_redis_store, mock_amadeus, mock_llm)

    def test_extract_all_info_single_message(self, handler):
        # Test extracting all information from one message
        message = "I want to fly from NYC to London on 2025-12-15 returning 2025-12-22, 2 adults"

        with patch.object(handler, '_extract_with_confidence') as mock_extract:
            mock_extract.return_value = (
                {
                    "origin": "NYC",
                    "destination": "LON",
                    "departure_date": "2025-12-15",
                    "return_date": "2025-12-22",
                    "passengers": 2
                },
                IntentConfidence()
            )

            response = handler.handle_message("user123", message)

            # Should go straight to confirmation since all info is present
            assert "NYC to LON" in response or "confirm" in response.lower()

    def test_handles_corrections(self, handler, mock_redis_store):
        # Setup existing session
        mock_redis_store.get.return_value = {
            "info": {
                "origin": "NYC",
                "destination": "PAR",
                "departure_date": "2025-12-15"
            },
            "history": []
        }

        # Test changing destination
        message = "Actually, change that to London"
        response = handler.handle_message("user123", message)

        assert "LON" in response or "London" in response
        assert "changed" in response.lower() or "updated" in response.lower()

    def test_natural_confirmation_flow(self, handler):
        # Test natural language confirmation
        with patch.object(handler, '_extract_with_confidence') as mock_extract:
            confidence = IntentConfidence()
            confidence.add("origin", "NYC", 0.95)
            confidence.add("destination", "LON", 0.95)
            confidence.add("departure_date", "2025-12-15", 0.7)  # Low confidence

            mock_extract.return_value = (
                {
                    "origin": "NYC",
                    "destination": "LON",
                    "departure_date": "2025-12-15"
                },
                confidence
            )

            response = handler.handle_message("user123", "NYC to London tomorrow")

            # Should ask for confirmation on low confidence field
            assert "2025-12-15" in response or "confirm" in response.lower()

    def test_handles_yes_confirmation(self, handler, mock_redis_store, mock_amadeus):
        # Setup session ready for search
        mock_redis_store.get.return_value = {
            "info": {
                "origin": "NYC",
                "destination": "LON",
                "departure_date": "2025-12-15"
            },
            "history": []
        }

        response = handler.handle_message("user123", "yes")

        # Should execute search
        mock_amadeus.search_flights.assert_called_once()
        assert "flight" in response.lower() or "$" in response

    def test_smart_merge_preserves_existing(self, handler):
        existing = {"origin": "NYC", "destination": "LON"}
        new = {"destination": "PAR", "departure_date": "2025-12-15"}

        merged = handler._smart_merge(existing, new)

        assert merged["origin"] == "NYC"  # Preserved
        assert merged["destination"] == "PAR"  # Updated
        assert merged["departure_date"] == "2025-12-15"  # Added

    def test_missing_fields_prompt(self, handler):
        info = {"origin": "NYC"}
        missing = handler._get_missing_required_fields(info)

        assert "destination" in missing
        assert "departure_date" in missing
        assert "origin" not in missing

    def test_cache_hit_returns_immediately(self, handler, mock_redis_store):
        # Setup cache hit
        cached_results = {
            "results": {"data": [{"price": {"total": "400.00"}}]},
            "cached_at": datetime.now().isoformat()
        }
        mock_redis_store.get_cached_search.return_value = cached_results
        mock_redis_store.get.return_value = {
            "info": {
                "origin": "NYC",
                "destination": "LON",
                "departure_date": "2025-12-15"
            },
            "history": []
        }

        response = handler.handle_message("user123", "yes")

        # Should return cached results
        assert "from recent searches" in response or "$" in response


class TestIntentConfidence:
    def test_confidence_scoring(self):
        confidence = IntentConfidence()
        confidence.add("origin", "NYC", 0.95)
        confidence.add("destination", "LON", 0.7)
        confidence.add("date", "2025-12-15", 0.6)

        # Check which need confirmation
        needs_confirm = confidence.needs_confirmation(threshold=0.8)

        assert "origin" not in needs_confirm  # High confidence
        assert "destination" in needs_confirm  # Low confidence
        assert "date" in needs_confirm  # Low confidence

    def test_get_value(self):
        confidence = IntentConfidence()
        confidence.add("origin", "NYC", 0.95)

        assert confidence.get_value("origin") == "NYC"
        assert confidence.get_value("unknown") is None
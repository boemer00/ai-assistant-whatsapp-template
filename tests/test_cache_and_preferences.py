import pytest
import json
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
from app.cache.flight_cache import FlightCacheManager
from app.user.preferences import UserPreferenceManager
from app.session.redis_store import RedisSessionStore


class TestFlightCacheManager:
    @pytest.fixture
    def mock_redis_store(self):
        store = Mock(spec=RedisSessionStore)
        store.get_cached_search.return_value = None
        store.cache_search.return_value = None
        return store

    @pytest.fixture
    def mock_amadeus(self):
        client = Mock()
        client.search_flights.return_value = {
            "data": [
                {"price": {"total": "500.00"}, "itineraries": [{"duration": "PT5H"}]}
            ]
        }
        return client

    @pytest.fixture
    def cache_manager(self, mock_redis_store, mock_amadeus):
        return FlightCacheManager(mock_redis_store, mock_amadeus)

    def test_cache_key_generation(self, cache_manager):
        key1 = cache_manager.create_cache_key("NYC", "LON", "2025-12-15")
        key2 = cache_manager.create_cache_key("NYC", "LON", "2025-12-15")
        key3 = cache_manager.create_cache_key("NYC", "PAR", "2025-12-15")

        assert key1 == key2  # Same params = same key
        assert key1 != key3  # Different params = different key

    def test_cache_hit_tracking(self, cache_manager, mock_redis_store):
        # Simulate cache hit
        mock_redis_store.get_cached_search.return_value = {
            "results": {"data": []},
            "cached_at": datetime.now().isoformat()
        }

        # First call - cache hit
        cache_manager.redis_store.get_cached_search("key1")
        cache_manager.cache_stats["hits"] += 1

        # Second call - cache miss
        mock_redis_store.get_cached_search.return_value = None
        cache_manager.redis_store.get_cached_search("key2")
        cache_manager.cache_stats["misses"] += 1

        stats = cache_manager.get_cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert "50.0%" in stats["hit_rate"]

    def test_cache_freshness_check(self, cache_manager):
        # Fresh cache
        fresh_data = {
            "results": {"data": []},
            "cached_at": datetime.now().isoformat()
        }
        assert cache_manager._is_cache_fresh(fresh_data, max_age_minutes=60) == True

        # Stale cache
        stale_data = {
            "results": {"data": []},
            "cached_at": (datetime.now() - timedelta(hours=2)).isoformat()
        }
        assert cache_manager._is_cache_fresh(stale_data, max_age_minutes=60) == False

    def test_popular_routes(self, cache_manager):
        routes = cache_manager._get_popular_routes()
        assert len(routes) > 0
        assert ("NYC", "LON") in routes
        assert ("LON", "NYC") in routes

    @pytest.mark.asyncio
    async def test_async_fetch(self, cache_manager, mock_amadeus):
        result = await cache_manager._fetch_async("NYC", "LON", "2025-12-15")
        assert result["data"][0]["price"]["total"] == "500.00"
        mock_amadeus.search_flights.assert_called_once()

    def test_alternative_date_suggestions(self, cache_manager, mock_redis_store):
        # Mock cached data for alternative dates
        def mock_get_cached(key):
            if "12-14" in str(key):
                return {"results": {"data": [{"price": {"total": "450.00"}}]}}
            elif "12-16" in str(key):
                return {"results": {"data": [{"price": {"total": "550.00"}}]}}
            return None

        mock_redis_store.get_cached_search.side_effect = mock_get_cached

        suggestions = cache_manager.suggest_alternative_dates("NYC", "LON", "2025-12-15")

        # Should be sorted by price
        assert len(suggestions) > 0
        if len(suggestions) > 1:
            assert suggestions[0]["price"] <= suggestions[1]["price"]


class TestUserPreferenceManager:
    @pytest.fixture
    def mock_redis_store(self):
        store = Mock()
        store.client = Mock()
        store.client.get.return_value = None
        store.client.setex.return_value = None
        return store

    @pytest.fixture
    def pref_manager(self, mock_redis_store):
        return UserPreferenceManager(mock_redis_store)

    def test_create_default_profile(self, pref_manager):
        profile = pref_manager._create_default_profile("user123")

        assert profile["user_id"] == "user123"
        assert profile["preferences"]["typical_class"] == "ECONOMY"
        assert profile["travel_patterns"]["frequent_routes"] == {}
        assert profile["insights"]["total_searches"] == 0

    def test_update_from_search(self, pref_manager):
        search_params = {
            "origin": "NYC",
            "destination": "LON",
            "departure_date": "2025-12-15"
        }

        profile = pref_manager.update_from_search("user123", search_params, "cheapest")

        assert profile["insights"]["total_searches"] == 1
        assert "NYC-LON" in profile["travel_patterns"]["frequent_routes"]
        assert profile["travel_patterns"]["frequent_routes"]["NYC-LON"] == 1
        assert profile["preferences"]["budget_conscious"] == True
        assert profile["insights"]["price_sensitivity"] == "high"

    def test_infer_preferences_from_selection(self, pref_manager):
        profile = pref_manager._create_default_profile("user123")

        # Test cheapest selection
        pref_manager._infer_preferences(profile, "cheapest")
        assert profile["preferences"]["budget_conscious"] == True
        assert profile["insights"]["price_sensitivity"] == "high"

        # Test fastest selection
        pref_manager._infer_preferences(profile, "fastest")
        assert profile["preferences"]["budget_conscious"] == False
        assert profile["insights"]["price_sensitivity"] == "low"

    def test_calculate_travel_patterns(self, pref_manager):
        profile = pref_manager._create_default_profile("user123")

        # Add search history
        for i in range(5):
            search = {
                "timestamp": datetime.now().isoformat(),
                "params": {
                    "departure_date": (datetime.now() + timedelta(days=14)).isoformat(),
                    "return_date": (datetime.now() + timedelta(days=21)).isoformat()
                }
            }
            profile["history"]["searches"].append(search)

        pref_manager._calculate_travel_patterns(profile)

        assert profile["travel_patterns"]["advance_booking_days"] is not None
        assert profile["travel_patterns"]["typical_trip_length"] == 7

    def test_personalized_suggestions(self, pref_manager):
        profile = pref_manager._create_default_profile("user123")
        profile["travel_patterns"]["frequent_routes"]["NYC-LON"] = 5
        profile["insights"]["price_sensitivity"] = "high"

        # Mock the get_user_profile to return our profile
        with patch.object(pref_manager, 'get_user_profile', return_value=profile):
            suggestions = pref_manager.get_personalized_suggestions("user123")

            assert len(suggestions) > 0
            assert any("NYC to LON" in s for s in suggestions)
            assert any("affordable" in s.lower() for s in suggestions)

    def test_quick_actions(self, pref_manager):
        profile = pref_manager._create_default_profile("user123")
        profile["travel_patterns"]["frequent_routes"]["NYC-LON"] = 3
        profile["history"]["searches"].append({
            "params": {"origin": "NYC", "destination": "LON"}
        })

        with patch.object(pref_manager, 'get_user_profile', return_value=profile):
            actions = pref_manager.get_quick_actions("user123")

            assert len(actions) > 0
            assert any(a["type"] == "route" for a in actions)
            assert any("NYC" in a["command"] for a in actions)

    def test_should_offer_help(self, pref_manager):
        # New user
        profile_new = pref_manager._create_default_profile("new_user")
        with patch.object(pref_manager, 'get_user_profile', return_value=profile_new):
            assert pref_manager.should_offer_help("new_user") == True

        # Returning user
        profile_returning = pref_manager._create_default_profile("old_user")
        profile_returning["insights"]["total_searches"] = 10
        profile_returning["insights"]["last_active"] = datetime.now().isoformat()
        with patch.object(pref_manager, 'get_user_profile', return_value=profile_returning):
            assert pref_manager.should_offer_help("old_user") == False

        # Inactive user
        profile_inactive = pref_manager._create_default_profile("inactive_user")
        profile_inactive["insights"]["total_searches"] = 10
        profile_inactive["insights"]["last_active"] = (datetime.now() - timedelta(days=45)).isoformat()
        with patch.object(pref_manager, 'get_user_profile', return_value=profile_inactive):
            assert pref_manager.should_offer_help("inactive_user") == True
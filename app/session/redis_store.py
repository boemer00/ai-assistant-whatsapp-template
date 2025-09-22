import json
import redis
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
from app.config import settings


class RedisSessionStore:
    def __init__(self, redis_url: str = None, ttl_seconds: int = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self.ttl_seconds = ttl_seconds or settings.REDIS_TTL_SECONDS
        self.client = redis.from_url(self.redis_url, decode_responses=True)
        self.prefix = "session:"

        # Test connection
        try:
            self.client.ping()
        except redis.ConnectionError:
            # Fall back to in-memory if Redis is not available
            self.client = None
            self._fallback_store = {}
            print("[WARNING] Redis not available, falling back to in-memory storage")

    def _get_key(self, user_id: str) -> str:
        return f"{self.prefix}{user_id}"

    def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        print(f"[DEBUG] RedisStore.get() called for user_id: {user_id}")
        if self.client is None:
            print(f"[DEBUG] Using fallback store")
            result = self._fallback_store.get(user_id)
            print(f"[DEBUG] Fallback store result: {result}")
            return result

        key = self._get_key(user_id)
        print(f"[DEBUG] Redis key: {key}")
        try:
            data = self.client.get(key)
            print(f"[DEBUG] Raw Redis data: {data}")
            if data:
                result = json.loads(data)
                print(f"[DEBUG] Parsed Redis result: {result}")
                return result
            print(f"[DEBUG] No data found in Redis for key: {key}")
            return None
        except Exception as e:
            print(f"[DEBUG] Redis get error: {e}")
            return None

    def set(self, user_id: str, session_data: Dict[str, Any]) -> None:
        print(f"[DEBUG] RedisStore.set() called for user_id: {user_id}")
        print(f"[DEBUG] Session data to save: {session_data}")

        if self.client is None:
            print(f"[DEBUG] Using fallback store for saving")
            self._fallback_store[user_id] = session_data
            print(f"[DEBUG] Saved to fallback store")
            return

        key = self._get_key(user_id)
        print(f"[DEBUG] Redis key for save: {key}")
        try:
            data = json.dumps(session_data)
            print(f"[DEBUG] Serialized data: {data}")
            result = self.client.setex(key, self.ttl_seconds, data)
            print(f"[DEBUG] Redis setex result: {result}")
        except Exception as e:
            print(f"[DEBUG] Redis set error: {e}")
            # Fallback to in-memory
            self._fallback_store[user_id] = session_data
            print(f"[DEBUG] Fell back to in-memory store due to Redis error")

    def touch(self, user_id: str) -> None:
        if self.client is None:
            # In-memory fallback doesn't need touch
            return

        key = self._get_key(user_id)
        self.client.expire(key, self.ttl_seconds)

    def clear(self, user_id: str) -> None:
        if self.client is None:
            self._fallback_store.pop(user_id, None)
            return

        key = self._get_key(user_id)
        self.client.delete(key)

    def exists(self, user_id: str) -> bool:
        if self.client is None:
            return user_id in self._fallback_store

        key = self._get_key(user_id)
        return bool(self.client.exists(key))

    def get_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        if self.client is None:
            return self._fallback_store.copy()

        sessions = {}
        for key in self.client.scan_iter(f"{self.prefix}*"):
            user_id = key.replace(self.prefix, "")
            data = self.client.get(key)
            if data:
                sessions[user_id] = json.loads(data)
        return sessions

    def cleanup_expired(self) -> int:
        # Redis automatically handles expiration
        # This method is for compatibility with the interface
        return 0

    # Cache methods for flight searches
    def cache_search(self, search_key: str, results: Any, ttl: int = None) -> None:
        if self.client is None:
            return

        ttl = ttl or settings.REDIS_CACHE_TTL_SECONDS
        cache_key = f"flight:{search_key}"
        data = json.dumps(results)
        self.client.setex(cache_key, ttl, data)

    def get_cached_search(self, search_key: str) -> Optional[Any]:
        if self.client is None:
            return None

        cache_key = f"flight:{search_key}"
        data = self.client.get(cache_key)
        if data:
            return json.loads(data)
        return None

    def create_search_key(self, origin: str, destination: str, dep_date: str,
                         ret_date: str = None, adults: int = 1) -> str:
        parts = [origin, destination, dep_date]
        if ret_date:
            parts.append(ret_date)
        parts.append(str(adults))
        return ":".join(parts)
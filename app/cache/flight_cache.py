import json
import hashlib
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta
import asyncio
from app.session.redis_store import RedisSessionStore
from app.amadeus.client import AmadeusClient


class FlightCacheManager:
    def __init__(self, redis_store: RedisSessionStore, amadeus_client: AmadeusClient):
        self.redis_store = redis_store
        self.amadeus_client = amadeus_client
        self.popular_routes = self._get_popular_routes()
        self.cache_stats = {"hits": 0, "misses": 0}

    def _get_popular_routes(self) -> List[Tuple[str, str]]:
        # Most popular routes for pre-warming
        return [
            ("NYC", "LON"), ("LON", "NYC"),  # NYC-London
            ("NYC", "LAX"), ("LAX", "NYC"),  # NYC-LA
            ("SFO", "NYC"), ("NYC", "SFO"),  # SF-NYC
            ("LON", "PAR"), ("PAR", "LON"),  # London-Paris
            ("NYC", "MIA"), ("MIA", "NYC"),  # NYC-Miami
            ("LAX", "SFO"), ("SFO", "LAX"),  # LA-SF
            ("NYC", "BOS"), ("BOS", "NYC"),  # NYC-Boston
            ("CHI", "NYC"), ("NYC", "CHI"),  # Chicago-NYC
            ("LON", "DUB"), ("DUB", "LON"),  # London-Dublin
            ("NYC", "TOR"), ("TOR", "NYC"),  # NYC-Toronto
        ]

    def create_cache_key(self, origin: str, destination: str, dep_date: str,
                        ret_date: str = None, adults: int = 1,
                        cabin_class: str = "ECONOMY") -> str:
        # Create deterministic cache key
        parts = [
            origin.upper(),
            destination.upper(),
            dep_date,
            ret_date or "ONEWAY",
            str(adults),
            cabin_class
        ]
        key_str = "|".join(parts)
        # Create shorter hash for Redis key
        return hashlib.md5(key_str.encode()).hexdigest()

    async def get_cached_or_fetch(self, origin: str, destination: str,
                                  dep_date: str, ret_date: str = None,
                                  adults: int = 1) -> Optional[Dict]:
        cache_key = self.create_cache_key(origin, destination, dep_date, ret_date, adults)

        # Try cache first
        cached = self.redis_store.get_cached_search(cache_key)
        if cached:
            self.cache_stats["hits"] += 1
            # Check if cache is still fresh (within last hour)
            if self._is_cache_fresh(cached):
                return cached

        # Cache miss or stale
        self.cache_stats["misses"] += 1

        # Fetch from Amadeus
        try:
            results = await self._fetch_async(origin, destination, dep_date, ret_date, adults)
            # Cache the results
            self.cache_results(cache_key, results)
            return results
        except Exception as e:
            # If fetch fails, return stale cache if available
            if cached:
                return cached
            raise e

    async def _fetch_async(self, origin: str, destination: str,
                          dep_date: str, ret_date: str = None,
                          adults: int = 1) -> Dict:
        # Wrapper for async fetch (to be used with background tasks)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.amadeus_client.search_flights,
            origin, destination, dep_date, ret_date, adults
        )

    def cache_results(self, cache_key: str, results: Dict, ttl: int = 3600) -> None:
        # Add metadata for cache management
        cache_data = {
            "results": results,
            "cached_at": datetime.now().isoformat(),
            "ttl": ttl
        }
        self.redis_store.cache_search(cache_key, cache_data, ttl)

    def _is_cache_fresh(self, cached_data: Dict, max_age_minutes: int = 60) -> bool:
        if not isinstance(cached_data, dict) or "cached_at" not in cached_data:
            return True  # Assume fresh if no metadata

        cached_time = datetime.fromisoformat(cached_data["cached_at"])
        age = datetime.now() - cached_time
        return age < timedelta(minutes=max_age_minutes)

    async def warm_popular_routes(self, days_ahead: int = 7):
        # Pre-warm cache with popular routes
        base_date = datetime.now()
        tasks = []

        for origin, destination in self.popular_routes:
            for day_offset in range(days_ahead):
                dep_date = (base_date + timedelta(days=day_offset)).strftime("%Y-%m-%d")
                tasks.append(self._warm_single_route(origin, destination, dep_date))

        # Limit concurrent warming to avoid overwhelming the API
        semaphore = asyncio.Semaphore(3)
        async def limited_warm(task):
            async with semaphore:
                return await task

        results = await asyncio.gather(*[limited_warm(task) for task in tasks],
                                      return_exceptions=True)

        successful = sum(1 for r in results if not isinstance(r, Exception))
        print(f"[Cache] Warmed {successful}/{len(tasks)} routes")

    async def _warm_single_route(self, origin: str, destination: str, dep_date: str):
        try:
            await self.get_cached_or_fetch(origin, destination, dep_date)
            return True
        except Exception as e:
            print(f"[Cache] Failed to warm {origin}-{destination} on {dep_date}: {e}")
            return False

    def invalidate_route(self, origin: str, destination: str):
        # Invalidate all cached entries for a specific route
        # Useful when prices change significantly
        pattern = f"{origin.upper()}|{destination.upper()}|*"
        # This would need Redis SCAN implementation
        pass

    def get_cache_stats(self) -> Dict:
        total = self.cache_stats["hits"] + self.cache_stats["misses"]
        if total == 0:
            hit_rate = 0
        else:
            hit_rate = self.cache_stats["hits"] / total * 100

        return {
            "hits": self.cache_stats["hits"],
            "misses": self.cache_stats["misses"],
            "hit_rate": f"{hit_rate:.1f}%",
            "popular_routes": len(self.popular_routes)
        }

    def suggest_alternative_dates(self, origin: str, destination: str,
                                  dep_date: str, adults: int = 1) -> List[Dict]:
        # Check cache for nearby dates and suggest cheaper options
        suggestions = []
        base_date = datetime.fromisoformat(dep_date)

        for day_offset in [-3, -2, -1, 1, 2, 3]:
            alt_date = (base_date + timedelta(days=day_offset)).strftime("%Y-%m-%d")
            cache_key = self.create_cache_key(origin, destination, alt_date, adults=adults)
            cached = self.redis_store.get_cached_search(cache_key)

            if cached and "results" in cached:
                # Extract price from cached results
                try:
                    results = cached["results"]
                    if results and "data" in results and results["data"]:
                        price = results["data"][0]["price"]["total"]
                        suggestions.append({
                            "date": alt_date,
                            "price": price,
                            "savings": None  # Will be calculated later
                        })
                except:
                    pass

        return sorted(suggestions, key=lambda x: x["price"]) if suggestions else []
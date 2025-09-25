"""
Amadeus API Search Tool for LangGraph Travel Assistant

Structured integration with Amadeus API that only executes with validated parameters
and integrates with existing caching infrastructure for optimal performance.
"""

from typing import Dict, Any, Optional, List
from pydantic import BaseModel
from datetime import datetime
import traceback

from app.langgraph.state import TravelState
from app.amadeus.client import AmadeusClient
from app.cache.flight_cache import FlightCacheManager


class SearchParams(BaseModel):
    """Validated search parameters for Amadeus API"""
    origin: str
    destination: str
    departure_date: str
    return_date: Optional[str] = None
    passengers: int
    trip_type: str  # "one_way" or "round_trip"


class SearchResult(BaseModel):
    """Result of flight search operation"""
    success: bool
    results: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    cached: bool = False
    cache_key: Optional[str] = None
    search_duration_ms: Optional[int] = None


class AmadeusSearchTool:
    """Execute validated flight search with caching integration"""

    def __init__(self, amadeus_client: AmadeusClient, cache_manager: Optional[FlightCacheManager] = None):
        self.amadeus_client = amadeus_client
        self.cache_manager = cache_manager

    def search(self, state: TravelState) -> SearchResult:
        """Execute flight search with validated state"""
        print(f"[DEBUG] AmadeusSearchTool.search() called")

        # Critical: Verify state is ready for API
        if not state.get("ready_for_api", False):
            error_msg = "CRITICAL: API call attempted with unvalidated state"
            print(f"[ERROR] {error_msg}")
            return SearchResult(
                success=False,
                error="Internal validation error - search blocked",
                cached=False
            )

        # Extract and validate search parameters
        try:
            params = self._extract_search_params(state)
            print(f"[DEBUG] Search parameters extracted: {params}")
        except Exception as e:
            print(f"[ERROR] Parameter extraction failed: {e}")
            return SearchResult(
                success=False,
                error=f"Parameter extraction failed: {str(e)}",
                cached=False
            )

        # Check cache first if available
        if self.cache_manager:
            cache_result = self._check_cache(params)
            if cache_result:
                print(f"[DEBUG] Cache HIT - returning cached results")
                return cache_result

        # Execute Amadeus API search
        start_time = datetime.now()
        try:
            print(f"[DEBUG] Executing Amadeus API search...")

            results = self.amadeus_client.search_flights(
                origin=params.origin,
                destination=params.destination,
                dep_date=params.departure_date,
                ret_date=params.return_date,
                adults=params.passengers
            )

            end_time = datetime.now()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            print(f"[DEBUG] Amadeus API search completed in {duration_ms}ms")

            # Cache the results if cache manager available
            cache_key = None
            if self.cache_manager:
                cache_key = self._cache_results(params, results)

            return SearchResult(
                success=True,
                results=results,
                cached=False,
                cache_key=cache_key,
                search_duration_ms=duration_ms
            )

        except Exception as e:
            error_msg = f"Amadeus API search failed: {str(e)}"
            print(f"[ERROR] {error_msg}")
            print(f"[ERROR] Full traceback: {traceback.format_exc()}")

            return SearchResult(
                success=False,
                error=error_msg,
                cached=False
            )

    def _extract_search_params(self, state: TravelState) -> SearchParams:
        """Extract and validate search parameters from state"""

        # All these should be validated by the validation node
        origin = state.get("origin")
        destination = state.get("destination")
        departure_date = state.get("departure_date")
        passengers = state.get("passengers", 1)
        trip_type = state.get("trip_type", "one_way")
        return_date = state.get("return_date") if trip_type == "round_trip" else None

        if not origin or not destination or not departure_date:
            raise ValueError("Missing required search parameters")

        # Resolve airport codes if needed
        origin_code = self._resolve_airport_code(origin)
        destination_code = self._resolve_airport_code(destination)

        return SearchParams(
            origin=origin_code,
            destination=destination_code,
            departure_date=departure_date,
            return_date=return_date,
            passengers=int(passengers),
            trip_type=trip_type
        )

    def _resolve_airport_code(self, location: str) -> str:
        """Resolve location to airport code if needed"""
        # Simple resolution - in production you'd use IATA database
        location_upper = str(location).upper().strip()

        # If already looks like airport code, return as-is
        if len(location_upper) == 3 and location_upper.isalpha():
            return location_upper

        # Simple city mappings for common cases
        city_mappings = {
            "NEW YORK": "JFK",
            "NYC": "JFK",
            "LONDON": "LHR",
            "LON": "LHR",
            "PARIS": "CDG",
            "PAR": "CDG",
            "LOS ANGELES": "LAX",
            "LA": "LAX",
            "TOKYO": "NRT",
            "CHICAGO": "ORD",
            "MIAMI": "MIA",
            "BOSTON": "BOS",
            "SAN FRANCISCO": "SFO",
            "WASHINGTON": "DCA",
            "ATLANTA": "ATL"
        }

        resolved = city_mappings.get(location_upper, location_upper)
        print(f"[DEBUG] Resolved '{location}' to '{resolved}'")
        return resolved

    def _check_cache(self, params: SearchParams) -> Optional[SearchResult]:
        """Check cache for existing search results"""
        if not self.cache_manager:
            return None

        try:
            cache_key = self._create_cache_key(params)
            cached_results = self.cache_manager.get_cached_results(cache_key)

            if cached_results:
                print(f"[DEBUG] Found cached results for key: {cache_key}")
                return SearchResult(
                    success=True,
                    results=cached_results,
                    cached=True,
                    cache_key=cache_key
                )
        except Exception as e:
            print(f"[WARNING] Cache check failed: {e}")

        return None

    def _cache_results(self, params: SearchParams, results: Dict[str, Any]) -> Optional[str]:
        """Cache search results for future use"""
        if not self.cache_manager:
            return None

        try:
            cache_key = self._create_cache_key(params)
            self.cache_manager.cache_results(cache_key, results)
            print(f"[DEBUG] Cached results with key: {cache_key}")
            return cache_key
        except Exception as e:
            print(f"[WARNING] Caching failed: {e}")
            return None

    def _create_cache_key(self, params: SearchParams) -> str:
        """Create cache key for search parameters"""
        key_parts = [
            params.origin,
            params.destination,
            params.departure_date,
            params.return_date or "ONEWAY",
            str(params.passengers)
        ]
        return "|".join(key_parts)


# Helper function to create search tool
def create_amadeus_search_tool(amadeus_client: AmadeusClient,
                              cache_manager: Optional[FlightCacheManager] = None) -> AmadeusSearchTool:
    """Create Amadeus search tool with optional caching"""
    return AmadeusSearchTool(amadeus_client, cache_manager)
import asyncio
import json
from typing import Dict, Optional, Any
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import httpx
from app.session.redis_store import RedisSessionStore
from app.amadeus.client import AmadeusClient
from app.cache.flight_cache import FlightCacheManager
from app.formatters.enhanced_whatsapp import NaturalFormatter


class AsyncFlightSearchHandler:
    def __init__(
        self,
        redis_store: RedisSessionStore,
        amadeus_client: AmadeusClient,
        twilio_config: Dict
    ):
        self.redis_store = redis_store
        self.amadeus_client = amadeus_client
        self.cache_manager = FlightCacheManager(redis_store, amadeus_client)
        self.formatter = NaturalFormatter()
        self.twilio_config = twilio_config
        self.executor = ThreadPoolExecutor(max_workers=5)

    async def search_and_respond(self, user_id: str, phone_number: str, search_params: Dict):
        # Send immediate acknowledgment
        await self._send_whatsapp_message(
            phone_number,
            self.formatter.format_searching_message()
        )

        try:
            # Check cache first
            cache_key = self.cache_manager.create_cache_key(
                search_params["origin"],
                search_params["destination"],
                search_params["departure_date"],
                search_params.get("return_date"),
                search_params.get("passengers", 1)
            )

            cached_results = self.redis_store.get_cached_search(cache_key)
            if cached_results:
                # Send cached results immediately
                response = self._format_flight_results(cached_results, search_params, from_cache=True)
                await self._send_whatsapp_message(phone_number, response)
                return

            # Fetch from Amadeus in background
            results = await self._fetch_flights_async(search_params)

            # Cache the results
            self.cache_manager.cache_results(cache_key, results)

            # Format and send results
            response = self._format_flight_results(results, search_params)
            await self._send_whatsapp_message(phone_number, response)

            # Update session with search history
            self._update_search_history(user_id, search_params, results)

        except asyncio.TimeoutError:
            await self._send_whatsapp_message(
                phone_number,
                self.formatter.format_error_friendly("timeout")
            )
        except Exception as e:
            print(f"[ERROR] Search failed for {user_id}: {e}")
            await self._send_whatsapp_message(
                phone_number,
                self.formatter.format_error_friendly("api_error")
            )

    async def _fetch_flights_async(self, params: Dict, timeout: int = 10) -> Dict:
        loop = asyncio.get_event_loop()

        # Run the blocking Amadeus call in executor
        future = loop.run_in_executor(
            self.executor,
            self.amadeus_client.search_flights,
            params["origin"],
            params["destination"],
            params["departure_date"],
            params.get("return_date"),
            params.get("passengers", 1)
        )

        # Apply timeout
        try:
            results = await asyncio.wait_for(future, timeout=timeout)
            return results
        except asyncio.TimeoutError:
            print(f"[WARNING] Amadeus search timed out after {timeout}s")
            raise

    def _format_flight_results(self, results: Dict, search_params: Dict,
                               from_cache: bool = False) -> str:
        from app.amadeus.transform import from_amadeus
        from app.rank.selector import rank_top

        # Transform Amadeus response
        options = from_amadeus(results if not from_cache else results.get("results", results))
        ranked = rank_top(options)

        # Convert to dict for formatter
        results_dict = {
            "fastest": ranked.fastest.__dict__ if ranked.fastest else None,
            "cheapest": ranked.cheapest.__dict__ if ranked.cheapest else None,
            "best_overall": ranked.best_overall.__dict__ if ranked.best_overall else None,
        }

        if ranked.fastest and ranked.cheapest:
            price_diff = ranked.fastest.price - ranked.cheapest.price
            time_diff = ranked.cheapest.duration_minutes - ranked.fastest.duration_minutes
            results_dict["price_difference"] = price_diff
            results_dict["time_saved"] = f"{time_diff // 60}h {time_diff % 60}m"

        return self.formatter.format_results_conversational(results_dict, from_cache)

    async def _send_whatsapp_message(self, to_number: str, message: str) -> bool:
        # Send WhatsApp message via Twilio API
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_config['account_sid']}/Messages.json",
                    auth=(self.twilio_config['account_sid'], self.twilio_config['auth_token']),
                    data={
                        'From': f"whatsapp:{self.twilio_config['whatsapp_number']}",
                        'To': f"whatsapp:{to_number}",
                        'Body': message
                    }
                )
                return response.status_code == 201
        except Exception as e:
            print(f"[ERROR] Failed to send WhatsApp message: {e}")
            return False

    def _update_search_history(self, user_id: str, search_params: Dict, results: Dict):
        session = self.redis_store.get(user_id) or {}
        history = session.get("search_history", [])

        # Add to history
        history.append({
            "timestamp": datetime.now().isoformat(),
            "params": search_params,
            "results_count": len(results.get("data", [])) if results else 0
        })

        # Keep only last 10 searches
        session["search_history"] = history[-10:]
        session["last_search"] = search_params

        self.redis_store.set(user_id, session)


class BackgroundTaskManager:
    def __init__(self):
        self.tasks = {}
        self.completed_tasks = {}

    def create_task(self, task_id: str, coroutine) -> str:
        task = asyncio.create_task(coroutine)
        self.tasks[task_id] = task

        # Clean up when done
        task.add_done_callback(lambda t: self._task_done(task_id, t))
        return task_id

    def _task_done(self, task_id: str, task: asyncio.Task):
        if task_id in self.tasks:
            del self.tasks[task_id]
            self.completed_tasks[task_id] = {
                "completed_at": datetime.now().isoformat(),
                "exception": str(task.exception()) if task.exception() else None
            }

    def get_task_status(self, task_id: str) -> Dict:
        if task_id in self.tasks:
            task = self.tasks[task_id]
            return {
                "status": "running",
                "done": task.done(),
                "cancelled": task.cancelled()
            }
        elif task_id in self.completed_tasks:
            return {
                "status": "completed",
                **self.completed_tasks[task_id]
            }
        else:
            return {"status": "not_found"}

    async def cancel_task(self, task_id: str) -> bool:
        if task_id in self.tasks:
            self.tasks[task_id].cancel()
            return True
        return False
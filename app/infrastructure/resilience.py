import asyncio
import time
from typing import Dict, Optional, Callable, Any
from datetime import datetime, timedelta
from collections import defaultdict, deque
from enum import Enum
import redis


class CircuitState(Enum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type = Exception
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED

    def call(self, func: Callable, *args, **kwargs) -> Any:
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
            else:
                raise Exception(f"Circuit breaker {self.name} is OPEN")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise e

    async def async_call(self, func: Callable, *args, **kwargs) -> Any:
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
            else:
                raise Exception(f"Circuit breaker {self.name} is OPEN")

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise e

    def _on_success(self):
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN

    def _should_attempt_reset(self) -> bool:
        return (
            self.last_failure_time and
            time.time() - self.last_failure_time >= self.recovery_timeout
        )

    def get_state(self) -> Dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "last_failure": self.last_failure_time
        }


class RateLimiter:
    def __init__(self, redis_client: redis.Redis = None):
        self.redis_client = redis_client
        self.local_cache = defaultdict(lambda: deque(maxlen=100))

    def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int
    ) -> tuple[bool, Dict]:
        if self.redis_client:
            return self._check_redis_rate_limit(key, max_requests, window_seconds)
        return self._check_local_rate_limit(key, max_requests, window_seconds)

    def _check_redis_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int
    ) -> tuple[bool, Dict]:
        redis_key = f"rate_limit:{key}"
        now = time.time()
        pipeline = self.redis_client.pipeline()

        # Remove old entries
        pipeline.zremrangebyscore(redis_key, 0, now - window_seconds)
        # Add current request
        pipeline.zadd(redis_key, {str(now): now})
        # Count requests in window
        pipeline.zcard(redis_key)
        # Set expiry
        pipeline.expire(redis_key, window_seconds + 1)

        results = pipeline.execute()
        request_count = results[2]

        allowed = request_count <= max_requests
        return allowed, {
            "allowed": allowed,
            "current": request_count,
            "limit": max_requests,
            "window_seconds": window_seconds,
            "retry_after": window_seconds if not allowed else None
        }

    def _check_local_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int
    ) -> tuple[bool, Dict]:
        now = time.time()
        request_times = self.local_cache[key]

        # Remove old requests outside window
        cutoff = now - window_seconds
        while request_times and request_times[0] < cutoff:
            request_times.popleft()

        # Check if under limit
        if len(request_times) < max_requests:
            request_times.append(now)
            return True, {
                "allowed": True,
                "current": len(request_times),
                "limit": max_requests,
                "window_seconds": window_seconds
            }

        return False, {
            "allowed": False,
            "current": len(request_times),
            "limit": max_requests,
            "window_seconds": window_seconds,
            "retry_after": window_seconds
        }


class HealthChecker:
    def __init__(self):
        self.checks = {}
        self.last_check_time = {}
        self.check_results = {}

    def register_check(self, name: str, check_func: Callable, interval_seconds: int = 30):
        self.checks[name] = {
            "func": check_func,
            "interval": interval_seconds
        }

    async def run_checks(self) -> Dict:
        results = {}
        tasks = []

        for name, check_info in self.checks.items():
            # Check if we should run this check
            last_time = self.last_check_time.get(name, 0)
            if time.time() - last_time >= check_info["interval"]:
                tasks.append(self._run_single_check(name, check_info["func"]))

        if tasks:
            check_results = await asyncio.gather(*tasks, return_exceptions=True)
            for name, result in check_results:
                results[name] = result
                self.check_results[name] = result
                self.last_check_time[name] = time.time()

        # Include cached results for checks not run this time
        for name in self.checks:
            if name not in results:
                results[name] = self.check_results.get(name, {"status": "unknown"})

        # Overall status
        all_healthy = all(
            r.get("status") == "healthy"
            for r in results.values()
            if r.get("status") != "unknown"
        )

        return {
            "status": "healthy" if all_healthy else "unhealthy",
            "checks": results,
            "timestamp": datetime.now().isoformat()
        }

    async def _run_single_check(self, name: str, check_func: Callable) -> tuple[str, Dict]:
        try:
            start = time.time()
            if asyncio.iscoroutinefunction(check_func):
                result = await check_func()
            else:
                result = check_func()

            duration = time.time() - start
            return name, {
                "status": "healthy" if result else "unhealthy",
                "duration_ms": int(duration * 1000),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return name, {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }


class RetryPolicy:
    def __init__(
        self,
        max_attempts: int = 3,
        backoff_base: float = 2.0,
        max_delay: int = 60
    ):
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.max_delay = max_delay

    async def execute_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        last_exception = None

        for attempt in range(self.max_attempts):
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < self.max_attempts - 1:
                    delay = min(
                        self.backoff_base ** attempt,
                        self.max_delay
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        raise last_exception


class RequestValidator:
    @staticmethod
    def validate_whatsapp_message(data: Dict) -> tuple[bool, Optional[str]]:
        required_fields = ["Body", "From", "To"]
        for field in required_fields:
            if field not in data:
                return False, f"Missing required field: {field}"

        # Validate phone number format
        from_number = data["From"]
        if not from_number.startswith("whatsapp:"):
            return False, "Invalid From number format"

        # Validate message length
        body = data["Body"]
        if len(body) > 4096:
            return False, "Message too long"

        return True, None

    @staticmethod
    def validate_search_params(params: Dict) -> tuple[bool, Optional[str]]:
        required = ["origin", "destination", "departure_date"]
        for field in required:
            if field not in params or not params[field]:
                return False, f"Missing required field: {field}"

        # Validate date format
        try:
            datetime.fromisoformat(params["departure_date"])
            if "return_date" in params and params["return_date"]:
                datetime.fromisoformat(params["return_date"])
        except ValueError:
            return False, "Invalid date format"

        # Validate passenger count
        passengers = params.get("passengers", 1)
        if not isinstance(passengers, int) or passengers < 1 or passengers > 9:
            return False, "Invalid passenger count"

        return True, None


class ProductionMiddleware:
    def __init__(self, app, redis_client: redis.Redis = None):
        self.app = app
        self.rate_limiter = RateLimiter(redis_client)
        self.health_checker = HealthChecker()
        self.circuit_breakers = {}

        # Register health checks
        self._register_health_checks()

    def _register_health_checks(self):
        # Redis health check
        def check_redis():
            try:
                if self.rate_limiter.redis_client:
                    self.rate_limiter.redis_client.ping()
                    return True
                return True  # If no Redis, consider it "healthy"
            except:
                return False

        self.health_checker.register_check("redis", check_redis, 30)

        # Add more health checks as needed

    def add_circuit_breaker(self, name: str, **kwargs):
        self.circuit_breakers[name] = CircuitBreaker(name, **kwargs)

    def get_circuit_breaker(self, name: str) -> Optional[CircuitBreaker]:
        return self.circuit_breakers.get(name)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope["path"]

            # Health check endpoint
            if path == "/health/detailed":
                health_status = await self.health_checker.run_checks()
                await self._send_json_response(send, health_status)
                return

            # Apply rate limiting to webhook
            if path == "/whatsapp/webhook":
                # Extract identifier (could be IP or phone number)
                client_ip = scope.get("client", ["unknown", None])[0]
                allowed, limit_info = self.rate_limiter.check_rate_limit(
                    f"ip:{client_ip}",
                    max_requests=60,  # 60 requests per minute
                    window_seconds=60
                )

                if not allowed:
                    await self._send_rate_limit_response(send, limit_info)
                    return

        await self.app(scope, receive, send)

    async def _send_json_response(self, send, data: Dict, status: int = 200):
        import json
        body = json.dumps(data).encode()
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [[b"content-type", b"application/json"]],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })

    async def _send_rate_limit_response(self, send, limit_info: Dict):
        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": [
                [b"content-type", b"application/json"],
                [b"retry-after", str(limit_info["retry_after"]).encode()],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"error": "Rate limit exceeded"}',
        })
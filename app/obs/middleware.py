"""ASGI middleware for lightweight observability."""

from typing import Callable, Any
import time
import uuid

from fastapi import FastAPI

from app.obs.context import request_id_var
from app.obs.logger import log_event
from app.obs.metrics import record_timing, inc_counter


class ObservabilityMiddleware:
    def __init__(self, app: FastAPI):
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable[[dict], Any]):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        req_id = str(uuid.uuid4())
        request_id_var.set(req_id)
        method = scope.get("method", "")
        path = scope.get("path", "")
        route = path
        start = time.monotonic()
        status_code = 500

        async def send_wrapper(message: dict):
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 200))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            record_timing("request_latency_ms", elapsed_ms, {"route": route})
            inc_counter("requests_total", {"route": route, "status": str(status_code)})
            log_event(
                "request",
                method=method,
                route=route,
                status=status_code,
                ms_total=round(elapsed_ms, 2),
            )

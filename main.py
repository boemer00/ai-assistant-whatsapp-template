import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Form, Request, BackgroundTasks, HTTPException
from fastapi.responses import PlainTextResponse, Response, JSONResponse
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from app.config import settings
from app.iata.lookup import IATADb
from app.amadeus.client import AmadeusClient

# New imports for refactored components
from app.session.redis_store import RedisSessionStore
from app.conversation.smart_handler import SmartConversationHandler
from app.cache.flight_cache import FlightCacheManager
from app.async_handler import AsyncFlightSearchHandler, BackgroundTaskManager
from app.user.preferences import UserPreferenceManager
from app.formatters.enhanced_whatsapp import NaturalFormatter
from app.infrastructure.resilience import (
    ProductionMiddleware, CircuitBreaker, RateLimiter,
    HealthChecker, RequestValidator
)
from app.obs.middleware import ObservabilityMiddleware
from app.obs.logger import log_event

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("[INFO] Starting WhatsApp Travel Bot (Refactored)")

    # Initialize components
    app.state.redis_store = RedisSessionStore()
    app.state.amadeus = AmadeusClient()
    app.state.iata = IATADb(csv_path="data/iata/iata_codes_19_sep.csv")
    app.state.llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0)

    # Initialize managers
    app.state.cache_manager = FlightCacheManager(app.state.redis_store, app.state.amadeus)
    app.state.user_prefs = UserPreferenceManager(app.state.redis_store)
    app.state.task_manager = BackgroundTaskManager()
    app.state.formatter = NaturalFormatter()

    # Initialize conversation handler
    app.state.conversation = SmartConversationHandler(
        session_store=app.state.redis_store,
        amadeus_client=app.state.amadeus,
        llm=app.state.llm
    )

    # Initialize async handler
    app.state.async_handler = AsyncFlightSearchHandler(
        redis_store=app.state.redis_store,
        amadeus_client=app.state.amadeus,
        twilio_config={
            "account_sid": settings.TWILIO_ACCOUNT_SID,
            "auth_token": settings.TWILIO_AUTH_TOKEN,
            "whatsapp_number": settings.TWILIO_WHATSAPP_NUMBER
        }
    )

    # Warm up services
    try:
        # Warm Amadeus token
        app.state.amadeus._get_token()
        print("[INFO] Warmed Amadeus token")

        # Pre-warm popular route caches (run in background, limited to avoid rate limits)
        asyncio.create_task(app.state.cache_manager.warm_popular_routes(days_ahead=3))
        print("[INFO] Started cache warming for popular routes (rate-limited)")
    except Exception as e:
        print(f"[WARNING] Service warming failed: {e}")

    # Initialize circuit breakers
    app.state.amadeus_breaker = CircuitBreaker(
        name="amadeus_api",
        failure_threshold=5,
        recovery_timeout=60
    )

    yield

    # Shutdown
    print("[INFO] Shutting down WhatsApp Travel Bot")
    # Cleanup tasks
    for task in app.state.task_manager.tasks.values():
        task.cancel()


app = FastAPI(
    title="WhatsApp Travel Agent (Refactored)",
    version="2.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    return {
        "service": "WhatsApp Travel Bot",
        "version": "2.0.0",
        "status": "running",
        "features": [
            "Redis-backed sessions",
            "Smart caching",
            "Context-aware conversations",
            "User preferences",
            "Async processing",
            "Production resilience"
        ]
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "whatsapp-travel-bot"}


@app.get("/health/detailed")
async def detailed_health(request: Request):
    health_checker = HealthChecker()

    # Check Redis
    def check_redis():
        try:
            request.app.state.redis_store.client.ping()
            return True
        except:
            return False

    # Check Amadeus
    def check_amadeus():
        try:
            return request.app.state.amadeus_breaker.state.value != "open"
        except:
            return False

    health_checker.register_check("redis", check_redis)
    health_checker.register_check("amadeus", check_amadeus)

    results = await health_checker.run_checks()
    status_code = 200 if results["status"] == "healthy" else 503
    return JSONResponse(results, status_code=status_code)


@app.get("/metrics")
async def metrics(request: Request):
    cache_stats = request.app.state.cache_manager.get_cache_stats()
    breaker_state = request.app.state.amadeus_breaker.get_state()

    return {
        "cache": cache_stats,
        "circuit_breaker": breaker_state,
        "active_tasks": len(request.app.state.task_manager.tasks),
    }


@app.post("/whatsapp/webhook")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    Body: str = Form(...),
    From: str = Form(...),
    To: str = Form(...)
):
    # Validate request
    valid, error = RequestValidator.validate_whatsapp_message({
        "Body": Body,
        "From": From,
        "To": To
    })
    if not valid:
        raise HTTPException(status_code=400, detail=error)

    # Extract phone number
    phone_number = From.replace("whatsapp:", "")
    message = Body.strip()

    # Log event
    log_event("webhook_received",
        from_number=phone_number,
        message_length=len(message)
    )

    # Check if user needs welcome message
    user_prefs = request.app.state.user_prefs
    if user_prefs.should_offer_help(phone_number):
        welcome = user_prefs.format_welcome_back(phone_number)
        # Could send welcome via background task

    # Process message with smart conversation handler
    try:
        response = request.app.state.conversation.handle_message(
            user_id=phone_number,
            message=message
        )

        # Check if this triggered a search
        session = request.app.state.redis_store.get(phone_number)
        if session and session.get("searching"):
            # Handle search in background
            search_params = session["info"]
            task_id = f"search_{phone_number}_{asyncio.get_event_loop().time()}"

            # Create background search task
            coroutine = request.app.state.async_handler.search_and_respond(
                user_id=phone_number,
                phone_number=phone_number,
                search_params=search_params
            )

            request.app.state.task_manager.create_task(task_id, coroutine)

            # Return immediate acknowledgment
            response = request.app.state.formatter.format_searching_message()

            # Clear searching flag
            session["searching"] = False
            request.app.state.redis_store.set(phone_number, session)

    except Exception as e:
        log_event("webhook_error", error=str(e))
        response = request.app.state.formatter.format_error_friendly("general")

    # Convert to TwiML
    from app.utils.twilio import to_twiml_message
    xml = to_twiml_message(response)

    return Response(content=xml, media_type="application/xml")


@app.post("/admin/cache/warm")
async def warm_cache(request: Request, days_ahead: int = 7):
    """Admin endpoint to manually trigger cache warming"""
    asyncio.create_task(
        request.app.state.cache_manager.warm_popular_routes(days_ahead)
    )
    return {"status": "warming_started", "days": days_ahead}


@app.get("/admin/user/{user_id}/profile")
async def get_user_profile(request: Request, user_id: str):
    """Admin endpoint to view user profile and preferences"""
    profile = request.app.state.user_prefs.get_user_profile(user_id)
    return profile


@app.post("/admin/circuit/{name}/reset")
async def reset_circuit_breaker(request: Request, name: str):
    """Admin endpoint to manually reset a circuit breaker"""
    if name == "amadeus_api":
        request.app.state.amadeus_breaker.state = CircuitBreaker.CircuitState.CLOSED
        request.app.state.amadeus_breaker.failure_count = 0
        return {"status": "reset", "breaker": name}
    return {"error": "Unknown circuit breaker"}


# Apply middleware
app = ObservabilityMiddleware(app)

# Add production middleware if Redis is available
if settings.REDIS_URL:
    import redis
    redis_client = redis.from_url(settings.REDIS_URL)
    app = ProductionMiddleware(app, redis_client)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info"
    )
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
from app.cache.flight_cache import FlightCacheManager
from app.user.preferences import UserPreferenceManager
from app.formatters.enhanced_whatsapp import NaturalFormatter

# LangGraph integration
from app.langgraph.handler import create_langgraph_handler
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
    app.state.llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        temperature=0,
        api_key=settings.OPENAI_API_KEY
    )

    # Initialize managers
    app.state.cache_manager = FlightCacheManager(app.state.redis_store, app.state.amadeus)
    app.state.user_prefs = UserPreferenceManager(app.state.redis_store)
    app.state.formatter = NaturalFormatter()

    # Initialize LangGraph handler (replacing ConversationalHandler)
    app.state.conversation = create_langgraph_handler(
        session_store=app.state.redis_store,
        llm=app.state.llm,
        amadeus_client=app.state.amadeus,
        cache_manager=app.state.cache_manager,
        user_preferences=app.state.user_prefs,
        iata_db=app.state.iata
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


app = FastAPI(
    title="WhatsApp Travel Agent (LangGraph)",
    version="3.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    return {
        "service": "WhatsApp Travel Bot",
        "version": "3.0.0",
        "status": "running",
        "features": [
            "LangGraph state machine",
            "Systematic information collection",
            "Bulletproof validation gates",
            "Redis-backed sessions",
            "Smart caching",
            "Natural result presentation",
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
    from app.obs.metrics import get_metrics_snapshot
    # Guard against missing state when app is wrapped by middleware in tests
    cache_stats = getattr(request.app.state, "cache_manager", None)
    cache_stats = cache_stats.get_cache_stats() if cache_stats else {"hits": 0, "misses": 0, "hit_rate": "0.0%", "popular_routes": 0}
    breaker = getattr(request.app.state, "amadeus_breaker", None)
    breaker_state = breaker.get_state() if breaker else {"name": "amadeus_api", "state": "closed", "failure_count": 0, "last_failure": None}

    snapshot = get_metrics_snapshot()
    snapshot.update({
        "cache": cache_stats,
        "circuit_breaker": breaker_state,
    })
    return snapshot


@app.post("/whatsapp/webhook")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    Body: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    MessageSid: str | None = Form(None),
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
    log_event(
        "webhook_received",
        from_number=phone_number,
        message_length=len(message),
        message_sid=MessageSid,
    )

    # Check if user needs welcome message
    user_prefs = request.app.state.user_prefs
    if user_prefs.should_offer_help(phone_number):
        welcome = user_prefs.format_welcome_back(phone_number)
        # Could send welcome via background task

    # Process message with LangGraph handler
    try:
        response = request.app.state.conversation.handle_message(
            user_id=phone_number,
            message=message
        )

    except Exception as e:
        log_event("webhook_error", error=str(e))
        response = request.app.state.formatter.format_error_friendly("general")

    # Convert to TwiML
    from app.utils.twilio import to_twiml_message
    xml = to_twiml_message(response)

    # Twilio accepts both application/xml and text/xml; prefer text/xml per docs
    return Response(content=xml, media_type="text/xml")


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


@app.get("/admin/user/{user_id}/conversation")
async def get_user_conversation(request: Request, user_id: str):
    """Admin endpoint to view user's LangGraph conversation state"""
    return request.app.state.conversation.get_user_session_info(user_id)


@app.post("/admin/user/{user_id}/reset")
async def reset_user_conversation(request: Request, user_id: str):
    """Admin endpoint to reset user's conversation state"""
    success = request.app.state.conversation.reset_user_conversation(user_id)
    return {"status": "reset" if success else "error", "user_id": user_id}


@app.post("/admin/user/{user_id}/emergency-reset")
async def emergency_reset_user(request: Request, user_id: str):
    """Emergency endpoint to completely wipe user's session data"""
    try:
        # Complete session wipe - use this for debugging corrupted sessions
        # Use proper Redis key format with session: prefix
        redis_key = f"session:{user_id}"
        request.app.state.redis_store.client.delete(redis_key)
        print(f"[DEBUG] Emergency reset: completely wiped session for user {user_id} (key: {redis_key})")
        return {"status": "emergency_reset_complete", "user_id": user_id, "message": "All session data wiped"}
    except Exception as e:
        print(f"[ERROR] Emergency reset failed for user {user_id}: {e}")
        return {"status": "error", "user_id": user_id, "error": str(e)}


@app.get("/admin/langgraph/metrics")
async def langgraph_metrics(request: Request):
    """Admin endpoint to get LangGraph conversation metrics"""
    return request.app.state.conversation.get_conversation_metrics()


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

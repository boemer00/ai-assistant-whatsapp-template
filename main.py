import os
import time
from fastapi import FastAPI, Form, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse, Response, JSONResponse
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from app.config import settings
from app.iata.lookup import IATADb
from app.llm.extract_intent import extract_intent, IntentSchema
from app.parse.fast_intent import fast_parse
from app.amadeus.client import AmadeusClient
from app.amadeus.transform import from_amadeus
from app.rank.selector import rank_top
from app.formatters.whatsapp import format_reply
from app.obs.middleware import ObservabilityMiddleware
from app.obs.metrics import get_metrics_snapshot, record_timing
from app.obs.logger import log_event
from app.obs.context import from_var, message_sid_var
from app.session.store import SessionStore
from app.session.merge import merge_message, is_ready_for_confirmation, is_ready_to_search
from app.formatters.whatsapp import format_missing_date, format_missing_passengers, format_confirmation
from app.conversation_handler import ConversationHandler

load_dotenv()
app = FastAPI(title="Travel WhatsApp Agent")

# Load CSV once
IATA = IATADb(csv_path="data/iata/iata_codes_19_sep.csv")
LLM = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0)
AMA = AmadeusClient()
STORE = SessionStore(ttl_seconds=900)

# Instantiate ConversationHandler with real dependencies
CONVERSATION_HANDLER = ConversationHandler(
    session_store=STORE,
    amadeus_client=AMA
)

@app.on_event("startup")
def warm_amadeus_token():
    try:
        AMA._get_token()
        print("[DEBUG] Warmed Amadeus token on startup")
    except Exception as e:
        print(f"[DEBUG] Token warmup failed: {e}")

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/metrics")
def metrics():
    """Lightweight JSON metrics snapshot for local inspection."""
    return JSONResponse(get_metrics_snapshot())

@app.post("/whatsapp/webhook")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    Body: str = Form(...),               # message text from user
    From: str = Form(...),               # sender
    To: str = Form(...)                  # your Twilio number
):
    text = Body.strip()
    print(f"[DEBUG] Received message: {text}")
    # Attach minimal context
    try:
        from_var.set(From)
    except Exception:
        pass
    log_event("webhook_received", route="/whatsapp/webhook")

    # Use ConversationHandler to process the message
    response = CONVERSATION_HANDLER.handle_message(user_id=From, message=text)

    # Log the response for debugging
    print(f"[DEBUG] ConversationHandler response: {response}")

    # If the response indicates a search is in progress, handle in background
    if "Searching" in response or "I’ll send the results shortly" in response:
        # For now, assume synchronous; but in real scenario, use background
        pass

    # Convert to TwiML for Twilio
    from app.utils.twilio import to_twiml_message
    xml = to_twiml_message(response)
    return Response(content=xml, media_type="application/xml")

# Wrap app with observability middleware after routes are defined
app = ObservabilityMiddleware(app)

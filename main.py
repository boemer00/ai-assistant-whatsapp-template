import os
from fastapi import FastAPI, Form, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse, Response
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

load_dotenv()
app = FastAPI(title="Travel WhatsApp Agent")

# Load CSV once
IATA = IATADb(csv_path="data/iata/iata_codes_19_sep.csv")
LLM = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0)
AMA = AmadeusClient()

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

    # 1) Extract intent (fast regex first, fallback to LLM)
    intent_raw = fast_parse(text) or extract_intent(LLM, text)
    print(f"[DEBUG] Extracted intent: origin={intent_raw.origin}, dest={intent_raw.destination}, "
          f"dep_date={intent_raw.departure_date}, ret_date={intent_raw.return_date}, "
          f"passengers={intent_raw.passengers}")

    # 2) Resolve IATA codes
    origins = IATA.resolve(intent_raw.origin) if intent_raw.origin else []
    dests = IATA.resolve(intent_raw.destination) if intent_raw.destination else []
    print(f"[DEBUG] IATA lookup results: origins={origins}, dests={dests}")

    # Pick first match (MVP); if ambiguous, ask user
    if len(origins) > 1 or len(dests) > 1:
        msg = ("I found multiple matches. Please specify exact airports:\n"
               f"Origin matches: {origins or ['?']}\n"
               f"Destination matches: {dests or ['?']}")
        from app.utils.twilio import to_twiml_message
        xml = to_twiml_message(msg)
        return Response(content=xml, media_type="application/xml")

    origin_code = origins[0] if origins else None
    destination_code = dests[0] if dests else None

    # 3) If required info missing, ask for it
    if not origin_code or not destination_code or not intent_raw.departure_date:
        msg = format_reply(
            intent_raw,
            ranked=type("Tmp", (), {"fastest": None, "cheapest": []})()
        )
        from app.utils.twilio import to_twiml_message
        xml = to_twiml_message(msg)
        return Response(content=xml, media_type="application/xml")

    # 4) Hand off the expensive search to a background task, reply immediately
    def _do_search_and_reply():
        try:
            print(f"[DEBUG] Calling Amadeus API: {origin_code} -> {destination_code} on {intent_raw.departure_date}")
            data = AMA.search_flights(
                origin=origin_code,
                destination=destination_code,
                dep_date=intent_raw.departure_date,
                ret_date=intent_raw.return_date,
                adults=int(intent_raw.passengers or 1),
            )
            options = from_amadeus(data)
            print(f"[DEBUG] Amadeus returned {len(options)} flight options")
            ranked = rank_top(options)
            msg = format_reply(intent_raw, ranked)
        except Exception as e:
            print(f"[DEBUG] Amadeus API error (bg): {e}")
            msg = f"Sorry, I couldn't search flights at this time. Error: {str(e)}"
        from app.utils.twilio import send_whatsapp_message
        # Send to the original sender
        send_whatsapp_message(From.replace("whatsapp:", ""), msg)

    background_tasks.add_task(_do_search_and_reply)

    from app.utils.twilio import to_twiml_message
    xml = to_twiml_message("Searching… ✈️ I’ll send the results shortly.")
    return Response(content=xml, media_type="application/xml")

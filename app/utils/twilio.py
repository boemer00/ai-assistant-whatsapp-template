from typing import Final
from app.config import settings

try:
    from twilio.rest import Client as TwilioClient
except Exception:
    TwilioClient = None  # type: ignore

XML_DECL: Final[str] = '<?xml version="1.0" encoding="UTF-8"?>'


def escape_for_xml(text: str) -> str:
    """
    Escape &, <, >, ", ' for safe XML content.
    """
    if text is None:
        return ""
    # Order matters: escape & first to avoid double-escaping newly inserted entities
    escaped = text.replace("&", "&amp;")
    escaped = escaped.replace("<", "&lt;")
    escaped = escaped.replace(">", "&gt;")
    escaped = escaped.replace('"', "&quot;")
    escaped = escaped.replace("'", "&apos;")
    return escaped


def to_twiml_message(body: str) -> str:
    """
    Wrap a message body in minimal TwiML envelope.
    """
    return f"{XML_DECL}<Response><Message>{escape_for_xml(body)}</Message></Response>"


def send_whatsapp_message(to: str, body: str) -> None:
    """
    Send an outbound WhatsApp message via Twilio's REST API.
    """
    if TwilioClient is None:
        raise RuntimeError("twilio package not installed")
    client = TwilioClient(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    from_number = settings.TWILIO_WHATSAPP_NUMBER
    if not from_number.startswith("whatsapp:"):
        from_number = f"whatsapp:{from_number}"
    if not to.startswith("whatsapp:"):
        to = f"whatsapp:{to}"
    client.messages.create(from_=from_number, to=to, body=body)

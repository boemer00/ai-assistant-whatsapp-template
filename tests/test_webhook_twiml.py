from fastapi.testclient import TestClient
from main import app


def test_webhook_returns_twiml_xml(monkeypatch):
    client = TestClient(app)

    # Avoid hitting external APIs by short-circuiting to a trivial message
    # Monkeypatch format_reply to a simple constant
    from app import formatters
    orig = formatters.whatsapp.format_reply
    formatters.whatsapp.format_reply = lambda intent, ranked: "Hello & <world>"
    try:
        resp = client.post(
            "/whatsapp/webhook",
            data={
                "Body": "hi",
                "From": "whatsapp:+111",
                "To": "whatsapp:+222",
            },
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")
        xml = resp.text
        assert xml.startswith("<?xml")
        assert "<Response><Message>" in xml
    finally:
        formatters.whatsapp.format_reply = orig

from fastapi.testclient import TestClient


def test_metrics_capture_request_and_histogram():
    from main import app
    client = TestClient(app)

    # Hit health to generate a request metric
    r = client.get("/health")
    assert r.status_code == 200

    # Fetch metrics snapshot
    m = client.get("/metrics")
    assert m.status_code == 200
    data = m.json()

    # Ensure a counter for /health exists with status 200
    counters = data.get("counters", [])
    assert any(
        c.get("name") == "requests_total" and c.get("labels", {}).get("route") == "/health" and c.get("labels", {}).get("status") == "200"
        for c in counters
    )

    # Ensure histogram for /health exists
    hists = data.get("histograms", [])
    assert any(
        h.get("name") == "request_latency_ms" and h.get("labels", {}).get("route") == "/health" and isinstance(h.get("counts"), list)
        for h in hists
    )


def test_logger_redacts_phone(capsys):
    from app.obs.logger import log_event
    log_event("step", user_from="whatsapp:+441234567890", step="unit-test")
    captured = capsys.readouterr().out.strip()
    assert "***7890" in captured

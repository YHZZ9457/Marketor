import json

from fastapi.testclient import TestClient

from csi300_service import api
from csi300_service.api import app
from csi300_service.catalog import InstrumentCatalog


client = TestClient(app)


def test_dashboard_and_static_assets():
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "市场航图" in dashboard.text
    assert 'id="chart"' in dashboard.text
    assert client.get("/static/dashboard.css").status_code == 200
    assert client.get("/static/dashboard.js").status_code == 200


def test_instruments_and_default_compatibility():
    instruments = client.get("/instruments")
    assert instruments.status_code == 200
    assert instruments.json()[0]["symbol"] == "csi300"

    latest = client.get("/latest")
    assert latest.status_code == 200
    assert latest.json()["date"] == "2026-08-28"


def test_selectable_statistics_method():
    response = client.get(
        "/holding-returns",
        params={"symbol": "csi300", "method": "distribution", "days": "30,365"},
    )
    assert response.status_code == 200
    assert [row["days"] for row in response.json()] == [30, 365]
    assert "p90" in response.json()[0]


def test_unknown_instrument_returns_404():
    response = client.get("/latest", params={"symbol": "missing"})
    assert response.status_code == 404


def test_instruments_tolerates_missing_csv(tmp_path, monkeypatch):
    config = tmp_path / "instruments.json"
    config.write_text(json.dumps({"instruments": [
        {"symbol": "ghost", "name": "Ghost Index", "data_file": "ghost.csv"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(api, "catalog", InstrumentCatalog(config))
    api._service.cache_clear()
    try:
        response = TestClient(api.app).get("/instruments")
        assert response.status_code == 200
        row = response.json()[0]
        assert row["symbol"] == "ghost"
        assert row["data_available"] is False
        missing = TestClient(api.app).get("/latest", params={"symbol": "ghost"})
        assert missing.status_code == 404
    finally:
        api._service.cache_clear()


def test_comparison_and_deduplicated_events_endpoints():
    comparison = client.get("/comparison")
    assert comparison.status_code == 200
    assert len(comparison.json()) >= 6
    assert comparison.json()[0]["rank"] == 1

    events = client.get("/events", params={"symbol": "csi300", "cooldown": 60})
    assert events.status_code == 200
    payload = events.json()
    assert payload["summary"]["event_count"] == len(payload["events"])
    assert payload["metric"] == "bias250"

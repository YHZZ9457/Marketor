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
    assert latest.json()["date"] == instruments.json()[0]["last_date"]


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


def test_invalid_event_and_date_inputs_return_422():
    for params in ({"metric": "missing"}, {"metric": "date"}, {"direction": "sideways"}, {"threshold": "nan"}):
        assert client.get("/events", params=params).status_code == 422
    for params in ({"start": "not-a-date"}, {"start": "NaT"}, {"start": "2025-02-01", "end": "2025-01-01"}, {"start": "2025-01-01T00:00:00Z"}):
        assert client.get("/history", params=params).status_code == 422


def test_api_refresh_observes_csv_changes(tmp_path, monkeypatch):
    import pandas as pd
    config = tmp_path / "instruments.json"
    config.write_text(json.dumps({"instruments": [{"symbol": "demo", "name": "Demo", "data_file": "demo.csv"}]}), encoding="utf-8")
    path = tmp_path / "demo.csv"
    def save(close):
        pd.DataFrame({"date": ["2025-01-02"], "open": [close], "high": [close], "low": [close], "close": [close], "amount": [100]}).to_csv(path, index=False)
    save(100)
    monkeypatch.setattr(api, "catalog", InstrumentCatalog(config))
    try:
        assert client.get("/latest?symbol=demo").json()["close"] == 100
        save(1200)
        assert client.get("/latest?symbol=demo").json()["close"] == 1200
        path.unlink()
        assert client.get("/latest?symbol=demo").status_code == 404
    finally:
        api._service.cache_clear()

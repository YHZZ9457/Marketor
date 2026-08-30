import json

import pandas as pd
import pytest

from csi300_service.catalog import InstrumentCatalog
from csi300_service.service import CSI300Service, MarketService
from csi300_service.statistics import register_statistics_method


def test_latest_and_signal():
    s = CSI300Service()
    latest = s.latest()
    assert latest["date"] == "2026-08-28"
    assert latest["close"] > 0
    signal = s.signal()
    assert "accumulation" in signal
    assert "reduction" in signal
    assert 1.0 <= signal["accumulation"]["score"] <= 3.0
    assert 0 <= signal["reduction"]["score"] <= 40


def test_history_range():
    s = CSI300Service()
    rows = s.history("2026-08-01", "2026-08-31")
    assert rows
    assert rows[0]["date"] >= "2026-08-01"


def test_holding_returns():
    rows = CSI300Service().holding_returns([1, 7, 30])
    assert [r["days"] for r in rows] == [1, 7, 30]
    assert all(r["samples"] > 0 for r in rows)


def test_distribution_statistics():
    rows = CSI300Service().holding_returns([30], method="distribution")
    assert {"std", "p10", "p90"} <= rows[0].keys()
    assert rows[0]["p10"] <= rows[0]["median"] <= rows[0]["p90"]


def test_custom_statistics_method():
    register_statistics_method("test_range", lambda values: {"range": float(values.max() - values.min())}, replace=True)
    row = CSI300Service().holding_returns([7], method="test_range")[0]
    assert row["range"] >= 0


def test_additional_instrument_from_catalog(tmp_path):
    market = tmp_path / "demo.csv"
    pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=20),
        "close": range(100, 120),
    }).to_csv(market, index=False)
    config = tmp_path / "instruments.json"
    config.write_text(json.dumps({"instruments": [{
        "symbol": "demo", "name": "Demo Market", "data_file": "demo.csv",
        "asset_class": "fund", "currency": "USD",
    }]}), encoding="utf-8")

    service = MarketService("DEMO", catalog=InstrumentCatalog(config))
    assert service.latest()["close"] == 119
    assert service.metadata()["currency"] == "USD"


def test_unknown_statistics_method():
    with pytest.raises(ValueError, match="Unknown statistics method"):
        CSI300Service().holding_returns([7], method="missing")


def test_bundled_catalog_includes_verified_new_indices():
    catalog = InstrumentCatalog()
    assert len(catalog.list()) == 22
    assert catalog.get("sse_composite").tencent_code == "sh000001"
    assert catalog.get("star50").source_priority[0] == "eastmoney"
    assert catalog.get("csi300").zh_index_code == "000300"
    assert catalog.get("csi2000").zh_index_code == "932000"
    assert catalog.get("star100").zh_index_code == "000698"

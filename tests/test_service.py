import json

import pandas as pd
import pytest

from csi300_service.catalog import InstrumentCatalog, default_data_dir
from csi300_service.legacy_strategy import evaluate as evaluate_legacy
from csi300_service.service import CSI300Service, MarketService
from csi300_service.statistics import register_statistics_method
from csi300_service.strategy import evaluate


def test_latest_and_signal():
    s = CSI300Service()
    latest = s.latest()
    assert latest["date"] == s.metadata()["last_date"]
    assert latest["close"] > 0
    signal = s.signal()
    assert signal["strategy_id"] == "ma_dynamic_v1"
    assert "accumulation" in signal
    assert "reduction" in signal
    assert signal["accumulation"]["score"] in (0, 50, 75, 100)
    assert signal["reduction"]["score"] in (0, 50, 75, 100)
    assert signal["initial_entry"]["amount"] == 10000
    assert signal["portfolio_state_required"] is True


@pytest.mark.parametrize("bias,buy,sell", [
    (-0.049999, 0, 0), (-0.05, 50, 0), (-0.10, 75, 0), (-0.15, 100, 0),
    (0.099999, 0, 0), (0.10, 0, 50), (0.15, 0, 75), (0.20, 0, 100),
    (0.0, 0, 0),
])
def test_current_signal_uses_v1_tiers(bias, buy, sell):
    signal = evaluate({
        "date": "2026-09-14", "close": 100.0, "ma500": 100.0,
        "bias500": 0.0, "bias250": bias,
    })
    assert signal["strategy_id"] == "ma_dynamic_v1"
    assert signal["accumulation"]["score"] == buy
    assert signal["reduction"]["score"] == sell


def test_current_signal_entry_uses_ma500_price_gate():
    eligible = evaluate({
        "date": "2026-09-14", "close": 110.0, "ma500": 100.0,
        "bias500": 0.10, "bias250": 0.0,
    })
    blocked = evaluate({
        "date": "2026-09-14", "close": 110.000001, "ma500": 100.0,
        "bias500": 0.10000001, "bias250": 0.0,
    })
    assert eligible["initial_entry"]["eligible"] is True
    assert blocked["initial_entry"]["eligible"] is False


def test_legacy_strategy_remains_separate_from_v1():
    row = {
        "date": "2026-09-14", "close": 100, "bias250": -0.10,
        "bias500": 0.20, "bias1250": 0.30, "rsi14": 29,
        "rsi_cross_down_75": True, "rsi_cross_down_70": True,
    }
    legacy = evaluate_legacy(row)
    current = evaluate({**row, "ma500": 100})
    assert legacy["accumulation"]["score"] == 3.0
    assert legacy["reduction"]["score"] == 40
    assert current["accumulation"]["score"] == 75
    assert current["reduction"]["score"] == 0


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
    catalog = InstrumentCatalog(default_data_dir() / "instruments.json")
    assert len(catalog.list()) == 31
    assert len(catalog.list(include_unavailable=False)) == 25
    assert catalog.get("sse_composite").tencent_code == "sh000001"
    assert catalog.get("star50").source_priority[0] == "eastmoney"
    assert catalog.get("csi300").zh_index_code == "000300"
    assert catalog.get("csi2000").zh_index_code == "932000"
    assert catalog.get("star100").zh_index_code == "000698"
    assert catalog.get("sp500").market == "US"
    assert catalog.get("sp500").source_priority == ("sina", "eastmoney")
    assert catalog.get("hang_seng_tech").currency == "HKD"


def test_catalog_hides_instrument_without_local_data(tmp_path):
    config = tmp_path / "instruments.json"
    config.write_text(json.dumps({"instruments": [{
        "symbol": "missing", "name": "Missing Market", "data_file": "missing.csv",
    }]}), encoding="utf-8")

    catalog = InstrumentCatalog(config)
    assert len(catalog.list()) == 1
    assert catalog.list(include_unavailable=False) == []


def test_frozen_app_copies_bundled_data_to_writable_profile(tmp_path, monkeypatch):
    bundled = tmp_path / "bundle" / "data"
    bundled.mkdir(parents=True)
    (bundled / "instruments.json").write_text('{"instruments": []}', encoding="utf-8")
    (bundled / "sample.csv").write_text("date,close\n2024-01-01,100\n", encoding="utf-8")
    profile = tmp_path / "profile"
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(profile))

    result = default_data_dir()

    assert result == profile / "Marketor" / "data"
    assert (result / "sample.csv").exists()

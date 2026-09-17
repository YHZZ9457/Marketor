import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from csi300_service.api import app
from csi300_service.catalog import InstrumentCatalog
from csi300_service.ma_dynamic import backtest, load_total_return, trade_fraction
from csi300_service.service import MarketService


def frames(prices, levels):
    dates = pd.bdate_range("2020-01-01", periods=500 + len(prices))
    return (pd.DataFrame({"date": dates, "close": [100.] * 500 + prices}),
            pd.DataFrame({"date": dates, "close": [100.] * 500 + levels}))


@pytest.mark.parametrize("bias,pnl,fraction", [
    (-.05, -100, .5), (-.10, -100, .75), (-.15, -100, 1),
    (.10, 100, .5), (.15, 100, .75), (.20, 100, 1),
    (-.049999, -100, 0), (-.099999, -100, .5), (-.149999, -100, .75),
    (.099999, 100, 0), (.149999, 100, .5), (.199999, 100, .75),
    (-.5, 100, 0), (.5, -100, 0), (0, -100, 0), (0, 100, 0),
    (.3, 0, 0), (float("nan"), -100, 0),
])
def test_highest_tier_and_pnl_direction(bias, pnl, fraction):
    assert trade_fraction(bias, pnl) == fraction


def test_cash_pool_and_capital_conservation():
    price, tri = frames([130, 80, 80, 80], [110, 108.9, 100, 90])
    result = backtest(price, tri)
    first, sell, buy, large_buy, later_buy = result["ledger"][-5:]
    assert first["action"] == "initial_buy"
    assert first["external_added"] == 10000
    assert first["daily_pnl"] == 0
    assert sell["action"] == "sell"
    assert sell["sell_amount"] == pytest.approx(1000)
    assert sell["cash"] == pytest.approx(1000)
    assert buy["action"] == "buy"
    assert buy["buy_amount"] == pytest.approx(100)
    assert buy["cash_used"] == pytest.approx(100)
    assert buy["external_added"] == 0
    assert large_buy["cash_used"] > 0
    assert later_buy["external_added"] > 0
    assert later_buy["cash"] == 0
    assert result["summary"]["profit"] == pytest.approx(sum(r["daily_pnl"] for r in result["ledger"]))
    for row in result["ledger"]:
        assert row["total_assets"] == pytest.approx(row["holding_value"] + row["cash"])
        assert row["profit"] == pytest.approx(row["total_assets"] - row["external_total"])
        assert row["cash"] >= 0
        assert row["units"] >= 0


def test_price_and_total_return_are_separate_and_ma500_only_for_entry():
    price, tri = frames([130, 130], [110, 109])
    result = backtest(price, tri)
    assert result["ledger"][-2]["action"] == "sell"  # even above MA500 * 1.10
    assert result["ledger"][-1]["action"] == "hold"  # price flat; TR loss, not price gain
    assert sum(r["action"] == "initial_buy" for r in result["ledger"]) == 1


def test_entry_gate_and_warmup():
    price, tri = frames([120, 100], [100, 100])
    result = backtest(price, tri, start=str(price.date.iloc[-2].date()))
    assert [r["action"] for r in result["ledger"]] == ["wait", "initial_buy"]
    assert backtest(price.iloc[:499], tri.iloc[:499])["summary"]["entered"] is False
    assert result["ledger"][-1]["buy_amount"] == 10000


def test_exact_entry_boundary():
    # 499 prior closes of 100; solve x == 1.10 * ((49900+x)/500).
    x = 54890 / 498.9
    price, tri = frames([], [])
    price.loc[499, "close"] = x
    assert backtest(price, tri)["summary"]["entered"]
    price.loc[499, "close"] = x + 1e-6
    assert not backtest(price, tri)["summary"]["entered"]


@pytest.mark.parametrize("damage", ["missing", "duplicate", "unordered", "zero", "nan", "infinite"])
def test_bad_total_return_rejected(damage):
    price, tri = frames([90], [99])
    if damage == "missing": tri = tri.drop(499)
    if damage == "duplicate": tri.loc[500, "date"] = tri.loc[499, "date"]
    if damage == "unordered": tri = tri.iloc[::-1]
    if damage == "zero": tri.loc[500, "close"] = 0
    if damage == "nan": tri.loc[500, "close"] = np.nan
    if damage == "infinite": tri.loc[500, "close"] = np.inf
    with pytest.raises(ValueError): backtest(price, tri)


def test_date_range_errors():
    price, tri = frames([], [])
    for start, end in [("2022-01-01", "2020-01-01"), ("invalid", None), ("2030-01-01", None)]:
        with pytest.raises(ValueError): backtest(price, tri, start, end)


def test_total_return_provenance(tmp_path):
    path = tmp_path / "tri.csv"
    pd.DataFrame({"date": ["2020-01-01"], "close": [100]}).to_csv(path, index=False)
    with pytest.raises(ValueError): load_total_return(path, "TEST")
    meta = {"index_code": "WRONG", "return_type": "total_return", "source": "test fixture", "download_time": "2026-09-14"}
    Path(str(path) + ".meta.json").write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError): load_total_return(path, "TEST")
    meta["index_code"] = "TEST"
    Path(str(path) + ".meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert len(load_total_return(path, "TEST")[0]) == 1


@pytest.mark.parametrize("symbol,code", [("csi300", "H00300"), ("csi800", "H00906"), ("csi_a500", "000510CNY010")])
def test_catalog_and_api_missing_data(symbol, code):
    instrument = InstrumentCatalog().get(symbol)
    assert instrument.total_return_code == code
    assert "ma_dynamic_v1" in instrument.strategies
    response = TestClient(app).get("/strategies/ma-dynamic-v1", params={"symbol": symbol})
    assert response.status_code == 200
    assert response.json()["status"] == "data_unavailable"
    assert "summary" not in response.json()


def test_all_catalog_instruments_use_v1_by_default():
    catalog = InstrumentCatalog()
    assert all("ma_dynamic_v1" in item.strategies for item in catalog.list())
    result = MarketService("csi500", catalog=catalog).ma_dynamic()
    assert result["status"] == "data_unavailable"
    assert result["strategy_id"] == "ma_dynamic_v1"


def test_service_api_and_cli_success(tmp_path, monkeypatch):
    from csi300_service import api
    from csi300_service import cli
    from typer.testing import CliRunner

    price, tri = frames([130, 80], [110, 109])
    price.to_csv(tmp_path / "price.csv", index=False)
    tri.to_csv(tmp_path / "tri.csv", index=False)
    (tmp_path / "tri.csv.meta.json").write_text(json.dumps({
        "index_code": "TEST", "return_type": "total_return",
        "source": "synthetic test fixture", "download_time": "2026-09-14",
    }), encoding="utf-8")
    config = tmp_path / "instruments.json"
    config.write_text(json.dumps({"instruments": [{
        "symbol": "fixture", "name": "Synthetic", "data_file": "price.csv",
        "strategies": ["ma_dynamic_v1"], "total_return_code": "TEST",
        "total_return_file": "tri.csv",
    }]}), encoding="utf-8")
    catalog = InstrumentCatalog(config)
    service = MarketService("fixture", catalog=catalog)
    original_signal = service.signal()
    result = service.ma_dynamic(include_ledger=False)
    assert result["status"] == "ok"
    assert "ledger" not in result
    assert result["summary"]["trade_count"] == 3
    assert service.signal() == original_signal
    monkeypatch.setattr(api, "catalog", catalog)
    api._service.cache_clear()
    try:
        client = TestClient(app)
        response = client.get("/strategies/ma-dynamic-v1", params={"symbol": "fixture", "include_ledger": True})
        assert response.status_code == 200
        assert len(response.json()["ledger"]) == len(price)
        bad = client.get("/strategies/ma-dynamic-v1", params={"symbol": "fixture", "start": "invalid"})
        assert bad.status_code == 422
        monkeypatch.setattr(cli, "MarketService", lambda symbol: service)
        output = CliRunner().invoke(cli.app, ["ma-dynamic", "--symbol", "fixture", "--ledger"])
        assert output.exit_code == 0, output.output
        assert len(json.loads(output.output)["ledger"]) == len(price)
    finally:
        api._service.cache_clear()


def test_total_return_path_cannot_escape_catalog(tmp_path):
    config = tmp_path / "instruments.json"
    config.write_text(json.dumps({"instruments": [{
        "symbol": "fixture", "name": "test", "data_file": "price.csv",
        "total_return_file": "../outside.csv",
    }]}), encoding="utf-8")
    with pytest.raises(ValueError): InstrumentCatalog(config)


def test_price_path_cannot_escape_catalog(tmp_path):
    config = tmp_path / "instruments.json"
    config.write_text(json.dumps({"instruments": [{
        "symbol": "fixture", "name": "test", "data_file": "../outside.csv",
    }]}), encoding="utf-8")
    with pytest.raises(ValueError):
        InstrumentCatalog(config)

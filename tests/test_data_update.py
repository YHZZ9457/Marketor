from __future__ import annotations

import hashlib
import io
import json

import pandas as pd
import pytest

from csi300_service.catalog import InstrumentCatalog
from csi300_service.data import load_data
from csi300_service.data_sources import (
    AKShareEastMoneyDataSource,
    AKShareGlobalEastMoneyDataSource,
    AKShareGlobalSinaDataSource,
    AKShareHKIndexSinaDataSource,
    AKShareIndexZHHistDataSource,
    AKShareTencentDataSource,
    AKShareUSIndexSinaDataSource,
    BaoStockDataSource,
    HiThinkDataSource,
    MarketDataSource,
    TushareDataSource,
)
from csi300_service.updater import MarketDataUpdater, OverlapMismatchError, read_source_meta
from csi300_service.validation import validate_market_data


def market_frame(periods: int = 10) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=periods)
    close = pd.Series([100.0 + index for index in range(periods)])
    return pd.DataFrame({
        "date": dates,
        "open": close - 0.3,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "amount": 1000.0 + close,
        "daily_return": close.pct_change(),
        "return": close.pct_change(),
        "net_value": close / close.iloc[0],
    })


class FakeSource(MarketDataSource):
    def __init__(self, frame: pd.DataFrame | None = None, error: Exception | None = None):
        self.frame = frame
        self.error = error
        self.calls: list[tuple[str | None, str | None]] = []

    def get_daily(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        self.calls.append((start_date, end_date))
        if self.error:
            raise self.error
        assert self.frame is not None
        return self.frame.copy()


def temp_catalog(tmp_path, frame: pd.DataFrame) -> tuple[InstrumentCatalog, object]:
    csv_path = tmp_path / "demo.csv"
    frame.to_csv(csv_path, index=False)
    config = tmp_path / "instruments.json"
    config.write_text(json.dumps({"instruments": [{
        "symbol": "demo",
        "name": "Demo Index",
        "asset_class": "index",
        "currency": "CNY",
        "provider_code": "000300.SH",
        "amount_unit": "CNY_THOUSAND",
        "data_file": "demo.csv",
    }]}), encoding="utf-8")
    return InstrumentCatalog(config), csv_path


def test_tushare_reverses_dates_and_converts_percent_return():
    class Client:
        def index_daily(self, **kwargs):
            assert kwargs["ts_code"] == "000300.SH"
            return pd.DataFrame({
                "trade_date": ["20240103", "20240102"],
                "open": [101, 100], "high": [103, 102], "low": [100, 99],
                "close": [102, 101], "amount": [2000, 1000], "pct_chg": [1.25, -0.5],
            })

    result = TushareDataSource(client=Client()).get_daily("2024-01-01", "2024-01-04")
    assert result["date"].is_monotonic_increasing
    assert result.iloc[-1]["daily_return"] == pytest.approx(0.0125)
    assert result.iloc[-1]["amount"] == 2000


def test_baostock_logs_out_and_normalizes_units():
    class Response:
        error_code = "0"
        error_msg = "success"

    class Query(Response):
        fields = ["date", "open", "high", "low", "close", "volume", "amount", "pctChg"]

        def __init__(self):
            self.rows = iter([
                ["2024-01-02", "100", "102", "99", "101", "1000", "2500000", "1.25"],
                ["2024-01-03", "101", "103", "100", "102", "1100", "3000000", "0.9901"],
            ])
            self.current = None

        def next(self):
            self.current = next(self.rows, None)
            return self.current is not None

        def get_row_data(self):
            return self.current

    class Client:
        logged_out = False
        def login(self): return Response()
        def logout(self): self.logged_out = True
        def query_history_k_data_plus(self, code, fields, **kwargs):
            assert code == "sh.000300"
            assert kwargs["adjustflag"] == "3"
            return Query()

    client = Client()
    result = BaoStockDataSource(client=client).get_daily("2024-01-01", "2024-01-04")
    assert client.logged_out
    assert result.iloc[0]["amount"] == 2500
    assert result.iloc[0]["daily_return"] == pytest.approx(0.0125)


def test_hithink_index_normalizes_official_response_without_leaking_key():
    payload = {
        "code": 0, "message": "success", "data": {"adjust": None, "item": [
            {"date_ms": 1704124800000, "open_price": 100, "high_price": 102,
             "low_price": 99, "close_price": 101, "turnover": 2_500_000},
            {"date_ms": 1704211200000, "open_price": 101, "high_price": 103,
             "low_price": 100, "close_price": 102, "turnover": 3_000_000},
        ]},
    }

    def opener(request, timeout):
        assert timeout == 25
        assert dict((key.lower(), value) for key, value in request.header_items())["x-api-key"] == "secret-test-key"
        assert "/api/a-share-index/prices/historical?" in request.full_url
        assert "thscode=000300.SH" in request.full_url
        assert "adjust=" not in request.full_url
        return io.BytesIO(json.dumps(payload).encode())

    result = HiThinkDataSource(
        "000300.SH", api_key="secret-test-key", amount_scale=0.001, opener=opener,
    ).get_daily("2024-01-01", "2024-01-04")
    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == ["2024-01-02", "2024-01-03"]
    assert result["amount"].tolist() == [2500.0, 3000.0]
    assert result.iloc[-1]["daily_return"] == pytest.approx(102 / 101 - 1)


def test_hithink_requires_key(monkeypatch):
    monkeypatch.delenv("HITHINK_FINANCE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="HITHINK_FINANCE_API_KEY"):
        HiThinkDataSource("000300.SH").get_daily("2024-01-01", "2024-01-04")


def test_akshare_tencent_normalizes_schema_and_preserves_documented_lots():
    class Client:
        def stock_zh_index_daily_tx(self, **kwargs):
            assert kwargs["symbol"] == "sh000001"
            assert kwargs["start_date"] == "20240101"
            return pd.DataFrame({
                "date": ["2024-01-02", "2024-01-03"],
                "open": [100, 101], "close": [101, 102], "high": [102, 103],
                "low": [99, 100], "amount": [1000, 1100],
            })

    result = AKShareTencentDataSource("sh000001", amount_unit="LOTS", client=Client()).get_daily(
        "2024-01-01", "2024-01-04"
    )
    assert list(result.columns) == ["date", "open", "high", "low", "close", "amount", "daily_return"]
    assert result.iloc[-1]["daily_return"] == pytest.approx(102 / 101 - 1)


def test_akshare_eastmoney_converts_yuan_amount_to_thousands():
    class Client:
        def stock_zh_index_daily_em(self, **kwargs):
            return pd.DataFrame({
                "date": ["2024-01-02", "2024-01-03"],
                "open": [100, 101], "close": [101, 102], "high": [102, 103],
                "low": [99, 100], "amount": [2_500_000, 3_000_000],
            })

    result = AKShareEastMoneyDataSource("sh000001", client=Client()).get_daily(
        "2024-01-01", "2024-01-04"
    )
    assert result.iloc[0]["amount"] == 2500


def test_zh_hist_provider_uses_code_only_and_converts_amount():
    class Client:
        def index_zh_a_hist(self, **kwargs):
            assert kwargs["symbol"] == "000300"  # plain code, no sh/csi prefix
            assert kwargs["start_date"] == "20240101"
            return pd.DataFrame({
                "日期": ["2024-01-02", "2024-01-03"],
                "开盘": [100, 101], "收盘": [101, 102], "最高": [102, 103],
                "最低": [99, 100], "成交额": [2_500_000, 3_000_000],
            })

    result = AKShareIndexZHHistDataSource("000300", eastmoney_code="csi000300", client=Client()).get_daily(
        "2024-01-01", "2024-01-04"
    )
    assert result.iloc[0]["amount"] == 2500
    assert result.iloc[-1]["daily_return"] == pytest.approx(102 / 101 - 1)
    assert result["date"].is_monotonic_increasing


def test_zh_hist_falls_back_to_prefixed_eastmoney():
    class Client:
        def index_zh_a_hist(self, **kwargs):
            raise RuntimeError("code not in index_zh_a_hist universe")

        def stock_zh_index_daily_em(self, **kwargs):
            assert kwargs["symbol"] == "bj899050"
            return pd.DataFrame({
                "date": ["2024-01-02", "2024-01-03"],
                "open": [100, 101], "close": [101, 102], "high": [102, 103],
                "low": [99, 100], "amount": [1000, 1100],
            })

    result = AKShareIndexZHHistDataSource(
        "899050", eastmoney_code="bj899050", amount_unit="LOTS", client=Client()
    ).get_daily("2024-01-01", "2024-01-04")
    assert list(result.columns) == ["date", "open", "high", "low", "close", "daily_return"]


def test_zh_hist_without_backup_code_reports_clear_error():
    class Client:
        def index_zh_a_hist(self, **kwargs):
            raise RuntimeError("downstream failure")

    with pytest.raises(RuntimeError, match="未配置东方财富备用代码"):
        AKShareIndexZHHistDataSource("000300", client=Client()).get_daily()


def test_global_eastmoney_normalizes_chinese_columns_and_date_range():
    class Client:
        def index_global_hist_em(self, **kwargs):
            assert kwargs["symbol"] == "日经225"
            return pd.DataFrame({
                "日期": ["2024-01-01", "2024-01-02", "2024-01-03"],
                "今开": [100, 101, 102], "最新价": [101, 102, 103],
                "最高": [102, 103, 104], "最低": [99, 100, 101],
            })

    result = AKShareGlobalEastMoneyDataSource("日经225", client=Client()).get_daily(
        "2024-01-02", "2024-01-03"
    )
    assert len(result) == 2
    assert list(result.columns) == ["date", "open", "high", "low", "close", "amount", "daily_return"]
    assert result.iloc[-1]["daily_return"] == pytest.approx(103 / 102 - 1)


def test_global_source_repairs_small_ohlc_envelope_gap():
    class Client:
        def index_us_stock_sina(self, **kwargs):
            return pd.DataFrame({
                "date": ["2024-01-02"], "open": [100.0], "close": [101.0],
                "high": [101.0], "low": [100.5],
            })

    result = AKShareUSIndexSinaDataSource(".INX", client=Client()).get_daily()
    assert result.iloc[0]["low"] == 100.0


def test_global_source_drops_isolated_severe_ohlc_row():
    class Client:
        def index_us_stock_sina(self, **kwargs):
            rows = 250
            return pd.DataFrame({
                "date": pd.bdate_range("2024-01-02", periods=rows),
                "open": [100.0] * (rows - 1) + [100.0],
                "close": [101.0] * (rows - 1) + [101.0],
                "high": [102.0] * (rows - 1) + [50.0],
                "low": [99.0] * rows,
            })

    result = AKShareUSIndexSinaDataSource(".INX", client=Client()).get_daily()
    assert len(result) == 249


@pytest.mark.parametrize(
    ("source_type", "method", "symbol"),
    [
        (AKShareUSIndexSinaDataSource, "index_us_stock_sina", ".INX"),
        (AKShareHKIndexSinaDataSource, "stock_hk_index_daily_sina", "HSI"),
    ],
)
def test_sina_global_sources_normalize_schema(source_type, method, symbol):
    class Client:
        def __getattr__(self, name):
            assert name == method
            return lambda **kwargs: pd.DataFrame({
                "date": ["2024-01-02", "2024-01-03"],
                "open": [100, 101], "close": [101, 102],
                "high": [102, 103], "low": [99, 100], "volume": [1000, 1100],
            })

    result = source_type(symbol, client=Client()).get_daily()
    assert result["date"].is_monotonic_increasing
    assert result.iloc[-1]["daily_return"] == pytest.approx(102 / 101 - 1)


def test_global_sina_source_uses_mapped_name():
    class Client:
        def index_global_hist_sina(self, **kwargs):
            assert kwargs["symbol"] == "日经225指数"
            return pd.DataFrame({
                "date": ["2024-01-02"], "open": [100], "close": [101],
                "high": [102], "low": [99], "volume": [1000],
            })

    result = AKShareGlobalSinaDataSource("日经225指数", client=Client()).get_daily()
    assert result.iloc[0]["close"] == 101


def test_validation_rejects_duplicate_dates():
    frame = market_frame(3)
    duplicate = pd.concat([frame, frame.iloc[[-1]]], ignore_index=True)
    with pytest.raises(ValueError, match="日期重复"):
        validate_market_data(duplicate)


def test_incremental_update_verifies_overlap_and_appends(tmp_path):
    local = market_frame(10)
    catalog, csv_path = temp_catalog(tmp_path, local)
    new = market_frame(12)
    remote = new.reset_index(drop=True)
    source = FakeSource(remote)

    result = MarketDataUpdater("demo", catalog=catalog, remote_source=source).run(allow_fallback=False)

    assert source.calls[0][0] == local.iloc[0]["date"].strftime("%Y-%m-%d")
    assert result.online_success
    assert result.data_source == "FakeSource"
    assert result.new_records == 2
    saved = load_data(csv_path)
    assert len(saved) == 12
    assert saved["date"].is_monotonic_increasing
    assert not saved["date"].duplicated().any()


def test_api_failure_falls_back_without_touching_csv(tmp_path):
    catalog, csv_path = temp_catalog(tmp_path, market_frame(10))
    before = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    source = FakeSource(error=RuntimeError("network unavailable"))

    result = MarketDataUpdater("demo", catalog=catalog, remote_source=source).run()

    assert not result.online_success
    assert result.data_source == "Local CSV"
    assert "继续使用本地数据" in result.warning
    assert result.latest["date"] == "2024-01-15"
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == before


def test_baostock_login_failure_falls_back_to_csv(tmp_path):
    class FailedLogin:
        error_code = "1001"
        error_msg = "network unavailable"

    class Client:
        def login(self): return FailedLogin()

    catalog, csv_path = temp_catalog(tmp_path, market_frame(10))
    before = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    source = BaoStockDataSource(client=Client())
    result = MarketDataUpdater("demo", catalog=catalog, remote_source=source).run()
    assert not result.online_success
    assert result.data_source == "Local CSV"
    assert "BaoStockDataSource" in result.attempts[0]
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == before


def test_overlap_conflict_rejects_update_without_touching_csv(tmp_path):
    local = market_frame(10)
    catalog, csv_path = temp_catalog(tmp_path, local)
    remote = market_frame(12).reset_index(drop=True)
    remote.loc[remote["date"] == local.iloc[-1]["date"], "close"] += 0.5
    before = hashlib.sha256(csv_path.read_bytes()).hexdigest()

    with pytest.raises(OverlapMismatchError, match="收盘价不一致"):
        MarketDataUpdater("demo", catalog=catalog, remote_source=FakeSource(remote)).run(allow_fallback=False)
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == before


def test_source_priority_falls_through_to_next_source(tmp_path, monkeypatch):
    """Primary source failing must not block the backup source."""
    monkeypatch.setattr("csi300_service.updater.hithink_api_key", lambda: None)
    catalog, csv_path = temp_catalog(tmp_path, market_frame(10))
    failing = FakeSource(error=RuntimeError("primary down"))
    good = FakeSource(market_frame(12))
    used: list[str] = []

    def fake_create(_self, mode):  # patched onto the class -> receives the instance
        used.append(mode)
        if mode == "eastmoney":
            return "FakePrimary", failing
        if mode == "tencent":
            return "FakeBackup", good
        raise RuntimeError(f"unexpected mode {mode}")

    monkeypatch.setattr(MarketDataUpdater, "_create_source", fake_create)
    result = MarketDataUpdater("demo", catalog=catalog).run(allow_fallback=False)

    assert result.online_success
    assert result.data_source == "FakeBackup"
    assert result.new_records == 2
    assert len(load_data(csv_path)) == 12
    assert used[0] == "eastmoney"
    assert "FakePrimary: primary down" in result.attempts
    assert result.attempts[-1] == "FakeBackup: success"


def test_metadata_sidecar_written_on_successful_update(tmp_path):
    catalog, csv_path = temp_catalog(tmp_path, market_frame(10))
    result = MarketDataUpdater("demo", catalog=catalog, remote_source=FakeSource(market_frame(12))).run(
        allow_fallback=False
    )
    assert result.meta_path == str(csv_path) + ".meta.json"
    meta = read_source_meta("demo", catalog=catalog)
    assert meta is not None
    assert meta["source"] == "FakeSource"
    assert meta["symbol"] == "demo"
    assert meta["latest_date"] == "2024-01-17"
    assert meta["overlap_records"] >= 1
    assert meta["new_records"] == 2


def test_metadata_sidecar_absent_on_failure(tmp_path):
    catalog, csv_path = temp_catalog(tmp_path, market_frame(10))
    result = MarketDataUpdater("demo", catalog=catalog, remote_source=FakeSource(error=RuntimeError("down"))).run()
    assert not result.online_success
    assert not (csv_path.parent / (csv_path.name + ".meta.json")).exists()

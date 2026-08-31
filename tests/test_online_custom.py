from __future__ import annotations

import io
import json

import pandas as pd

from csi300_service.catalog import InstrumentCatalog
from csi300_service.custom_instruments import CustomInstrumentManager
from csi300_service.data_sources import (
    AKShareCNStockTencentDataSource,
    AKShareOpenFundDataSource,
    YahooChartDataSource,
)
from csi300_service.online_custom import OnlineCustomInstrumentManager, normalize_cn_provider_code


class FakeAKShare:
    def stock_zh_a_hist_tx(self, **_kwargs):
        return pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=20),
            "open": range(99, 119), "high": range(101, 121),
            "low": range(98, 118), "close": range(100, 120),
            "amount": range(1000, 1020),
        })

    def fund_open_fund_info_em(self, **_kwargs):
        return pd.DataFrame({
            "净值日期": pd.date_range("2024-01-01", periods=20),
            "单位净值": [1 + index / 100 for index in range(20)],
        })


def test_cn_code_normalization():
    assert normalize_cn_provider_code("600519") == ("600519", "sh.600519", "sh600519")
    assert normalize_cn_provider_code("sz.000001") == ("000001", "sz.000001", "sz000001")


def test_custom_akshare_stock_and_fund_sources():
    stock = AKShareCNStockTencentDataSource("sh600519", client=FakeAKShare()).get_daily()
    fund = AKShareOpenFundDataSource("000001", client=FakeAKShare()).get_daily()
    assert stock.iloc[-1]["close"] == 119
    assert fund.iloc[-1]["close"] == 1.19
    assert {"date", "close", "daily_return"} <= set(fund.columns)


def test_yahoo_chart_source_uses_adjusted_prices():
    payload = {
        "chart": {"error": None, "result": [{
            "meta": {"longName": "Example ETF", "currency": "USD", "exchangeName": "NYSE"},
            "timestamp": [1704067200, 1704153600],
            "indicators": {
                "quote": [{
                    "open": [100, 102], "high": [105, 106], "low": [98, 100],
                    "close": [100, 104], "volume": [1000, 1200],
                }],
                "adjclose": [{"adjclose": [50, 52]}],
            },
        }]},
    }

    def opener(_request, timeout):
        assert timeout == 20
        return io.BytesIO(json.dumps(payload).encode())

    source = YahooChartDataSource("TEST", opener=opener)
    frame = source.get_daily("2024-01-01", "2024-01-02")
    assert frame["close"].tolist() == [50.0, 52.0]
    assert frame["open"].tolist() == [50.0, 51.0]
    assert source.metadata["longName"] == "Example ETF"


class FakeGateway:
    def __init__(self):
        self.last_close = 119

    def fetch(self, online_type, provider_code, start_date, end_date=None):
        assert online_type == "yahoo"
        assert provider_code == "TEST"
        frame = pd.DataFrame({
            "date": pd.date_range(start_date, periods=20),
            "close": list(range(100, 119)) + [self.last_close],
        })
        return frame, {
            "name": "测试资产", "currency": "USD", "market": "NYSE",
            "asset_class": "stock", "adjustment": "adjusted",
        }, "Fake Yahoo", ("Fake Yahoo：成功",)


def test_online_manager_adds_and_refreshes_persistent_instrument(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    custom = CustomInstrumentManager()
    gateway = FakeGateway()
    manager = OnlineCustomInstrumentManager(custom, gateway)
    result = manager.add(
        online_type="yahoo", provider_code="TEST", symbol="test_asset",
        start_date="2024-01-01",
    )
    assert result.instrument.online_source == "yahoo"
    assert result.instrument.provider_code == "TEST"
    assert result.rows == 20

    gateway.last_close = 130
    refreshed = manager.refresh("test_asset", catalog=InstrumentCatalog())
    assert refreshed.last_date == "2024-01-20"
    assert pd.read_csv(refreshed.instrument.data_path).iloc[-1]["close"] == 130

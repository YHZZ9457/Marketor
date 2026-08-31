from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

from .akshare_source import _akshare_client, _normalize_frame
from .base import MarketDataSource


class AKShareCNStockTencentDataSource(MarketDataSource):
    def __init__(self, symbol: str, client: Any | None = None, *, adjust: str = "qfq"):
        self.symbol = symbol
        self.client = _akshare_client(client)
        self.adjust = adjust

    def get_daily(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        raw = self.client.stock_zh_a_hist_tx(
            symbol=self.symbol,
            start_date=pd.Timestamp(start_date or "1990-01-01").strftime("%Y%m%d"),
            end_date=pd.Timestamp(end_date or "2050-01-01").strftime("%Y%m%d"),
            adjust=self.adjust,
        )
        frame = _normalize_frame(raw, f"AKShare/Tencent stock {self.symbol}")
        columns = ["date", "open", "high", "low", "close"]
        if "amount" in frame:
            columns.append("amount")
        columns.append("daily_return")
        return frame[columns]


class AKShareCNStockEastMoneyDataSource(MarketDataSource):
    def __init__(self, symbol: str, client: Any | None = None, *, adjust: str = "qfq"):
        self.symbol = symbol
        self.client = _akshare_client(client)
        self.adjust = adjust

    def get_daily(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        raw = self.client.stock_zh_a_hist(
            symbol=self.symbol,
            period="daily",
            start_date=pd.Timestamp(start_date or "1990-01-01").strftime("%Y%m%d"),
            end_date=pd.Timestamp(end_date or "2050-01-01").strftime("%Y%m%d"),
            adjust=self.adjust,
            timeout=15,
        )
        frame = _normalize_frame(raw, f"AKShare/EastMoney stock {self.symbol}")
        columns = ["date", "open", "high", "low", "close"]
        if "amount" in frame:
            columns.append("amount")
        columns.append("daily_return")
        return frame[columns]


class AKShareOpenFundDataSource(MarketDataSource):
    def __init__(self, symbol: str, client: Any | None = None):
        self.symbol = symbol
        self.client = _akshare_client(client)

    def get_daily(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        raw = self.client.fund_open_fund_info_em(symbol=self.symbol, indicator="单位净值走势")
        if raw is None or raw.empty:
            raise RuntimeError(f"东方财富未返回基金 {self.symbol} 的单位净值")
        frame = raw.rename(columns={"净值日期": "date", "单位净值": "close"}).copy()
        if not {"date", "close"} <= set(frame.columns):
            raise RuntimeError(f"东方财富基金响应缺少日期或单位净值字段：{list(raw.columns)}")
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date", keep="last")
        if start_date:
            frame = frame[frame["date"] >= pd.Timestamp(start_date)]
        if end_date:
            frame = frame[frame["date"] <= pd.Timestamp(end_date)]
        frame = frame.reset_index(drop=True)
        frame["daily_return"] = frame["close"].pct_change()
        return frame[["date", "close", "daily_return"]]


class YahooChartDataSource(MarketDataSource):
    BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"

    def __init__(self, symbol: str, *, timeout: int = 20, opener: Any | None = None):
        self.symbol = symbol.strip()
        self.timeout = timeout
        self.opener = opener or urlopen
        self.metadata: dict[str, Any] = {}

    def get_daily(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        start = pd.Timestamp(start_date or "1970-01-01", tz="UTC")
        end = pd.Timestamp(end_date or pd.Timestamp.now().date(), tz="UTC") + pd.Timedelta(days=1)
        url = (
            f"{self.BASE_URL}{quote(self.symbol, safe='')}?"
            f"period1={int(start.timestamp())}&period2={int(end.timestamp())}"
            "&interval=1d&events=div%2Csplits&includeAdjustedClose=true"
        )
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 Marketor/0.14"})
        try:
            response = self.opener(request, timeout=self.timeout)
            payload = json.load(response)
        except Exception as exc:
            raise RuntimeError(f"Yahoo Finance 查询 {self.symbol} 失败：{exc}") from exc
        chart = payload.get("chart", {})
        if chart.get("error"):
            raise RuntimeError(f"Yahoo Finance 查询失败：{chart['error']}")
        results = chart.get("result") or []
        if not results:
            raise RuntimeError(f"Yahoo Finance 未返回 {self.symbol} 日线数据")
        result = results[0]
        self.metadata = dict(result.get("meta") or {})
        timestamps = result.get("timestamp") or []
        indicators = result.get("indicators") or {}
        quotes = (indicators.get("quote") or [{}])[0]
        adjusted = (indicators.get("adjclose") or [{}])[0].get("adjclose") or quotes.get("close") or []
        rows: list[dict[str, Any]] = []
        for index, stamp in enumerate(timestamps):
            raw_close = self._at(quotes.get("close"), index)
            adjusted_close = self._at(adjusted, index)
            if raw_close in (None, 0) or adjusted_close is None:
                continue
            factor = float(adjusted_close) / float(raw_close)
            row = {
                "date": datetime.fromtimestamp(stamp, tz=timezone.utc).date(),
                "close": float(adjusted_close),
            }
            for column in ("open", "high", "low"):
                value = self._at(quotes.get(column), index)
                if value is not None:
                    row[column] = float(value) * factor
            rows.append(row)
        frame = pd.DataFrame(rows)
        if frame.empty:
            raise RuntimeError(f"Yahoo Finance 未返回 {self.symbol} 有效日线数据")
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
        frame["daily_return"] = frame["close"].pct_change()
        return frame

    @staticmethod
    def _at(values: Any, index: int) -> Any:
        return values[index] if values is not None and index < len(values) else None

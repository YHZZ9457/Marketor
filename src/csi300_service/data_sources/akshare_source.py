from __future__ import annotations

from typing import Any

import pandas as pd

from .base import MarketDataSource


def _akshare_client(client: Any | None) -> Any:
    if client is not None:
        return client
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("未安装 AKShare；请运行 pip install akshare") from exc
    return ak


def _normalize_frame(raw: pd.DataFrame, source_name: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise RuntimeError(f"{source_name} 未返回指数日线数据")
    aliases = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交额": "amount"}
    frame = raw.rename(columns=aliases).copy()
    required = {"date", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"{source_name} 响应缺少字段：{sorted(missing)}")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    for column in ("open", "high", "low", "close", "amount"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    frame["daily_return"] = frame["close"].pct_change()
    return frame


class AKShareIndexZHHistDataSource(MarketDataSource):
    """AKShare adapter for EastMoney index history via code-only lookup.

    Uses ``ak.index_zh_a_hist(symbol=<plain 6-digit code>)`` so the market
    (SH / SZ / CSI / BJ) is resolved by AKShare itself instead of a hand-written
    prefix. When the code is not in that universe, falls back to the prefixed
    ``stock_zh_index_daily_em`` adapter for the same underlying host.
    """

    def __init__(
        self,
        symbol: str,
        eastmoney_code: str | None = None,
        amount_unit: str = "CNY_THOUSAND",
        client: Any | None = None,
    ):
        self.symbol = symbol
        self.eastmoney_code = eastmoney_code
        self.amount_unit = amount_unit
        self.client = _akshare_client(client)

    def get_daily(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        start = pd.Timestamp(start_date or "1990-01-01").strftime("%Y%m%d")
        end = pd.Timestamp(end_date or "2050-01-01").strftime("%Y%m%d")
        try:
            raw = self.client.index_zh_a_hist(symbol=self.symbol, start_date=start, end_date=end)
            frame = _normalize_frame(raw, f"AKShare/EastMoney(index_zh_a_hist) {self.symbol}")
        except Exception as exc:
            if not self.eastmoney_code:
                raise RuntimeError(
                    f"index_zh_a_hist 查询失败且未配置东方财富备用代码：{exc}"
                ) from exc
            raw = self.client.stock_zh_index_daily_em(
                symbol=self.eastmoney_code, start_date=start, end_date=end
            )
            frame = _normalize_frame(raw, f"AKShare/EastMoney {self.eastmoney_code}")
        columns = ["date", "open", "high", "low", "close"]
        if self.amount_unit == "CNY_THOUSAND" and "amount" in frame.columns:
            frame["amount"] = frame["amount"] / 1000.0
            columns.append("amount")
        columns.append("daily_return")
        return frame[columns]


class AKShareTencentDataSource(MarketDataSource):
    """AKShare adapter for Tencent index history.

    Tencent's ``amount`` field is documented as lots, so it is retained only
    for instruments whose catalog unit is explicitly ``LOTS``.
    """

    def __init__(self, symbol: str, amount_unit: str = "CNY_THOUSAND", client: Any | None = None):
        self.symbol = symbol
        self.amount_unit = amount_unit
        self.client = _akshare_client(client)

    def get_daily(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        raw = self.client.stock_zh_index_daily_tx(
            symbol=self.symbol,
            start_date=pd.Timestamp(start_date or "1990-01-01").strftime("%Y%m%d"),
            end_date=pd.Timestamp(end_date or "2050-01-01").strftime("%Y%m%d"),
        )
        frame = _normalize_frame(raw, f"AKShare/Tencent {self.symbol}")
        columns = ["date", "open", "high", "low", "close"]
        if self.amount_unit == "LOTS" and "amount" in frame.columns:
            columns.append("amount")
        columns.append("daily_return")
        return frame[columns]


class AKShareEastMoneyDataSource(MarketDataSource):
    """AKShare adapter for EastMoney index history."""

    def __init__(self, symbol: str, amount_unit: str = "CNY_THOUSAND", client: Any | None = None):
        self.symbol = symbol
        self.amount_unit = amount_unit
        self.client = _akshare_client(client)

    def get_daily(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        raw = self.client.stock_zh_index_daily_em(
            symbol=self.symbol,
            start_date=pd.Timestamp(start_date or "1990-01-01").strftime("%Y%m%d"),
            end_date=pd.Timestamp(end_date or "2050-01-01").strftime("%Y%m%d"),
        )
        frame = _normalize_frame(raw, f"AKShare/EastMoney {self.symbol}")
        columns = ["date", "open", "high", "low", "close"]
        if self.amount_unit == "CNY_THOUSAND" and "amount" in frame.columns:
            frame["amount"] = frame["amount"] / 1000.0
            columns.append("amount")
        columns.append("daily_return")
        return frame[columns]

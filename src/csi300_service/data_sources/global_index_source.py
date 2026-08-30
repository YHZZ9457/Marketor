from __future__ import annotations

from typing import Any

import numpy as np
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


def _normalize_global_frame(
    raw: pd.DataFrame,
    aliases: dict[str, str],
    start_date: str | None,
    end_date: str | None,
) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise RuntimeError("全球指数数据源未返回日线数据")
    frame = raw.rename(columns=aliases).copy()
    required = {"date", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"全球指数响应缺少字段：{sorted(missing)}")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "open", "high", "low", "close"])
    frame = frame.loc[(frame[["open", "high", "low", "close"]] > 0).all(axis=1)].copy()
    # A few global-provider rows publish an intraday low/high that omits the
    # opening auction. Repair only small (<1%) envelope gaps; reject larger ones.
    upper = frame[["open", "close"]].max(axis=1)
    lower = frame[["open", "close"]].min(axis=1)
    high_gap = (upper - frame["high"]).clip(lower=0)
    low_gap = (frame["low"] - lower).clip(lower=0)
    maximum_gap = frame["close"].abs() * 0.02
    severe = (high_gap > maximum_gap) | (low_gap > maximum_gap)
    if severe.mean() > 0.005:
        raise RuntimeError("全球指数源超过 0.5% 的记录存在严重 OHLC 异常，已拒绝导入")
    frame = frame.loc[~severe].copy()
    upper = frame[["open", "close"]].max(axis=1)
    lower = frame[["open", "close"]].min(axis=1)
    frame["high"] = pd.concat([frame["high"], upper], axis=1).max(axis=1)
    frame["low"] = pd.concat([frame["low"], lower], axis=1).min(axis=1)
    if start_date:
        frame = frame.loc[frame["date"] >= pd.Timestamp(start_date)]
    if end_date:
        frame = frame.loc[frame["date"] <= pd.Timestamp(end_date)]
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    frame["amount"] = np.nan
    frame["daily_return"] = frame["close"].pct_change()
    return frame[["date", "open", "high", "low", "close", "amount", "daily_return"]]


class AKShareGlobalEastMoneyDataSource(MarketDataSource):
    """东方财富全球指数日线，symbol 使用其中文指数名称。"""

    def __init__(self, symbol: str, client: Any | None = None):
        self.symbol = symbol
        self.client = _akshare_client(client)

    def get_daily(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        raw = self.client.index_global_hist_em(symbol=self.symbol)
        return _normalize_global_frame(
            raw,
            {"日期": "date", "今开": "open", "最高": "high", "最低": "low", "最新价": "close"},
            start_date,
            end_date,
        )


class AKShareUSIndexSinaDataSource(MarketDataSource):
    """新浪美股指数完整历史，支持 .INX/.NDX/.DJI/.IXIC。"""

    def __init__(self, symbol: str, client: Any | None = None):
        self.symbol = symbol
        self.client = _akshare_client(client)

    def get_daily(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        raw = self.client.index_us_stock_sina(symbol=self.symbol)
        return _normalize_global_frame(raw, {}, start_date, end_date)


class AKShareGlobalSinaDataSource(MarketDataSource):
    """新浪环球市场最近约 1000 个交易日，作为全球东财的备用源。"""

    def __init__(self, symbol: str, client: Any | None = None):
        self.symbol = symbol
        self.client = _akshare_client(client)

    def get_daily(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        raw = self.client.index_global_hist_sina(symbol=self.symbol)
        return _normalize_global_frame(raw, {}, start_date, end_date)


class AKShareHKIndexSinaDataSource(MarketDataSource):
    """新浪港股指数完整历史，如 HSI/HSTECH。"""

    def __init__(self, symbol: str, client: Any | None = None):
        self.symbol = symbol
        self.client = _akshare_client(client)

    def get_daily(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        raw = self.client.stock_hk_index_daily_sina(symbol=self.symbol)
        return _normalize_global_frame(raw, {}, start_date, end_date)

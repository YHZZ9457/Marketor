from __future__ import annotations

import os
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from .base import MarketDataSource


class TushareDataSource(MarketDataSource):
    """Tushare Pro index_daily adapter using canonical decimal returns.

    Tushare's amount is retained in its documented unit: CNY thousands.
    """

    def __init__(self, ts_code: str = "000300.SH", token: str | None = None, client: Any | None = None):
        self.ts_code = ts_code
        if client is not None:
            self.pro = client
            return
        load_dotenv()
        token = token or os.getenv("TUSHARE_TOKEN")
        if not token:
            raise RuntimeError("缺少 TUSHARE_TOKEN；请在 .env 或系统环境变量中配置")
        try:
            import tushare as ts
        except ImportError as exc:
            raise RuntimeError("未安装 tushare；请运行 pip install tushare") from exc
        self.pro = ts.pro_api(token)

    def get_daily(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        kwargs: dict[str, str] = {"ts_code": self.ts_code}
        if start_date:
            kwargs["start_date"] = pd.Timestamp(start_date).strftime("%Y%m%d")
        if end_date:
            kwargs["end_date"] = pd.Timestamp(end_date).strftime("%Y%m%d")
        raw = self.pro.index_daily(**kwargs)
        if raw is None or raw.empty:
            raise RuntimeError(f"Tushare 未返回 {self.ts_code} 指数日线数据")
        required = {"trade_date", "open", "high", "low", "close", "amount", "pct_chg"}
        missing = required - set(raw.columns)
        if missing:
            raise RuntimeError(f"Tushare 响应缺少字段：{sorted(missing)}")
        frame = raw.rename(columns={"trade_date": "date"}).copy()
        frame["date"] = pd.to_datetime(frame["date"], format="%Y%m%d", errors="raise")
        for column in ("open", "high", "low", "close", "amount", "pct_chg"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["daily_return"] = frame["pct_chg"] / 100.0
        return (
            frame[["date", "open", "high", "low", "close", "amount", "daily_return"]]
            .sort_values("date")
            .reset_index(drop=True)
        )

from __future__ import annotations

from datetime import date
import json
import os
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .base import MarketDataSource


HITHINK_API_KEY_ENV = "HITHINK_FINANCE_API_KEY"


def hithink_api_key() -> str | None:
    """Return the configured key without ever logging or serializing it."""
    value = os.getenv(HITHINK_API_KEY_ENV, "").strip()
    return value or None


def normalize_hithink_code(value: str) -> str:
    """Normalize common Chinese-market codes to a HiThink thscode."""
    raw = value.strip().upper()
    if "." in raw:
        left, right = raw.split(".", 1)
        if right in {"SH", "SZ", "BJ", "TI", "CSI"}:
            return f"{left}.{right}"
        if left in {"SH", "SZ", "BJ"}:
            return f"{right}.{left}"
    compact = raw.replace(".", "")
    if compact[:2] in {"SH", "SZ", "BJ"}:
        return f"{compact[2:]}.{compact[:2]}"
    if len(compact) != 6 or not compact.isdigit():
        raise ValueError("同花顺代码应为 6 位代码或完整 thscode，例如 600519、000300.SH")
    market = "SH" if compact[0] in "569" else "BJ" if compact[0] in "48" else "SZ"
    return f"{compact}.{market}"


class HiThinkDataSource(MarketDataSource):
    """Official HiThink REST adapter for Chinese stocks, indices and ETFs."""

    ENDPOINTS = {
        "stock": "/api/a-share/prices/historical",
        "index": "/api/a-share-index/prices/historical",
        "etf": "/api/fund/market/historical",
    }
    MAX_WINDOW_DAYS = {"stock": 3650, "index": 3650, "etf": 1825}

    def __init__(
        self,
        code: str,
        *,
        asset_type: str = "index",
        api_key: str | None = None,
        amount_scale: float = 1.0,
        opener: Callable[..., Any] | None = None,
        base_url: str = "https://fuyao.aicubes.cn",
    ):
        if asset_type not in self.ENDPOINTS:
            raise ValueError("asset_type 必须是 stock、index 或 etf")
        self.code = normalize_hithink_code(code)
        self.asset_type = asset_type
        self.api_key = (api_key or hithink_api_key() or "").strip()
        self.amount_scale = float(amount_scale)
        self.opener = opener or urlopen
        self.base_url = base_url.rstrip("/")

    def get_daily(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        if not self.api_key:
            raise RuntimeError(f"未配置 {HITHINK_API_KEY_ENV}")
        start = pd.Timestamp(start_date or "2005-01-01").normalize()
        end = pd.Timestamp(end_date or date.today().isoformat()).normalize()
        if start > end:
            raise ValueError("起始日期不能晚于结束日期")

        frames: list[pd.DataFrame] = []
        cursor = start
        window = pd.Timedelta(days=self.MAX_WINDOW_DAYS[self.asset_type] - 1)
        while cursor <= end:
            chunk_end = min(cursor + window, end)
            frames.append(self._fetch_chunk(cursor, chunk_end))
            cursor = chunk_end + pd.Timedelta(days=1)
        if not frames:
            raise RuntimeError(f"同花顺未返回 {self.code} 日线数据")
        frame = pd.concat(frames, ignore_index=True)
        frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
        if frame.empty:
            raise RuntimeError(f"同花顺未返回 {self.code} 日线数据")
        frame["daily_return"] = frame["close"].pct_change()
        return frame[["date", "open", "high", "low", "close", "amount", "daily_return"]]

    def _fetch_chunk(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        params: dict[str, str | int] = {
            "thscode": self.code,
            "interval": "1d",
            "start": int(start.tz_localize("Asia/Shanghai").timestamp() * 1000),
            "end": int((end + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)).tz_localize("Asia/Shanghai").timestamp() * 1000),
        }
        if self.asset_type == "stock":
            params["adjust"] = "forward"
        url = f"{self.base_url}{self.ENDPOINTS[self.asset_type]}?{urlencode(params)}"
        request = Request(url, headers={"X-api-key": self.api_key, "Accept": "application/json"})
        try:
            response = self.opener(request, timeout=25)
            payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"同花顺查询 {self.code} 失败：{exc}") from exc
        if payload.get("code") != 0:
            message = payload.get("message") or "未知错误"
            raise RuntimeError(f"同花顺查询失败（code={payload.get('code')}）：{message}")
        items = (payload.get("data") or {}).get("item") or []
        if not items:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "amount"])
        frame = pd.DataFrame(items).rename(columns={
            "date_ms": "date", "open_price": "open", "high_price": "high",
            "low_price": "low", "close_price": "close", "turnover": "amount",
        })
        required = {"date", "open", "high", "low", "close"}
        if not required <= set(frame.columns):
            raise RuntimeError(f"同花顺返回字段不完整：缺少 {sorted(required - set(frame.columns))}")
        dates = pd.to_datetime(frame["date"], unit="ms", utc=True, errors="coerce")
        frame["date"] = dates.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None).dt.normalize()
        for column in ["open", "high", "low", "close", "amount"]:
            if column not in frame:
                frame[column] = pd.NA
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["amount"] = frame["amount"] * self.amount_scale
        return frame.dropna(subset=["date", "close"])[["date", "open", "high", "low", "close", "amount"]]

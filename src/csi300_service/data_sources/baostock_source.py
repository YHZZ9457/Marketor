from __future__ import annotations

from typing import Any

import pandas as pd

from .base import MarketDataSource


class BaoStockDataSource(MarketDataSource):
    """BaoStock daily-index adapter.

    BaoStock returns amount in CNY yuan; the adapter converts it to the
    project's canonical CSI 300 unit, CNY thousands.
    """

    FIELDS = "date,open,high,low,close,volume,amount,pctChg"

    def __init__(self, code: str = "sh.000300", client: Any | None = None):
        self.code = code
        if client is None:
            try:
                import baostock as bs
            except ImportError as exc:
                raise RuntimeError("未安装 baostock；请运行 pip install baostock") from exc
            client = bs
        self.client = client

    def get_daily(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        login = self.client.login()
        if str(login.error_code) != "0":
            raise RuntimeError(f"BaoStock 登录失败：{login.error_msg}")
        try:
            rows: list[list[str]] = []
            fields: list[str] = []
            ranges = self._date_ranges(start_date, end_date)
            for range_start, range_end in ranges:
                result = self.client.query_history_k_data_plus(
                    self.code,
                    self.FIELDS,
                    start_date=range_start,
                    end_date=range_end,
                    frequency="d",
                    adjustflag="3",
                )
                if str(result.error_code) != "0":
                    raise RuntimeError(f"BaoStock 查询失败：{result.error_msg}")
                fields = result.fields
                while result.next():
                    rows.append(result.get_row_data())
            if not rows:
                raise RuntimeError(f"BaoStock 未返回 {self.code} 指数日线数据")
            frame = pd.DataFrame(rows, columns=fields)
        finally:
            self.client.logout()

        frame["date"] = pd.to_datetime(frame["date"], errors="raise")
        for column in ("open", "high", "low", "close", "amount", "pctChg"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["amount"] = frame["amount"] / 1000.0
        frame["daily_return"] = frame["pctChg"] / 100.0
        return (
            frame[["date", "open", "high", "low", "close", "amount", "daily_return"]]
            .sort_values("date")
            .reset_index(drop=True)
        )

    @staticmethod
    def _date_ranges(start_date: str | None, end_date: str | None) -> list[tuple[str, str]]:
        if not start_date or not end_date:
            return [(start_date or "", end_date or "")]
        start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
        ranges: list[tuple[str, str]] = []
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + pd.DateOffset(years=4) - pd.Timedelta(days=1), end)
            ranges.append((cursor.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))
            cursor = chunk_end + pd.Timedelta(days=1)
        return ranges

from __future__ import annotations

import pandas as pd


OHLC_COLUMNS = ("open", "high", "low", "close")


def validate_market_data(frame: pd.DataFrame, price_tolerance: float = 0.05) -> None:
    """Reject invalid daily bars before they can reach the historical CSV."""
    required = {"date", *OHLC_COLUMNS}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"行情数据缺少字段：{sorted(missing)}")
    if frame.empty:
        raise ValueError("行情数据为空")
    if frame[list(required)].isna().any().any():
        raise ValueError("行情日期或 OHLC 存在空值")
    if not frame["date"].is_monotonic_increasing:
        raise ValueError("行情日期必须按升序排列")
    if frame["date"].duplicated().any():
        duplicates = frame.loc[frame["date"].duplicated(keep=False), "date"].dt.strftime("%Y-%m-%d").unique()
        raise ValueError(f"行情日期重复：{', '.join(duplicates[:5])}")
    if (frame["close"] <= 0).any():
        raise ValueError("收盘价必须大于 0")
    # BaoStock has a handful of historical index bars where OHLC rounding differs
    # by less than one basis point. Permit only that immaterial provider tolerance.
    row_tolerance = frame["close"].abs().mul(0.0001).clip(lower=price_tolerance)
    if (frame["high"] + row_tolerance < frame["low"]).any():
        raise ValueError("存在最高价低于最低价的记录")
    if (frame["high"] + row_tolerance < frame[["open", "close"]].max(axis=1)).any():
        raise ValueError("存在最高价低于开盘价或收盘价的记录")
    if (frame["low"] - row_tolerance > frame[["open", "close"]].min(axis=1)).any():
        raise ValueError("存在最低价高于开盘价或收盘价的记录")

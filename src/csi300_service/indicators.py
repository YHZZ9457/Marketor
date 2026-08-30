from __future__ import annotations

import numpy as np
import pandas as pd

MA_WINDOWS = (5, 10, 20, 60, 180, 250, 500, 1250)


def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return rsi


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for window in MA_WINDOWS:
        ma = out["close"].rolling(window, min_periods=window).mean()
        out[f"ma{window}"] = ma
        out[f"bias{window}"] = out["close"] / ma - 1
    out["rsi14"] = wilder_rsi(out["close"], 14)
    out["rsi_cross_down_75"] = (out["rsi14"].shift(1) >= 75) & (out["rsi14"] < 75)
    out["rsi_cross_down_70"] = (out["rsi14"].shift(1) >= 70) & (out["rsi14"] < 70)
    out["ret_5d"] = out["close"].pct_change(5)
    out["ret_20d"] = out["close"].pct_change(20)
    out["drawdown_250d"] = out["close"] / out["close"].rolling(250, min_periods=1).max() - 1
    return out

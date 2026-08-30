from __future__ import annotations

from pathlib import Path

import pandas as pd

from .catalog import default_data_dir

REQUIRED_COLUMNS = {"date", "close"}


def default_data_path() -> Path:
    return default_data_dir() / "csi300.csv"


def load_data(path: str | Path | None = None) -> pd.DataFrame:
    source = Path(path) if path else default_data_path()
    df = pd.read_csv(source)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="raise")
    df = df.sort_values("date").reset_index(drop=True)
    if df["date"].duplicated().any():
        duplicates = df.loc[df["date"].duplicated(keep=False), "date"].dt.strftime("%Y-%m-%d").unique()
        raise ValueError(f"CSV contains duplicate dates: {', '.join(duplicates[:5])}")
    for col in ["open", "high", "low", "close", "amount", "daily_return", "return", "net_value"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "daily_return" not in df.columns and "return" in df.columns:
        df["daily_return"] = df["return"]
    if "return" not in df.columns and "daily_return" in df.columns:
        df["return"] = df["daily_return"]
    if df["close"].isna().any() or (df["close"] <= 0).any():
        raise ValueError("close must contain only positive numeric values")
    if df.empty:
        raise ValueError("CSV contains no market data")
    return df

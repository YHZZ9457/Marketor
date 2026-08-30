from __future__ import annotations

from pathlib import Path

import pandas as pd

from .base import MarketDataSource
from ..data import load_data


class CsvDataSource(MarketDataSource):
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def get_daily(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        frame = load_data(self.path)
        if start_date:
            frame = frame[frame["date"] >= pd.Timestamp(start_date)]
        if end_date:
            frame = frame[frame["date"] <= pd.Timestamp(end_date)]
        return frame.reset_index(drop=True)

from __future__ import annotations

from typing import Iterable
import pandas as pd

from .catalog import Instrument, InstrumentCatalog
from .data import load_data
from .indicators import add_indicators
from .statistics import statistics_methods, summarize_returns
from .strategy import evaluate


class MarketService:
    def __init__(
        self,
        symbol: str = "csi300",
        path=None,
        *,
        catalog: InstrumentCatalog | None = None,
    ):
        self.catalog = catalog or InstrumentCatalog()
        if path is None:
            self.instrument = self.catalog.get(symbol)
            data_path = self.instrument.data_path
        else:
            self.instrument = Instrument(symbol=symbol.lower(), name=symbol, data_path=path)
            data_path = path
        self.df = add_indicators(load_data(data_path))

    def metadata(self) -> dict:
        return {
            **self.instrument.to_dict(),
            "first_date": self.df.iloc[0]["date"].strftime("%Y-%m-%d"),
            "last_date": self.df.iloc[-1]["date"].strftime("%Y-%m-%d"),
            "rows": len(self.df),
        }

    def latest(self) -> dict:
        row = self.df.iloc[-1]
        return self._row_to_dict(row)

    def indicators(self, days: int = 30) -> list[dict]:
        days = max(1, min(days, 1000))
        cols = ["date", "close", "ma60", "ma250", "ma500", "ma1250", "bias60", "bias180", "bias250", "bias500", "bias1250", "rsi14", "drawdown_250d", "ret_20d"]
        return [self._row_to_dict(row[cols]) for _, row in self.df.tail(days).iterrows()]

    def history(self, start: str | None = None, end: str | None = None, limit: int = 5000) -> list[dict]:
        df = self.df
        if start:
            df = df[df["date"] >= pd.Timestamp(start)]
        if end:
            df = df[df["date"] <= pd.Timestamp(end)]
        df = df.tail(max(1, min(limit, 10000)))
        cols = [c for c in ["date", "open", "high", "low", "close", "amount", "daily_return", "return", "net_value"] if c in df.columns]
        return [self._row_to_dict(row[cols]) for _, row in df.iterrows()]

    def signal(self) -> dict:
        latest = self._row_to_dict(self.df.iloc[-1])
        previous = self._row_to_dict(self.df.iloc[-2]) if len(self.df) > 1 else None
        return evaluate(latest, previous)

    def holding_returns(
        self,
        calendar_days: Iterable[int] = (1, 7, 30, 365, 730, 1095, 1825),
        method: str = "summary",
    ) -> list[dict]:
        if method.strip().lower() not in statistics_methods():
            raise ValueError(
                f"Unknown statistics method {method!r}; available: {', '.join(statistics_methods())}"
            )
        df = self.df[["date", "close"]].copy().reset_index(drop=True)
        dates = df["date"].values.astype("datetime64[ns]")
        close = df["close"].to_numpy()
        rows = []
        for days in calendar_days:
            if days <= 0:
                raise ValueError("Holding periods must be positive calendar days")
            target = (df["date"] + pd.to_timedelta(days, unit="D")).values.astype("datetime64[ns]")
            idx = dates.searchsorted(target, side="left")
            valid = idx < len(df)
            if not valid.any():
                rows.append({"days": int(days), "samples": 0})
                continue
            ret = close[idx[valid]] / close[valid] - 1
            rows.append({"days": int(days), "samples": int(valid.sum()), **summarize_returns(ret, method)})
        return rows

    @staticmethod
    def _row_to_dict(row: pd.Series) -> dict:
        out = {}
        for k, v in row.items():
            if isinstance(v, pd.Timestamp):
                out[k] = v.strftime("%Y-%m-%d")
            elif pd.isna(v):
                out[k] = None
            elif hasattr(v, "item"):
                out[k] = v.item()
            else:
                out[k] = v
        return out


class CSI300Service(MarketService):
    """Backward-compatible facade for existing imports and callers."""

    def __init__(self, path=None):
        super().__init__("csi300", path)

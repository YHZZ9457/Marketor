from __future__ import annotations

from typing import Iterable
import pandas as pd

from .catalog import Instrument, InstrumentCatalog
from .data import load_data
from .indicators import add_indicators
from .statistics import statistics_methods, summarize_returns
from .strategy import evaluate, evaluate_adaptive, daily_reference
from .ai_strategy import load_strategy_profile


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
        start_date = pd.Timestamp(start) if start else None
        end_date = pd.Timestamp(end) if end else None
        for value in (start_date, end_date):
            if value is not None and (pd.isna(value) or value.tzinfo is not None or value != value.normalize()):
                raise ValueError("日期必须是无时区的有效日期（YYYY-MM-DD）")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("起始日期不能晚于截止日期")
        if start_date is not None:
            df = df[df["date"] >= start_date]
        if end_date is not None:
            df = df[df["date"] <= end_date]
        df = df.tail(max(1, min(limit, 10000)))
        cols = [c for c in ["date", "open", "high", "low", "close", "amount", "daily_return", "return", "net_value"] if c in df.columns]
        return [self._row_to_dict(row[cols]) for _, row in df.iterrows()]

    def signal(self, equity: float = 10000.0) -> dict:
        latest = self._row_to_dict(self.df.iloc[-1])
        previous = self._row_to_dict(self.df.iloc[-2]) if len(self.df) > 1 else None
        profile = load_strategy_profile(self.instrument.symbol)
        if self.instrument.asset_class != "index" and profile is not None and profile.active:
            return evaluate_adaptive(latest, profile.to_dict(), previous)
        result = evaluate(latest, previous)
        result["model_policy"] = "所有指数暂时统一V1；已保存的AI配置不覆盖指数信号"
        result["daily_reference"] = daily_reference(latest, equity)
        return result

    def ma_dynamic(self, start: str | None = None, end: str | None = None,
                   include_ledger: bool = True) -> dict:
        from .ma_dynamic import STRATEGY_ID, STRATEGY_NAME, RULES, backtest, load_total_return
        instrument = self.instrument
        base = {"strategy_id": STRATEGY_ID, "name": STRATEGY_NAME,
                "symbol": instrument.symbol, "rules": RULES}
        if STRATEGY_ID not in instrument.strategies:
            return {**base, "status": "unsupported", "message": "该指数未启用此策略"}
        latest = self.latest()
        base["entry_eligible_today"] = (latest.get("ma500") is not None
                                        and latest["close"] <= latest["ma500"] * 1.10)
        base["total_return_code"] = instrument.total_return_code
        if not instrument.total_return_code or not instrument.total_return_file:
            return {**base, "status": "data_unavailable", "message": "尚未配置全收益指数"}
        try:
            tri, provenance = load_total_return(
                self.catalog.config_path.parent.resolve() / instrument.total_return_file,
                instrument.total_return_code)
        except (ValueError, OSError) as exc:
            return {**base, "status": "data_unavailable", "message": str(exc)}
        result = backtest(self.df, tri, start, end)
        if not include_ledger:
            result.pop("ledger")
        return {**base, **result, "source": provenance}

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

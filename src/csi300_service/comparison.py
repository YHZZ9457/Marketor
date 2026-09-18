from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .catalog import InstrumentCatalog
from .service import MarketService
from .strategy import daily_reference


def _percentile(series: pd.Series, value: float | None) -> float | None:
    clean = series.dropna()
    if value is None or not len(clean) or pd.isna(value):
        return None
    return float((clean <= value).mean() * 100)


def _score_label(score: int, side: str) -> str:
    if side == "buy":
        levels = ((85, "极端区域"), (70, "重度加仓"), (50, "明显加仓"), (30, "轻度加仓"), (0, "正常"))
    else:
        levels = ((85, "极端过热"), (70, "重度减仓"), (50, "明显减仓"), (30, "轻度减仓"), (0, "正常"))
    return next(label for threshold, label in levels if score >= threshold)


def allocation_scores(latest: dict[str, Any]) -> tuple[int, int]:
    """Independent 0-100 allocation scores; existing strategy rules remain unchanged."""
    b250, b500, b1250 = latest.get("bias250"), latest.get("bias500"), latest.get("bias1250")
    rsi, drawdown = latest.get("rsi14"), latest.get("drawdown_250d")
    buy = 0
    if b250 is not None:
        buy += 15 if b250 <= -0.05 else 0
        buy += 15 if b250 <= -0.10 else 0
        buy += 15 if b250 <= -0.15 else 0
    if rsi is not None:
        buy += 10 if rsi < 35 else 0
        buy += 10 if rsi < 30 else 0
    buy += 15 if drawdown is not None and drawdown <= -0.20 else 0
    buy += 20 if b1250 is not None and b1250 <= -0.10 else 0

    sell = 0
    if b500 is not None:
        sell += 15 if b500 >= 0.10 else 0
        sell += 15 if b500 >= 0.15 else 0
        sell += 15 if b500 >= 0.20 else 0
    if rsi is not None:
        sell += 10 if rsi >= 65 else 0
        sell += 10 if rsi >= 70 else 0
    sell += 15 if drawdown is not None and drawdown >= -0.05 else 0
    sell += 20 if b1250 is not None and b1250 >= 0.20 else 0
    return min(buy, 100), min(sell, 100)


def instrument_snapshot(service: MarketService) -> dict[str, Any]:
    frame = service.df
    latest = service.latest()
    close = frame["close"]
    returns = close.pct_change()
    bias250_pct = _percentile(frame["bias250"], latest.get("bias250"))
    bias500_pct = _percentile(frame["bias500"], latest.get("bias500"))
    rsi_pct = _percentile(frame["rsi14"], latest.get("rsi14"))
    drawdown_pct = _percentile(frame["drawdown_250d"], latest.get("drawdown_250d"))
    percentiles = [value for value in (bias250_pct, bias500_pct, rsi_pct, drawdown_pct) if value is not None]
    relative_value = float(sum(100 - value for value in percentiles) / len(percentiles)) if percentiles else 0.0
    buy_score, sell_score = allocation_scores(latest)
    ranking_score = round(max(0.0, min(100.0, relative_value * 0.6 + buy_score * 0.6 - sell_score * 0.4)), 2)
    return {
        "symbol": service.instrument.symbol,
        "name": service.instrument.name,
        "date": latest["date"],
        "daily_reference": daily_reference(latest),
        "close": latest["close"],
        "bias250": latest.get("bias250"),
        "bias500": latest.get("bias500"),
        "bias1250": latest.get("bias1250"),
        "rsi14": latest.get("rsi14"),
        "drawdown_1y": latest.get("drawdown_250d"),
        "return_1y": float(close.pct_change(250).iloc[-1]) if len(close) > 250 else None,
        "return_3y": float(close.pct_change(750).iloc[-1]) if len(close) > 750 else None,
        "volatility_60d": float(returns.rolling(60).std().iloc[-1] * math.sqrt(250)) if len(close) > 60 else None,
        "bias250_percentile": bias250_pct,
        "bias500_percentile": bias500_pct,
        "rsi_percentile": rsi_pct,
        "drawdown_percentile": drawdown_pct,
        "relative_value_score": round(relative_value, 2),
        "buy_score": buy_score,
        "buy_state": _score_label(buy_score, "buy"),
        "sell_score": sell_score,
        "sell_state": _score_label(sell_score, "sell"),
        "ranking_score": ranking_score,
    }


class MarketComparisonService:
    def __init__(self, catalog: InstrumentCatalog | None = None):
        self.catalog = catalog or InstrumentCatalog()

    def snapshots(self) -> list[dict[str, Any]]:
        rows = [
            instrument_snapshot(MarketService(item.symbol, catalog=self.catalog))
            for item in self.catalog.list()
            if item.has_data
        ]
        rows.sort(key=lambda row: (row["ranking_score"], row["buy_score"]), reverse=True)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        return rows

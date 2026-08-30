from __future__ import annotations

from typing import Any

import pandas as pd

from .service import MarketService


class EventBacktester:
    def __init__(self, service: MarketService):
        self.service = service

    def run(
        self,
        metric: str = "bias250",
        threshold: float = -0.10,
        direction: str = "below",
        cooldown_trading_days: int = 60,
        horizons: tuple[int, ...] = (250, 750, 1250),
    ) -> dict[str, Any]:
        frame = self.service.df.reset_index(drop=True)
        if metric not in frame.columns:
            raise ValueError(f"未知事件指标：{metric}")
        if direction not in {"below", "above"}:
            raise ValueError("direction 必须是 below 或 above")
        if cooldown_trading_days < 0:
            raise ValueError("cooldown_trading_days 不能为负")
        condition = frame[metric] <= threshold if direction == "below" else frame[metric] >= threshold
        # An event starts only when the condition changes from false to true.
        # This avoids counting a continuous bear/bull regime as daily samples.
        starts = condition & ~condition.shift(1, fill_value=False)
        candidate_indexes = list(frame.index[starts.fillna(False)])
        selected: list[int] = []
        for index in candidate_indexes:
            if not selected or index - selected[-1] > cooldown_trading_days:
                selected.append(index)

        events: list[dict[str, Any]] = []
        for index in selected:
            row = frame.iloc[index]
            event = {
                "date": row["date"].strftime("%Y-%m-%d"),
                "close": float(row["close"]),
                "metric": float(row[metric]),
                "rsi14": float(row["rsi14"]) if pd.notna(row.get("rsi14")) else None,
            }
            for horizon in horizons:
                future_index = index + horizon
                event[f"return_{horizon}d"] = (
                    float(frame.iloc[future_index]["close"] / row["close"] - 1)
                    if future_index < len(frame) else None
                )
            events.append(event)

        summary: dict[str, Any] = {"event_count": len(events)}
        for horizon in horizons:
            key = f"return_{horizon}d"
            values = pd.Series([event[key] for event in events if event[key] is not None], dtype=float)
            summary[key] = {
                "samples": int(len(values)),
                "mean": float(values.mean()) if len(values) else None,
                "median": float(values.median()) if len(values) else None,
                "positive_rate": float((values > 0).mean()) if len(values) else None,
            }
        return {
            "symbol": self.service.instrument.symbol,
            "name": self.service.instrument.name,
            "metric": metric,
            "threshold": threshold,
            "direction": direction,
            "cooldown_trading_days": cooldown_trading_days,
            "summary": summary,
            "events": events,
        }

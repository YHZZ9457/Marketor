"""MA dynamic V1: price signals, total-return valuation, close-time simulation."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

STRATEGY_ID = "ma_dynamic_v1"
STRATEGY_NAME = "MA动态策略 V1"
RULES = {
    "initial_amount": 10000.0,
    "entry_ma500_multiple": 1.10,
    "buy_tiers": [[-0.05, 0.50], [-0.10, 0.75], [-0.15, 1.0]],
    "sell_tiers": [[0.10, 0.50], [0.15, 0.75], [0.20, 1.0]],
    "daily_pnl_basis": "昨日收盘持仓份额 ×（今日全收益收盘点位－昨日全收益收盘点位）",
    "execution": "当日收盘估值与模拟成交；首次建仓日不重复加减仓",
    "cash_interest": 0,
    "fees": 0,
    "note": "理想化指数回测，未计费用和滑点；全收益份额为模拟单位，非可直接交易证券。",
}


def _series(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    if not {"date", "close"}.issubset(frame.columns) or frame.empty:
        raise ValueError(f"{label}必须包含非空 date,close")
    frame = frame[["date", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    if (frame.date.isna().any() or frame.date.dt.tz is not None
            or not frame.date.eq(frame.date.dt.normalize()).all()
            or frame.date.duplicated().any() or not frame.date.is_monotonic_increasing):
        raise ValueError(f"{label}日期必须无时区、无时间、升序且唯一")
    frame["close"] = pd.to_numeric(frame["close"], errors="raise")
    if not np.isfinite(frame.close).all() or (frame.close <= 0).any():
        raise ValueError(f"{label}收盘点位必须为有限正数")
    return frame.reset_index(drop=True)


def load_total_return(path: Path, expected_code: str) -> tuple[pd.DataFrame, dict]:
    """An explicitly identified local series; never substitute price/net_value."""
    if not path.exists():
        raise ValueError(f"缺少全收益指数 {expected_code} 数据：{path.name}")
    meta_path = Path(str(path) + ".meta.json")
    if not meta_path.exists():
        raise ValueError(f"缺少全收益来源记录：{meta_path.name}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if (not isinstance(meta, dict) or meta.get("index_code") != expected_code or meta.get("return_type") != "total_return"
            or not meta.get("source") or not meta.get("download_time")):
        raise ValueError("全收益来源记录必须匹配 index_code、return_type=total_return，并注明 source、download_time")
    return _series(pd.read_csv(path), "全收益指数"), meta


def trade_fraction(bias: float, daily_pnl: float) -> float:
    if not math.isfinite(bias) or daily_pnl == 0:
        return 0.0
    # Round only the comparison to neutralize float error at exact thresholds.
    bias = round(bias, 12)
    tiers = RULES["buy_tiers"] if daily_pnl < 0 else RULES["sell_tiers"]
    for threshold, fraction in reversed(tiers):
        if (daily_pnl < 0 and bias <= threshold) or (daily_pnl > 0 and bias >= threshold):
            return fraction
    return 0.0


def backtest(price: pd.DataFrame, total_return: pd.DataFrame,
             start: str | None = None, end: str | None = None) -> dict:
    price = _series(price, "价格指数")
    total_return = _series(total_return, "全收益指数")
    # Warm up before slicing: MA windows always mean actual price trading days.
    price["ma250"] = price.close.rolling(250, min_periods=250).mean()
    price["ma500"] = price.close.rolling(500, min_periods=500).mean()
    start_date = pd.Timestamp(start) if start else price.date.iloc[0]
    end_date = pd.Timestamp(end) if end else price.date.iloc[-1]
    if (pd.isna(start_date) or pd.isna(end_date)
            or start_date.tzinfo is not None or end_date.tzinfo is not None
            or start_date != start_date.normalize() or end_date != end_date.normalize()
            or start_date > end_date):
        raise ValueError("回测起止日期无效")
    price = price[price.date.between(start_date, end_date)].copy()
    if price.empty:
        raise ValueError("回测区间没有价格数据")
    tri = total_return.set_index("date").close.reindex(price.date)
    if tri.isna().any():
        missing = price.loc[tri.isna().to_numpy(), "date"].iloc[0]
        raise ValueError(f"全收益数据未覆盖价格交易日 {missing:%Y-%m-%d}；不能跳日或前向填充")
    price["total_return_close"] = tri.to_numpy()
    units = cash = external = previous_tri = 0.0
    entered = False
    ledger = []
    for row in price.itertuples(index=False):
        level = row.total_return_close
        daily_pnl = units * (level - previous_tri) if entered else 0.0
        holding_before = units * level
        bias = row.close / row.ma250 - 1 if pd.notna(row.ma250) else float("nan")
        buy = sell = cash_used = added = fraction = 0.0
        action = "hold" if entered else "wait"
        if not entered:
            if pd.notna(row.ma500) and row.close <= row.ma500 * 1.10:
                buy = added = RULES["initial_amount"]
                units = buy / level
                entered = True
                action = "initial_buy"
        else:
            fraction = trade_fraction(bias, daily_pnl)
            if fraction and daily_pnl < 0:
                buy = -daily_pnl * fraction
                cash_used = min(cash, buy)
                cash -= cash_used
                added = buy - cash_used
                units += buy / level
                action = "buy"
            elif fraction and daily_pnl > 0:
                sell = min(daily_pnl * fraction, holding_before)
                units -= sell / level
                cash += sell
                action = "sell"
        external += added
        holding = units * level
        ledger.append({
            "date": row.date.strftime("%Y-%m-%d"), "price_close": row.close,
            "total_return_close": level,
            "ma250": None if pd.isna(row.ma250) else row.ma250,
            "ma500": None if pd.isna(row.ma500) else row.ma500,
            "bias250": None if pd.isna(bias) else bias,
            "action": action, "fraction": fraction, "daily_pnl": daily_pnl,
            "holding_before_trade": holding_before, "buy_amount": buy, "sell_amount": sell,
            "cash_used": cash_used, "external_added": added, "external_total": external,
            "units": units, "holding_value": holding, "cash": cash,
            "total_assets": holding + cash, "profit": holding + cash - external,
        })
        previous_tri = level
    last = ledger[-1]
    return {
        "strategy_id": STRATEGY_ID, "name": STRATEGY_NAME, "rules": RULES,
        "status": "ok", "start": ledger[0]["date"], "end": last["date"],
        "summary": {**{k: last[k] for k in ("holding_value", "cash", "external_total", "total_assets", "profit")},
                    "entered": entered, "trade_count": sum(r["action"] in ("initial_buy", "buy", "sell") for r in ledger)},
        "latest": last, "ledger": ledger,
    }

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
import math

from .ma_dynamic import RULES, STRATEGY_ID, STRATEGY_NAME, trade_fraction


@dataclass
class Signal:
    side: str
    level: str
    score: float
    suggested_action: str
    reasons: list[str]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def _pct(x: float | None) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "N/A"
    return f"{x * 100:.2f}%"


def daily_reference(latest: dict[str, Any], equity: float = 10000.0) -> dict[str, Any]:
    """Normalize an existing holding at today's close, before the simulated trade."""
    if not math.isfinite(equity) or equity < 0:
        raise ValueError("权益市值必须是有限的非负数")
    bias, rate = latest.get("bias250"), latest.get("daily_return")
    result = {"date": str(latest.get("date"))[:10], "baseline_equity": 10000.0,
              "equity": equity, "coefficient": equity / 10000,
              "basis": "价格涨跌估算（未含分红），当日收盘交易前权益市值；假设全天持仓份额不变",
              "note": "已有持仓参考，不包含首次建仓；加仓先用现金池，不等于必须新增资金。"}
    if any(v is None or not math.isfinite(float(v)) for v in (bias, rate)) or float(rate) <= -1:
        return {**result, "status": "unavailable", "message": "缺少有效日收益或MA250数据"}
    pnl = 10000 * float(rate) / (1 + float(rate))
    fraction = trade_fraction(float(bias), pnl)
    buy, sell = max(-pnl, 0) * fraction, min(max(pnl, 0) * fraction, 10000)
    return {**result, "status": "ok", "daily_return": float(rate), "fraction": fraction,
            "baseline_pnl": pnl, "baseline_buy": buy, "baseline_sell": sell,
            "buy_amount": buy * equity / 10000, "sell_amount": sell * equity / 10000,
            "signed_amount_per_10000": buy - sell}


def evaluate(latest: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return V1 conditional guidance without inventing portfolio state.

    MA250 determines the tier. The actual action and amount remain conditional on
    the user's holding P&L calculated from the total-return index.
    """
    b250 = latest.get("bias250")
    b500 = latest.get("bias500")
    close = latest.get("close")
    ma500 = latest.get("ma500")
    valid250 = b250 is not None and math.isfinite(float(b250))
    valid500 = all(
        value is not None and math.isfinite(float(value))
        for value in (close, ma500, b500)
    )
    buy_fraction = trade_fraction(float(b250), -1.0) if valid250 else 0.0
    sell_fraction = trade_fraction(float(b250), 1.0) if valid250 else 0.0
    buy_pct = int(buy_fraction * 100)
    sell_pct = int(sell_fraction * 100)
    entry_eligible = valid500 and float(close) <= float(ma500) * RULES["entry_ma500_multiple"]
    initial_action = (
        "未建仓时允许首次投入10,000元"
        if entry_eligible else "未建仓时暂不首次建仓"
    )
    holding_buy_action = (
        f"已持仓且当日亏损时，加仓当日亏损的{buy_pct}%"
        if buy_pct else "已持仓时不触发V1加仓档位"
    )

    def level(value: int) -> str:
        return {0: "无", 50: "一档", 75: "二档", 100: "三档"}[value]

    metrics = {
        "close": latest.get("close"),
        "bias250": b250,
        "bias500": b500,
    }
    return {
        "strategy_id": STRATEGY_ID,
        "name": STRATEGY_NAME,
        "date": str(latest.get("date"))[:10],
        "initial_entry": {
            "eligible": entry_eligible,
            "amount": RULES["initial_amount"],
            "suggested_action": (
                "若尚未建仓：允许首次投入10,000元"
                if entry_eligible else "若尚未建仓：暂不首次建仓"
            ),
            "reason": f"当前价格相对MA500乖离为{_pct(b500)}；首次门槛为≤+10%",
        },
        "accumulation": {
            "side": "buy", "level": level(buy_pct), "score": float(buy_pct),
            "suggested_action": f"{initial_action}；{holding_buy_action}",
            "reasons": ([f"MA250乖离{_pct(b250)}，命中{buy_pct}%档"] if buy_pct
                        else [f"MA250乖离{_pct(b250)}，未达到-5%加仓线"]),
            "metrics": metrics, "condition": "仅当日持仓亏损时执行",
        },
        "reduction": {
            "side": "sell", "level": level(sell_pct), "score": float(sell_pct),
            "suggested_action": (f"若当日持仓盈利：减仓当日盈利的{sell_pct}%" if sell_pct else "不触发V1减仓档位"),
            "reasons": ([f"MA250乖离{_pct(b250)}，命中{sell_pct}%档"] if sell_pct
                        else [f"MA250乖离{_pct(b250)}，未达到+10%减仓线"]),
            "metrics": metrics, "condition": "仅当日持仓盈利时执行",
        },
        "portfolio_state_required": True,
        "note": "这是V1条件信号。实际交易金额须用全收益指数计算当日持仓盈亏；卖出进入现金池，加仓先用现金。辅助决策，不构成自动交易指令。",
    }


def evaluate_adaptive(
    latest: dict[str, Any], profile: dict[str, Any], previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate an explicitly applied per-instrument profile without changing global rules."""
    b250, b500, b1250 = latest.get("bias250"), latest.get("bias500"), latest.get("bias1250")
    rsi = latest.get("rsi14")
    buy_levels = [float(value) for value in profile["buy_bias_levels"]]
    sell_levels = [float(value) for value in profile["sell_bias_levels"]]
    mult = 1.0
    buy_reasons: list[str] = []
    if b250 is not None and not math.isnan(b250):
        for threshold, value in zip(buy_levels, (1.2, 1.5, 2.0, 2.5)):
            if b250 <= threshold:
                mult = value
                buy_reasons = [f"个性化250日线阈值 {_pct(threshold)} 已触发（当前 {_pct(b250)}）"]
    if rsi is not None and not math.isnan(rsi):
        if rsi < float(profile["rsi_extreme"]):
            mult += 1.0; buy_reasons.append(f"个性化 RSI 极端阈值已触发（{rsi:.1f}）")
        elif rsi < float(profile["rsi_oversold"]):
            mult += 0.5; buy_reasons.append(f"个性化 RSI 超卖阈值已触发（{rsi:.1f}）")
    if b1250 is not None and not math.isnan(b1250) and b1250 <= -0.10:
        mult += 0.5; buy_reasons.append(f"低于1250日线10%以上（{_pct(b1250)}），长期位置偏低")
    mult = min(mult, 3.0)

    reduce = 0
    sell_reasons: list[str] = []
    if b500 is not None and not math.isnan(b500):
        for threshold, value in zip(sell_levels, (10, 15, 25, 30)):
            if b500 >= threshold:
                reduce = value
                sell_reasons = [f"个性化500日线阈值 {_pct(threshold)} 已触发（当前 {_pct(b500)}）"]
    if b1250 is not None and not math.isnan(b1250):
        if b1250 >= 0.30:
            reduce += 10; sell_reasons.append(f"高于1250日线30%以上（{_pct(b1250)}），长期极端过热")
        elif b1250 >= 0.20:
            reduce += 5; sell_reasons.append(f"高于1250日线20%以上（{_pct(b1250)}），长期偏热")
    if latest.get("rsi_cross_down_75"):
        reduce += 10; sell_reasons.append("RSI从75以上回落到75以下")
    elif latest.get("rsi_cross_down_70"):
        reduce += 5; sell_reasons.append("RSI从70以上回落到70以下")
    reduce = min(reduce, 40)

    buy_level = "强" if mult >= 2.5 else "中" if mult >= 1.5 else "弱" if mult > 1.0 else "无"
    sell_level = "强" if reduce >= 30 else "中" if reduce >= 15 else "弱" if reduce > 0 else "无"
    metrics = {
        "close": latest.get("close"), "rsi14": rsi, "bias180": latest.get("bias180"),
        "bias250": b250, "bias500": b500, "bias1250": b1250,
        "drawdown_250d": latest.get("drawdown_250d"),
    }
    return {
        "date": str(latest.get("date"))[:10],
        "accumulation": Signal("buy", buy_level, mult, f"定投/加仓参考倍数 {mult:.1f}x", buy_reasons or ["未触发个性化低位信号"], metrics).to_dict(),
        "reduction": Signal("sell", sell_level, float(reduce), f"累计减仓参考 {reduce}%" if reduce else "维持核心仓位，不触发技术性减仓", sell_reasons or ["未触发个性化过热信号"], metrics).to_dict(),
        "strategy_profile": {"source": profile.get("source"), "model": profile.get("model"), "created_at": profile.get("created_at")},
        "note": "已使用经用户明确应用、并通过样本外验证的个性化阈值；不构成自动交易指令。",
    }

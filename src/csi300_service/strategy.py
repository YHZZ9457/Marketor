from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
import math


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


def evaluate(latest: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    b250 = latest.get("bias250")
    b500 = latest.get("bias500")
    b1250 = latest.get("bias1250")
    rsi = latest.get("rsi14")

    # Accumulation multiplier: intentionally simple and capped.
    mult = 1.0
    buy_reasons: list[str] = []
    if b250 is not None and not math.isnan(b250):
        if b250 <= -0.15:
            mult = 2.5; buy_reasons.append(f"低于250日线15%以上（{_pct(b250)}）")
        elif b250 <= -0.10:
            mult = 2.0; buy_reasons.append(f"低于250日线10%以上（{_pct(b250)}）")
        elif b250 <= -0.05:
            mult = 1.5; buy_reasons.append(f"低于250日线5%以上（{_pct(b250)}）")
        elif b250 < 0:
            mult = 1.2; buy_reasons.append(f"略低于250日线（{_pct(b250)}）")
    if rsi is not None and not math.isnan(rsi):
        if rsi < 30:
            mult += 1.0; buy_reasons.append(f"RSI14<30（{rsi:.1f}），短期超卖")
        elif rsi < 35:
            mult += 0.5; buy_reasons.append(f"RSI14<35（{rsi:.1f}），偏超卖")
    if b1250 is not None and not math.isnan(b1250) and b1250 <= -0.10:
        mult += 0.5; buy_reasons.append(f"低于1250日线10%以上（{_pct(b1250)}），长期位置偏低")
    mult = min(mult, 3.0)

    # Reduction: MA500 is primary; MA1250 + RSI pullback are confirmations.
    reduce = 0
    sell_reasons: list[str] = []
    if b500 is not None and not math.isnan(b500):
        if b500 >= 0.25:
            reduce = 30; sell_reasons.append(f"高于500日线25%以上（{_pct(b500)}）")
        elif b500 >= 0.20:
            reduce = 25; sell_reasons.append(f"高于500日线20%以上（{_pct(b500)}）")
        elif b500 >= 0.15:
            reduce = 15; sell_reasons.append(f"高于500日线15%以上（{_pct(b500)}）")
        elif b500 >= 0.10:
            reduce = 10; sell_reasons.append(f"高于500日线10%以上（{_pct(b500)}）")
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

    if mult >= 2.5:
        buy_level = "强"
    elif mult >= 1.5:
        buy_level = "中"
    elif mult > 1.0:
        buy_level = "弱"
    else:
        buy_level = "无"

    if reduce >= 30:
        sell_level = "强"
    elif reduce >= 15:
        sell_level = "中"
    elif reduce > 0:
        sell_level = "弱"
    else:
        sell_level = "无"

    metrics = {
        "close": latest.get("close"),
        "rsi14": rsi,
        "bias180": latest.get("bias180"),
        "bias250": b250,
        "bias500": b500,
        "bias1250": b1250,
        "drawdown_250d": latest.get("drawdown_250d"),
    }
    return {
        "date": str(latest.get("date"))[:10],
        "accumulation": Signal(
            side="buy", level=buy_level, score=mult,
            suggested_action=f"定投/加仓参考倍数 {mult:.1f}x",
            reasons=buy_reasons or ["未触发明显低位信号"], metrics=metrics,
        ).to_dict(),
        "reduction": Signal(
            side="sell", level=sell_level, score=float(reduce),
            suggested_action=(f"累计减仓参考 {reduce}%" if reduce else "维持核心仓位，不触发技术性减仓"),
            reasons=sell_reasons or ["未触发明显过热/动量回落信号"], metrics=metrics,
        ).to_dict(),
        "note": "辅助决策信号，不构成自动交易指令；技术信号应结合资产配置、现金流和风险承受能力。",
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

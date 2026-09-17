"""Previous multiplier/reduction strategy, retained for compatibility and audit."""
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


def _pct(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "N/A"
    return f"{value * 100:.2f}%"


def evaluate(latest: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate the pre-V1 strategy. New user-facing signals do not call this."""
    b250, b500 = latest.get("bias250"), latest.get("bias500")
    b1250, rsi = latest.get("bias1250"), latest.get("rsi14")
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

    buy_level = "强" if mult >= 2.5 else "中" if mult >= 1.5 else "弱" if mult > 1 else "无"
    sell_level = "强" if reduce >= 30 else "中" if reduce >= 15 else "弱" if reduce > 0 else "无"
    metrics = {
        "close": latest.get("close"), "rsi14": rsi,
        "bias180": latest.get("bias180"), "bias250": b250,
        "bias500": b500, "bias1250": b1250,
        "drawdown_250d": latest.get("drawdown_250d"),
    }
    return {
        "date": str(latest.get("date"))[:10],
        "accumulation": Signal(
            "buy", buy_level, mult, f"定投/加仓参考倍数 {mult:.1f}x",
            buy_reasons or ["未触发明显低位信号"], metrics,
        ).to_dict(),
        "reduction": Signal(
            "sell", sell_level, float(reduce),
            f"累计减仓参考 {reduce}%" if reduce else "维持核心仓位，不触发技术性减仓",
            sell_reasons or ["未触发明显过热/动量回落信号"], metrics,
        ).to_dict(),
        "note": "辅助决策信号，不构成自动交易指令；技术信号应结合资产配置、现金流和风险承受能力。",
    }

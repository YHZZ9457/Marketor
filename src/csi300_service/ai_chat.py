from __future__ import annotations

import json
from typing import Any

from .ai_strategy import load_strategy_profile
from .catalog import InstrumentCatalog
from .service import MarketService


def build_analysis_context(
    symbol: str, *, catalog: InstrumentCatalog | None = None,
) -> dict[str, Any]:
    """Build a compact, auditable context; raw price history stays local."""
    catalog = catalog or InstrumentCatalog()
    service = MarketService(symbol, catalog=catalog)
    latest = service.latest()
    signal = service.signal()
    profile = load_strategy_profile(symbol)
    indicator_keys = (
        "date", "close", "ma60", "ma180", "ma250", "ma500", "ma1250",
        "bias60", "bias180", "bias250", "bias500", "bias1250", "rsi14",
        "drawdown_250d", "ret_5d", "ret_20d",
    )
    return {
        "instrument": service.metadata(),
        "latest": {key: latest.get(key) for key in indicator_keys},
        "signal": signal,
        "holding_return_statistics": service.holding_returns((30, 365, 730, 1095, 1825)),
        "adaptive_strategy": profile.to_dict() if profile is not None else None,
        "context_policy": {
            "raw_history_transmitted": False,
            "data_cutoff": latest.get("date"),
            "purpose": "historical research and decision support only",
        },
    }


def analysis_system_prompt(context: dict[str, Any]) -> str:
    return (
        "你是 Marketor 内置的市场研究助手。请用中文回答，并严格依据下方 JSON 上下文。"
        "先区分可核对的数据事实、你的推断和不确定性；没有数据时明确说不知道。"
        "可以解释指标、比较历史统计、讨论情景、风险与策略逻辑，但不得声称保证收益，"
        "不得假装掌握数据截止日之后的行情，不得生成或执行自动交易指令，也不得声称已经修改策略。"
        "涉及买卖时使用条件式、研究性表达，并提醒这不是个性化投资建议。"
        "回答尽量清晰简洁，引用关键数字时注明日期或统计口径。\n\n"
        f"当前标的上下文 JSON：\n{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}"
    )

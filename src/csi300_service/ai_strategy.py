from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
import json
import math
import os
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import numpy as np
import pandas as pd

from .catalog import InstrumentCatalog, user_storage_dir
from .indicators import add_indicators
from .data import load_data


DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"


@dataclass(frozen=True)
class AdaptiveStrategyProfile:
    symbol: str
    name: str
    buy_bias_levels: tuple[float, float, float, float]
    sell_bias_levels: tuple[float, float, float, float]
    rsi_oversold: float
    rsi_extreme: float
    source: str
    model: str
    rationale: str
    active: bool
    created_at: str
    validation: dict[str, float | int | None]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["buy_bias_levels"] = list(self.buy_bias_levels)
        result["sell_bias_levels"] = list(self.sell_bias_levels)
        return result


def strategy_profile_path(symbol: str) -> Path:
    return user_storage_dir() / "ai_strategies" / f"{symbol.lower()}.json"


def load_strategy_profile(symbol: str) -> AdaptiveStrategyProfile | None:
    path = strategy_profile_path(symbol)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _profile_from_payload(payload)
    except (OSError, ValueError, TypeError, KeyError):
        return None


def set_strategy_profile_active(symbol: str, active: bool) -> AdaptiveStrategyProfile:
    profile = load_strategy_profile(symbol)
    if profile is None:
        raise ValueError("该标的尚无个性化策略")
    updated = replace(profile, active=bool(active))
    InstrumentStrategyOptimizer._save(updated)
    return updated


def _profile_from_payload(payload: dict[str, Any]) -> AdaptiveStrategyProfile:
    return AdaptiveStrategyProfile(
        symbol=str(payload["symbol"]), name=str(payload["name"]),
        buy_bias_levels=tuple(float(value) for value in payload["buy_bias_levels"]),  # type: ignore[arg-type]
        sell_bias_levels=tuple(float(value) for value in payload["sell_bias_levels"]),  # type: ignore[arg-type]
        rsi_oversold=float(payload["rsi_oversold"]), rsi_extreme=float(payload["rsi_extreme"]),
        source=str(payload["source"]), model=str(payload["model"]),
        rationale=str(payload["rationale"]), active=bool(payload.get("active", True)),
        created_at=str(payload["created_at"]), validation=dict(payload.get("validation", {})),
    )


class OpenAICompatibleJSONClient:
    def __init__(
        self, *, api_key: str, base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash", opener: Callable[..., Any] | None = None,
    ):
        self.api_key = api_key.strip()
        self.base_url = base_url.strip().rstrip("/")
        self.model = model.strip()
        self.opener = opener or urlopen

    @staticmethod
    def _error_message(exc: Exception) -> str:
        if isinstance(exc, HTTPError):
            return {401: "API Key 无效或已过期", 403: "接口拒绝访问，请检查权限", 429: "请求过多或额度不足，请稍后重试"}.get(exc.code, f"服务返回 HTTP {exc.code}，请检查端点和模型配置")
        if isinstance(exc, (TimeoutError, URLError)):
            return "网络连接失败或超时，请检查网络和 Base URL 后重试"
        return "响应格式不正确或内容为空，请检查模型是否支持当前请求"

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("AI API Key 不能为空")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 1800,
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = self.opener(request, timeout=60)
            try:
                envelope = json.loads(response.read().decode("utf-8"))
            finally:
                response.close()
            content = envelope["choices"][0]["message"]["content"]
            result = json.loads(content)
            if not isinstance(result, dict):
                raise ValueError("模型必须返回 JSON 对象")
            return result
        except Exception as exc:
            raise RuntimeError(f"AI 策略接口调用失败：{self._error_message(exc)}") from exc

    def chat(self, system_prompt: str, messages: list[dict[str, str]]) -> str:
        """Return one non-streaming conversational answer."""
        if not self.api_key:
            raise RuntimeError("AI API Key 不能为空")
        cleaned = [
            {"role": item["role"], "content": str(item["content"])[:8000]}
            for item in messages[-12:]
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, *cleaned],
            "temperature": 0.3,
            "max_tokens": 2200,
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = self.opener(request, timeout=75)
            try:
                envelope = json.loads(response.read().decode("utf-8"))
            finally:
                response.close()
            content = envelope["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("模型返回空内容")
            return content.strip()
        except Exception as exc:
            raise RuntimeError(f"AI 自由分析接口调用失败：{self._error_message(exc)}") from exc


class InstrumentStrategyOptimizer:
    """AI-proposed, locally validated per-instrument threshold optimizer."""

    def __init__(self, symbol: str, *, catalog: InstrumentCatalog | None = None):
        self.catalog = catalog or InstrumentCatalog()
        self.instrument = self.catalog.get(symbol)
        self.frame = add_indicators(load_data(self.instrument.data_path))

    def optimize(
        self, *, client: OpenAICompatibleJSONClient | None = None,
        provider_name: str = "本地量化", apply: bool = True, persist: bool = True,
    ) -> AdaptiveStrategyProfile:
        usable = self.frame.dropna(subset=["bias250", "bias500", "rsi14"]).copy()
        if len(usable) < 500:
            raise ValueError("至少需要 500 个包含长期均线的交易日才能做策略优化")
        split = max(350, int(len(usable) * 0.70))
        train, validation = usable.iloc[:split], usable.iloc[split:]
        if len(validation) < 120:
            raise ValueError("样本外验证区间不足 120 个交易日")

        baseline = self._quantile_candidate(train)
        candidates = [baseline]
        source = "本地量化"
        model = "quantile-baseline"
        if client is not None:
            proposals = client.complete_json(self._system_prompt(), json.dumps(self._summary(train), ensure_ascii=False))
            proposed = proposals.get("candidates", [])
            if not isinstance(proposed, list):
                raise ValueError("AI 返回的 candidates 必须为数组；原策略未修改")
            for raw in proposed[:4]:
                try:
                    candidates.append(self._validate_candidate(raw))
                except (ValueError, TypeError, KeyError):
                    continue
            source, model = provider_name, client.model

        scored = [(self._backtest(validation, candidate), candidate) for candidate in candidates]
        scored.sort(key=lambda item: float(item[0]["score"]), reverse=True)
        metrics, chosen = scored[0]
        if not math.isfinite(float(metrics["score"])):
            raise RuntimeError("没有候选策略通过样本外验证")
        profile = AdaptiveStrategyProfile(
            symbol=self.instrument.symbol, name=self.instrument.name,
            buy_bias_levels=tuple(chosen["buy_bias_levels"]),
            sell_bias_levels=tuple(chosen["sell_bias_levels"]),
            rsi_oversold=float(chosen["rsi_oversold"]), rsi_extreme=float(chosen["rsi_extreme"]),
            source=source if chosen is not baseline else "本地量化基线",
            model=model if chosen is not baseline else "quantile-baseline",
            rationale=str(chosen.get("rationale") or "基于训练区间历史分位生成，并通过样本外回测选择。"),
            active=apply, created_at=datetime.now().isoformat(timespec="seconds"), validation=metrics,
        )
        if persist:
            self._save(profile)
        return profile

    @staticmethod
    def apply_profile(profile: AdaptiveStrategyProfile) -> AdaptiveStrategyProfile:
        updated = replace(profile, active=True)
        InstrumentStrategyOptimizer._save(updated)
        return updated

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是审慎的量化研究助手。根据输入的单一标的训练区间统计摘要，输出 JSON，键为 candidates，"
            "包含 3 个候选。每个候选包含 name、buy_bias_levels（4个严格递减负数，范围-0.35到-0.01）、"
            "sell_bias_levels（4个严格递增正数，范围0.03到0.50）、rsi_oversold（25到45）、"
            "rsi_extreme（15到且小于rsi_oversold）和 rationale。"
            "目标是稳健的样本外风险调整收益，不追求拟合训练样本；不要修改仓位上限、核心仓位或指标定义。"
        )

    def _summary(self, frame: pd.DataFrame) -> dict[str, Any]:
        returns = frame["close"].pct_change().dropna()
        def quantiles(column: str) -> dict[str, float]:
            values = frame[column].dropna()
            return {str(q): round(float(values.quantile(q)), 6) for q in (0.05, 0.1, 0.2, 0.35, 0.65, 0.8, 0.9, 0.95)}
        return {
            "symbol": self.instrument.symbol, "name": self.instrument.name,
            "asset_class": self.instrument.asset_class, "rows": len(frame),
            "date_range": [frame.iloc[0]["date"].strftime("%Y-%m-%d"), frame.iloc[-1]["date"].strftime("%Y-%m-%d")],
            "bias250_quantiles": quantiles("bias250"), "bias500_quantiles": quantiles("bias500"),
            "rsi14_quantiles": quantiles("rsi14"),
            "annualized_volatility": round(float(returns.std() * np.sqrt(250)), 6),
            "max_drawdown": round(float((frame["close"] / frame["close"].cummax() - 1).min()), 6),
        }

    def _quantile_candidate(self, train: pd.DataFrame) -> dict[str, Any]:
        buy = [float(train["bias250"].quantile(q)) for q in (0.35, 0.20, 0.10, 0.05)]
        sell = [float(train["bias500"].quantile(q)) for q in (0.65, 0.80, 0.90, 0.95)]
        return self._validate_candidate({
            "name": "历史分位基线", "buy_bias_levels": buy, "sell_bias_levels": sell,
            "rsi_oversold": float(train["rsi14"].quantile(0.20)),
            "rsi_extreme": float(train["rsi14"].quantile(0.10)),
            "rationale": "训练区间历史分位基线。",
        })

    @staticmethod
    def _validate_candidate(raw: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("候选必须为对象")
        values = [*raw["buy_bias_levels"], *raw["sell_bias_levels"], raw["rsi_oversold"], raw["rsi_extreme"]]
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("候选参数必须为有限数值")
        buy = [min(-0.01, max(-0.35, float(value))) for value in raw["buy_bias_levels"]]
        sell = [min(0.50, max(0.03, float(value))) for value in raw["sell_bias_levels"]]
        if len(buy) != 4 or len(sell) != 4:
            raise ValueError("阈值必须各有 4 档")
        buy = sorted(set(buy), reverse=True)
        sell = sorted(set(sell))
        if len(buy) != 4 or len(sell) != 4:
            raise ValueError("阈值必须严格单调")
        oversold = min(45.0, max(25.0, float(raw["rsi_oversold"])))
        extreme = min(oversold - 1.0, max(15.0, float(raw["rsi_extreme"])))
        return {
            "name": str(raw.get("name") or "AI候选"), "buy_bias_levels": buy,
            "sell_bias_levels": sell, "rsi_oversold": oversold, "rsi_extreme": extreme,
            "rationale": str(raw.get("rationale") or "AI 生成候选。")[:500],
        }

    @staticmethod
    def _positions(frame: pd.DataFrame, candidate: dict[str, Any]) -> pd.Series:
        position = pd.Series(0.75, index=frame.index, dtype=float)
        for threshold, level in zip(candidate["buy_bias_levels"], (0.80, 0.87, 0.95, 1.0)):
            position = position.mask(frame["bias250"] <= threshold, level)
        position = position.mask(frame["rsi14"] < candidate["rsi_oversold"], np.maximum(position, 0.90))
        position = position.mask(frame["rsi14"] < candidate["rsi_extreme"], 1.0)
        for threshold, level in zip(candidate["sell_bias_levels"], (0.70, 0.66, 0.62, 0.60)):
            position = position.mask(frame["bias500"] >= threshold, level)
        return position.clip(0.60, 1.0)

    def _backtest(self, frame: pd.DataFrame, candidate: dict[str, Any]) -> dict[str, float | int | None]:
        position = self._positions(frame, candidate)
        returns = frame["close"].pct_change().fillna(0.0)
        turnover = position.diff().abs().fillna(0.0)
        strategy_returns = position.shift(1).fillna(0.75) * returns - turnover * 0.001
        wealth = (1 + strategy_returns).cumprod()
        years = max(len(strategy_returns) / 250.0, 1 / 250)
        cagr = float(wealth.iloc[-1] ** (1 / years) - 1)
        max_drawdown = float((wealth / wealth.cummax() - 1).min())
        std = float(strategy_returns.std())
        sharpe = float(strategy_returns.mean() / std * np.sqrt(250)) if std > 0 else 0.0
        score = sharpe + 0.5 * cagr - 1.5 * abs(max_drawdown) - 0.05 * float(turnover.sum() / years)
        return {
            "score": round(score, 6), "cagr": round(cagr, 6),
            "max_drawdown": round(max_drawdown, 6), "sharpe": round(sharpe, 6),
            "annual_turnover": round(float(turnover.sum() / years), 6), "validation_days": len(frame),
        }

    @staticmethod
    def _save(profile: AdaptiveStrategyProfile) -> None:
        path = strategy_profile_path(profile.symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

from __future__ import annotations

import io
import json

import numpy as np
import pandas as pd

from csi300_service.ai_strategy import (
    InstrumentStrategyOptimizer, OpenAICompatibleJSONClient, load_strategy_profile,
    set_strategy_profile_active,
)
from csi300_service.ai_chat import analysis_system_prompt, build_analysis_context
from csi300_service.catalog import InstrumentCatalog
from csi300_service.service import MarketService


def _catalog(tmp_path) -> InstrumentCatalog:
    rows = 1800
    dates = pd.bdate_range("2018-01-02", periods=rows)
    trend = np.linspace(100, 220, rows)
    cycle = 18 * np.sin(np.arange(rows) / 55) + 8 * np.sin(np.arange(rows) / 170)
    close = np.maximum(20, trend + cycle)
    frame = pd.DataFrame({"date": dates, "close": close})
    frame["open"] = frame["close"] * 0.998
    frame["high"] = frame["close"] * 1.01
    frame["low"] = frame["close"] * 0.99
    frame["amount"] = 1_000_000
    frame.to_csv(tmp_path / "demo.csv", index=False)
    (tmp_path / "instruments.json").write_text(json.dumps({"instruments": [{
        "symbol": "demo", "name": "Demo Stock", "asset_class": "stock",
        "market": "CN", "currency": "CNY", "data_file": "demo.csv",
    }]}), encoding="utf-8")
    return InstrumentCatalog(tmp_path / "instruments.json")


def test_openai_compatible_client_requests_json_without_logging_key():
    api_response = {"choices": [{"message": {"content": json.dumps({"candidates": []})}}]}

    def opener(request, timeout):
        assert timeout == 60
        assert request.full_url == "https://api.deepseek.com/chat/completions"
        assert dict((k.lower(), v) for k, v in request.header_items())["authorization"] == "Bearer secret"
        body = json.loads(request.data)
        assert body["response_format"] == {"type": "json_object"}
        return io.BytesIO(json.dumps(api_response).encode())

    result = OpenAICompatibleJSONClient(api_key="secret", opener=opener).complete_json("json system", "{}")
    assert result == {"candidates": []}


def test_openai_compatible_chat_bounds_history_and_returns_text():
    api_response = {"choices": [{"message": {"content": "  风险主要来自波动与回撤。  "}}]}

    def opener(request, timeout):
        assert timeout == 75
        body = json.loads(request.data)
        assert body["messages"][0] == {"role": "system", "content": "system"}
        assert len(body["messages"]) == 13  # system + latest 12 turns
        assert body["messages"][1]["content"] == "q3"
        return io.BytesIO(json.dumps(api_response, ensure_ascii=False).encode())

    messages = [{"role": "user", "content": f"q{index}"} for index in range(15)]
    answer = OpenAICompatibleJSONClient(api_key="secret", opener=opener).chat("system", messages)
    assert answer == "风险主要来自波动与回撤。"


def test_optimizer_saves_active_profile_and_service_uses_it(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    catalog = _catalog(tmp_path)
    profile = InstrumentStrategyOptimizer("demo", catalog=catalog).optimize(apply=True)
    assert profile.active
    assert len(profile.buy_bias_levels) == 4
    assert profile.buy_bias_levels == tuple(sorted(profile.buy_bias_levels, reverse=True))
    assert profile.sell_bias_levels == tuple(sorted(profile.sell_bias_levels))
    assert profile.validation["validation_days"] >= 120
    saved = load_strategy_profile("demo")
    assert saved is not None and saved.active
    signal = MarketService("demo", catalog=catalog).signal()
    assert signal["strategy_profile"]["model"] == "quantile-baseline"
    assert signal["accumulation"]["score"] <= 3.0
    assert signal["reduction"]["score"] <= 40.0
    set_strategy_profile_active("demo", False)
    default_signal = MarketService("demo", catalog=catalog).signal()
    assert "strategy_profile" not in default_signal


def test_free_analysis_context_is_compact_and_marks_data_cutoff(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    catalog = _catalog(tmp_path)
    context = build_analysis_context("demo", catalog=catalog)
    assert context["instrument"]["symbol"] == "demo"
    assert context["context_policy"]["raw_history_transmitted"] is False
    assert context["context_policy"]["data_cutoff"] == context["latest"]["date"]
    assert "history" not in context
    prompt = analysis_system_prompt(context)
    assert "不得生成或执行自动交易指令" in prompt
    assert "Demo Stock" in prompt


def test_ai_candidate_is_locally_clamped_and_validated():
    candidate = InstrumentStrategyOptimizer._validate_candidate({
        "name": "wide", "buy_bias_levels": [-0.005, -0.08, -0.15, -0.9],
        "sell_bias_levels": [0.01, 0.15, 0.30, 0.90],
        "rsi_oversold": 70, "rsi_extreme": 5, "rationale": "test",
    })
    assert candidate["buy_bias_levels"] == [-0.01, -0.08, -0.15, -0.35]
    assert candidate["sell_bias_levels"] == [0.03, 0.15, 0.30, 0.50]
    assert candidate["rsi_oversold"] == 45
    assert candidate["rsi_extreme"] == 15

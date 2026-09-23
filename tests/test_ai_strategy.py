from __future__ import annotations

import io
import json

import numpy as np
import pandas as pd

from csi300_service.ai_strategy import (
    InstrumentStrategyOptimizer, OpenAICompatibleJSONClient, load_strategy_profile,
    set_strategy_profile_active,
)
from csi300_service.ai_chat import analysis_system_prompt, build_analysis_context, free_chat_system_prompt
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


def test_free_chat_prompt_does_not_claim_market_context():
    prompt = free_chat_system_prompt()
    assert "通用 AI 助手" in prompt
    assert "没有附带任何行情" in prompt
    assert "本地 CSV 数据" in prompt


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


def test_preview_preserves_existing_active_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    optimizer = InstrumentStrategyOptimizer("demo", catalog=_catalog(tmp_path))
    original = optimizer.optimize(apply=True)
    preview = optimizer.optimize(apply=False, persist=False)
    assert not preview.active
    assert load_strategy_profile("demo") == original
    applied = optimizer.apply_profile(preview)
    assert applied.active
    assert load_strategy_profile("demo") == applied


def test_nonfinite_candidates_are_rejected():
    import pytest
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="有限数值"):
            InstrumentStrategyOptimizer._validate_candidate({
                "buy_bias_levels": [-0.02, -0.08, -0.15, value],
                "sell_bias_levels": [0.05, 0.1, 0.2, 0.3],
                "rsi_oversold": 35, "rsi_extreme": 20,
            })


def test_provider_errors_do_not_expose_secrets():
    import pytest
    from urllib.error import HTTPError
    def opener(request, timeout):
        raise HTTPError(request.full_url, 401, "secret credential", {}, None)
    client = OpenAICompatibleJSONClient(api_key="secret", opener=opener)
    for call in (lambda: client.chat("system", [{"role": "user", "content": "hi"}]),
                 lambda: client.complete_json("system", "{}")):
        with pytest.raises(RuntimeError) as error:
            call()
        assert "无效或已过期" in str(error.value)
        assert "secret" not in str(error.value)


def test_json_client_rejects_non_object_response():
    import pytest
    response = io.BytesIO(json.dumps({"choices": [{"message": {"content": "[]"}}]}).encode())
    client = OpenAICompatibleJSONClient(api_key="secret", opener=lambda *a, **k: response)
    with pytest.raises(RuntimeError, match="响应格式"):
        client.complete_json("system", "{}")
    assert response.closed

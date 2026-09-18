import math
from types import SimpleNamespace

import pytest

from csi300_service.strategy import daily_reference
from csi300_service.service import MarketService


@pytest.mark.parametrize("bias,rate,fraction", [
    (-.05, -.02, .5), (-.10, -.02, .75), (-.15, -.02, 1),
    (.10, .02, .5), (.15, .02, .75), (.20, .02, 1),
    (-.20, .02, 0), (.20, -.02, 0), (0, .02, 0), (.20, 0, 0),
])
def test_reference_matches_one_day_holding_pnl(bias, rate, fraction):
    result = daily_reference({"date": "2026-09-17", "bias250": bias, "daily_return": rate}, 35000)
    # Yesterday's units valued at today's close are exactly 10,000.
    yesterday_close, today_close = 100, 100 * (1 + rate)
    expected_pnl = (10000 / today_close) * (today_close - yesterday_close)
    assert result["baseline_pnl"] == pytest.approx(expected_pnl)
    assert result["fraction"] == fraction
    assert result["coefficient"] == 3.5
    assert result["buy_amount"] == pytest.approx(max(-expected_pnl, 0) * fraction * 3.5)
    assert result["sell_amount"] == pytest.approx(max(expected_pnl, 0) * fraction * 3.5)


@pytest.mark.parametrize("rate,bias", [(None, 0), (-1, .2), (math.nan, .2), (.01, None)])
def test_missing_inputs_are_not_zero_trades(rate, bias):
    assert daily_reference({"daily_return": rate, "bias250": bias})["status"] == "unavailable"


@pytest.mark.parametrize("equity", [-1, math.nan, math.inf])
def test_invalid_equity(equity):
    with pytest.raises(ValueError):
        daily_reference({}, equity)


def test_index_v1_overrides_saved_active_profile(monkeypatch):
    monkeypatch.setattr("csi300_service.service.load_strategy_profile", lambda _: SimpleNamespace(active=True))
    result = MarketService().signal(20000)
    assert result["strategy_id"] == "ma_dynamic_v1"
    assert "strategy_profile" not in result
    assert result["daily_reference"]["coefficient"] == 2


def test_api_equity_scaling():
    from fastapi.testclient import TestClient
    from csi300_service.api import app
    client = TestClient(app)
    assert client.get("/signal?equity=-1").status_code == 422
    result = client.get("/signal?equity=50000").json()["daily_reference"]
    assert result["coefficient"] == 5

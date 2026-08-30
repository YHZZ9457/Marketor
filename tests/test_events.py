from csi300_service.events import EventBacktester
from csi300_service.service import CSI300Service


def test_event_backtest_deduplicates_continuous_regimes():
    result = EventBacktester(CSI300Service()).run(cooldown_trading_days=60)
    events = result["events"]
    assert events
    assert result["summary"]["event_count"] == len(events)
    assert len({event["date"] for event in events}) == len(events)
    assert all("return_250d" in event for event in events)


def test_event_backtest_validates_direction():
    try:
        EventBacktester(CSI300Service()).run(direction="sideways")
    except ValueError as exc:
        assert "direction" in str(exc)
    else:
        raise AssertionError("invalid direction should fail")

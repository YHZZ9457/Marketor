from threading import Thread
from unittest.mock import Mock, patch

from csi300_service.ui_tasks import UIQueue
from csi300_service.desktop import MarketDesktopApp


def test_workers_only_enqueue_and_closed_owners_are_skipped():
    root = Mock()
    queue = UIQueue(root)
    root.reset_mock()
    callback = Mock()
    owner = Mock()
    owner.winfo_exists.return_value = False
    worker = Thread(target=lambda: queue.post(callback, "result", owner=owner))
    worker.start()
    worker.join()
    assert not root.mock_calls
    assert not owner.mock_calls
    queue.drain()
    callback.assert_not_called()
    queue.post(callback, "live")
    queue.drain()
    callback.assert_called_once_with("live")


def test_callback_error_does_not_block_other_results():
    root = Mock()
    queue = UIQueue(root)
    callback = Mock(side_effect=ValueError("bad callback"))
    next_callback = Mock()
    queue.post(callback)
    queue.post(next_callback)
    queue.drain()
    next_callback.assert_called_once()
    root.report_callback_exception.assert_called_once()


def test_stale_success_and_failure_cannot_replace_latest_selection():
    app = MarketDesktopApp.__new__(MarketDesktopApp)
    app._load_generation = 2
    app._render, app._show_error = Mock(), Mock()
    app._finish_load(1, {"symbol": "old"}, None)
    app._finish_load(1, None, "old error")
    app._render.assert_not_called()
    app._show_error.assert_not_called()
    app._finish_load(2, {"symbol": "current"}, None)
    app._render.assert_called_once_with({"symbol": "current"})


def test_update_failure_is_delivered_to_ui():
    app = MarketDesktopApp.__new__(MarketDesktopApp)
    app.catalog, app._post_ui = Mock(), Mock()
    with patch("csi300_service.desktop.MarketDataUpdater", side_effect=ValueError("broken provider")):
        app._run_online_update("demo", "auto")
    app._post_ui.assert_called_once_with(app._custom_online_update_failed, "broken provider")


def test_reference_edit_preserves_signal_tiers_and_reasons():
    app = MarketDesktopApp.__new__(MarketDesktopApp)
    app.current_reference = {"status": "ok", "baseline_buy": 50, "baseline_sell": 0}
    app.reference_equity = Mock(get=lambda: "50,000")
    app.reference_text = Mock()
    app.buy_widgets = {"score": Mock(), "reasons": Mock(), "level": Mock()}
    app.sell_widgets = {"score": Mock(), "reasons": Mock(), "level": Mock()}
    app._update_reference()
    assert "250.00" in app.reference_text.configure.call_args.kwargs["text"]
    for widgets in (app.buy_widgets, app.sell_widgets):
        for widget in widgets.values():
            widget.configure.assert_not_called()


def test_v1_percentage_label_describes_daily_pnl():
    widgets = {key: Mock() for key in ("level", "score", "action", "reasons")}
    MarketDesktopApp._render_signal(widgets, {"side": "buy", "level": "三档", "score": 100, "condition": "亏损", "suggested_action": "example", "reasons": []}, "%")
    assert widgets["level"].configure.call_args.kwargs["text"] == "三档 · 当日亏损比例"

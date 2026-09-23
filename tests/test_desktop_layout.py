"""Real Tk geometry checks; skipped where the Tk display is unavailable."""
import tkinter as tk
from unittest.mock import patch

import pytest

from csi300_service.desktop import MarketDesktopApp, THEMES
from csi300_service.service import MarketService


@pytest.fixture(autouse=True)
def isolated_user_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))


@pytest.fixture(scope="module")
def market_payload():
    service = MarketService("csi300")
    return {
        "metadata": service.metadata(), "latest": service.latest(),
        "signal": service.signal(), "indicators": service.indicators(250),
        "returns": service.holding_returns((30, 365, 730, 1095, 1825)),
    }


@pytest.mark.parametrize("width,height", [(980, 700), (1280, 850), (1600, 1000)])
def test_workspace_controls_fit_and_content_can_scroll(width, height, market_payload):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    try:
        root.withdraw()
        with patch.object(MarketDesktopApp, "refresh"):
            app = MarketDesktopApp(root)
        app._render(market_payload)
        root.minsize(1, 1)
        root.geometry(f"{width}x{height}")
        root.deiconify()
        root.update()
        clipped = []
        for widget in app._walk_widgets(root):
            if widget.winfo_manager() and widget.master != app.content_canvas:
                if widget.winfo_x() + widget.winfo_width() > widget.master.winfo_width() + 2:
                    clipped.append(str(widget))
        assert not clipped, clipped
        assert app.chart.winfo_width() >= 300
        assert app.content_canvas.bbox("all")[3] >= app.returns_table.winfo_height()
        app.content_canvas.yview_moveto(1)
        root.update()
        assert app.content_canvas.yview()[1] == 1.0
        assert len(app.returns_table.get_children()) == 5
        with patch("csi300_service.desktop.save_theme"):
            for theme in THEMES:
                app.theme_var.set(theme)
                app._on_theme_change(None)
                root.update()
                assert root.cget("bg") == THEMES[theme]["bg"]
    finally:
        root.destroy()


@pytest.mark.parametrize("open_dialog", ["open_ai_chat", "open_strategy_rules"])
def test_dialog_controls_fit_at_minimum_width(open_dialog):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    try:
        root.withdraw()
        with patch.object(MarketDesktopApp, "refresh"):
            app = MarketDesktopApp(root)
        with patch("csi300_service.chat_window.build_analysis_context", side_effect=AssertionError("free chat must not read market data")):
            getattr(app, open_dialog)()
        dialog = next(widget for widget in root.winfo_children() if isinstance(widget, tk.Toplevel))
        dialog.geometry("720x600")
        root.update()
        for widget in app._walk_widgets(dialog):
            if widget.winfo_manager():
                assert widget.winfo_x() + widget.winfo_width() <= widget.master.winfo_width() + 2, str(widget)
    finally:
        root.destroy()


def test_chat_failure_can_retry_without_duplicate_question(monkeypatch):
    from csi300_service.chat_client import ChatResult
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    class ImmediateThread:
        def __init__(self, target, **kwargs):
            self.target = target
        def start(self):
            self.target()
    try:
        root.withdraw()
        with patch.object(MarketDesktopApp, "refresh"):
            app = MarketDesktopApp(root)
        app.open_ai_chat()
        chat = app.chat_workspace
        chat.input.insert("1.0", "解释 MA250")
        with patch("csi300_service.chat_window.threading.Thread", ImmediateThread), patch("csi300_service.chat_window.StreamingChatClient.stream_chat", side_effect=[RuntimeError("network"), ChatResult("answer")]) as stream:
            chat.send()
            app._ui_queue.drain()
            assert chat.regenerate_button.cget("state") == "normal"
            chat.regenerate()
            app._ui_queue.drain()
            assert stream.call_count == 2
            assert stream.call_args_list[0].args[1] == stream.call_args_list[1].args[1] == [{"role": "user", "content": "解释 MA250"}]
            assert chat.send_button.cget("state") == "normal"
            assert chat.stop_button.cget("state") == "disabled"
            assert [m["status"] for m in chat.session.messages] == ["complete", "error", "complete"]
            chat.input.insert("1.0", "未发送的草稿")
            session_id = chat.current_id
            chat.close()
            app.open_ai_chat()
            restored = app.chat_workspace
            assert restored.current_id == session_id
            assert restored.session.messages[-1]["content"] == "answer"
            assert restored.input.get("1.0", "end-1c") == "未发送的草稿"
    finally:
        root.destroy()


def test_stream_switch_stop_and_stale_events_are_isolated(monkeypatch):
    from csi300_service.chat_client import ChatResult
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    try:
        root.withdraw()
        with patch.object(MarketDesktopApp, "refresh"):
            app = MarketDesktopApp(root)
        app.open_ai_chat()
        chat = app.chat_workspace
        with patch("csi300_service.chat_window.threading.Thread"):
            chat.input.insert("1.0", "first")
            chat.send()
            first_id, first_token = chat.current_id, chat.runs[chat.current_id]["token"]
            chat._chunk(first_id, first_token, "hello")
            assert "hello" in chat.transcript.get("1.0", "end")
            chat.new_chat()
            second_id = chat.current_id
            chat._chunk(first_id, first_token, " world")
            assert "hello" not in chat.transcript.get("1.0", "end")
            chat._switch(first_id)
            assert "hello world" in chat.transcript.get("1.0", "end")
            chat.stop()
            chat._chunk(first_id, first_token, "late")
            chat._finished(first_id, first_token, ChatResult("late complete"), None)
            assert chat.session.messages[-1]["content"] == "hello world"
            assert chat.session.messages[-1]["status"] == "stopped"
            chat.regenerate()
            new_token = chat.runs[first_id]["token"]
            assert new_token != first_token
            chat._finished(first_id, first_token, ChatResult("old result"), None)
            assert first_id in chat.runs
            chat._finished(first_id, new_token, ChatResult("new result"), None)
            assert chat.session.messages[-1]["content"] == "new result"
            assert chat.sessions[second_id].messages == []
    finally:
        root.destroy()


def test_chat_settings_and_markdown_rendering():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    try:
        root.withdraw()
        with patch.object(MarketDesktopApp, "refresh"):
            app = MarketDesktopApp(root)
        app.open_ai_chat()
        chat = app.chat_workspace
        chat.session.add("assistant", "# 标题\n**重点**\n```python\nprint('safe')\n```", model="test")
        chat._render()
        assert chat.transcript.tag_ranges("heading")
        assert chat.transcript.tag_ranges("bold")
        assert chat.transcript.tag_ranges("code")
        chat.open_settings()
        root.update()
        dialog = chat.settings_window
        for widget in app._walk_widgets(dialog):
            if widget.winfo_manager():
                assert widget.winfo_x() + widget.winfo_width() <= widget.master.winfo_width() + 2, str(widget)
        assert "api_key" not in chat.session.export_markdown()
    finally:
        root.destroy()

"""Real Tk geometry checks; skipped where the Tk display is unavailable."""
import tkinter as tk
from unittest.mock import patch

import pytest

from csi300_service.desktop import MarketDesktopApp, THEMES
from csi300_service.service import MarketService


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

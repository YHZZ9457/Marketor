from __future__ import annotations

import ctypes
from datetime import datetime
import json
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .catalog import InstrumentCatalog
from .comparison import MarketComparisonService
from .custom_instruments import CustomInstrumentManager, normalize_symbol
from .events import EventBacktester
from .online_custom import ONLINE_TYPE_LABELS, OnlineCustomInstrumentManager, OnlineImportResult
from .service import MarketService
from .updater import MarketDataUpdater, UpdateResult
from .data_sources import HITHINK_API_KEY_ENV, hithink_api_key
from .ai_strategy import (
    DEEPSEEK_API_KEY_ENV, InstrumentStrategyOptimizer, OpenAICompatibleJSONClient,
    load_strategy_profile, set_strategy_profile_active,
)
from .ai_chat import analysis_system_prompt, build_analysis_context, free_chat_system_prompt


THEMES = {
    "墨绿夜色": {
        "bg": "#07110f", "panel": "#10231f", "panel_alt": "#0c1c19", "line": "#29433c",
        "text": "#eff8f4", "muted": "#91aaa2", "soft_text": "#c4d3ce", "mint": "#72e6bc",
        "cyan": "#5fc9db", "gold": "#e6bd70", "coral": "#ff927d", "violet": "#c3b3f0",
        "selected": "#23493f",
        "button": "#17312b", "button_hover": "#21473d", "rank_button": "#172d31", "rank_hover": "#214148",
    },
    "深海蓝": {
        "bg": "#07101f", "panel": "#101d32", "panel_alt": "#0b1729", "line": "#273b58",
        "text": "#f2f6ff", "muted": "#8fa4c4", "soft_text": "#c5d0e3", "mint": "#56ddb2",
        "cyan": "#69c8ff", "gold": "#f3c969", "coral": "#ff8d9b", "violet": "#b9a6f5",
        "selected": "#20466a",
        "button": "#163451", "button_hover": "#205076", "rank_button": "#253052", "rank_hover": "#34446e",
    },
    "石墨紫": {
        "bg": "#111018", "panel": "#1d1b29", "panel_alt": "#171522", "line": "#39354b",
        "text": "#f6f3ff", "muted": "#aaa4be", "soft_text": "#d0cadc", "mint": "#75dfbc",
        "cyan": "#8bbcff", "gold": "#f0c674", "coral": "#ff8fa3", "violet": "#b39df0",
        "selected": "#493f69",
        "button": "#2d2842", "button_hover": "#423a60", "rank_button": "#252e47", "rank_hover": "#374363",
    },
    "象牙日光": {
        "bg": "#f3f0e8", "panel": "#fffdf8", "panel_alt": "#eae6dc", "line": "#d2ccbd",
        "text": "#202923", "muted": "#69756e", "soft_text": "#48564e", "mint": "#148563",
        "cyan": "#167b98", "gold": "#a66d12", "coral": "#c64f43", "violet": "#6a4fa3",
        "selected": "#cde6dc",
        "button": "#dcece5", "button_hover": "#c6dfd4", "rank_button": "#dce8ed", "rank_hover": "#c6dce4",
    },
}
DEFAULT_THEME = "墨绿夜色"
COLORS = dict(THEMES[DEFAULT_THEME])

PERIODS = {"半年": 120, "1年": 250, "2年": 500, "4年": 1000}
DATA_SOURCES = {
    "自动": "auto", "同花顺官方": "hithink", "BaoStock": "baostock", "腾讯": "tencent",
    "东方财富": "eastmoney", "新浪全球": "sina", "Tushare": "tushare", "仅本地": "local",
}
TOOL_MENU_GROUPS = {
    "研究": ("指数排名", "AI 策略优化"),
    "添加标的": ("联网添加", "导入本地 CSV"),
    "设置": ("数据源", "主题", "API Key"),
}
MARKET_LABELS = {"CN": "中国", "US": "美国", "HK": "香港", "JP": "日本", "UK": "英国", "DE": "德国", "EU": "欧洲", "CUSTOM": "自定义"}
ASSET_CLASS_LABELS = {"index": "指数", "stock": "股票", "fund": "基金"}


def save_user_api_key(variable_name: str, value: str) -> bool:
    """Save an API key for this process and, on Windows, the current user only."""
    key = value.strip()
    if key:
        os.environ[variable_name] = key
    else:
        os.environ.pop(variable_name, None)
    if os.name != "nt":
        return False
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as registry_key:
        if key:
            winreg.SetValueEx(registry_key, variable_name, 0, winreg.REG_SZ, key)
        else:
            try:
                winreg.DeleteValue(registry_key, variable_name)
            except FileNotFoundError:
                pass
    try:
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, None)
    except (AttributeError, OSError):
        pass
    return True


def save_hithink_api_key(value: str) -> bool:
    return save_user_api_key(HITHINK_API_KEY_ENV, value)


def combobox_popup_options(colors: dict[str, str]) -> dict[str, object]:
    """Return classic Tk listbox options used by ttk combobox popdowns."""
    return {
        "-background": colors["panel"],
        "-foreground": colors["text"],
        "-selectbackground": colors["selected"],
        "-selectforeground": colors["text"],
        "-font": "{Microsoft YaHei UI} 11",
        "-activestyle": "none",
        "-borderwidth": 0,
        "-highlightthickness": 1,
        "-highlightbackground": colors["line"],
        "-highlightcolor": colors["mint"],
    }


def enable_high_dpi_awareness() -> None:
    """Enable crisp per-monitor rendering before creating the Tk root window."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def calculate_window_size(screen_width: int, screen_height: int, scale: float) -> tuple[int, int]:
    scale = max(1.0, min(float(scale), 2.5))
    width = min(round(1280 * scale), round(screen_width * 0.92))
    height = min(round(850 * scale), round(screen_height * 0.90))
    return max(width, min(960, screen_width)), max(height, min(680, screen_height))


def _theme_settings_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MarketCompass"
    return base / "settings.json"


def _app_icon_path() -> Path:
    """Locate the bundled Windows icon in source and PyInstaller builds."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return bundle_root / "assets" / "app-icon.ico"


def load_theme() -> str:
    try:
        value = json.loads(_theme_settings_path().read_text(encoding="utf-8")).get("theme")
        return value if value in THEMES else DEFAULT_THEME
    except (OSError, ValueError, TypeError):
        return DEFAULT_THEME


def save_theme(name: str) -> None:
    path = _theme_settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"theme": name}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # A read-only profile should not prevent the application from running.


def format_number(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


def format_pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:+.{digits}%}"


def direction_color(value: float | None) -> str:
    if value is None or value == 0:
        return COLORS["text"]
    return COLORS["mint"] if value > 0 else COLORS["coral"]


class LineChart(tk.Canvas):
    SERIES = (
        ("close", "收盘价", "text", 2),
        ("ma60", "MA60", "violet", 1),
        ("ma250", "MA250", "mint", 1),
        ("ma500", "MA500", "gold", 1),
        ("ma1250", "MA1250", "cyan", 1),
    )

    def __init__(self, master: tk.Misc):
        super().__init__(master, bg=COLORS["panel"], highlightthickness=0, height=330)
        self.rows: list[dict[str, Any]] = []
        self.bind("<Configure>", lambda _event: self.redraw())

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width, height = max(self.winfo_width(), 400), max(self.winfo_height(), 240)
        if not self.rows:
            self.create_text(width / 2, height / 2, text="暂无行情数据", fill=COLORS["muted"], font=("Microsoft YaHei UI", 11))
            return
        left, right, top, bottom = 18, 76, 28, 34
        values = [float(row[key]) for row in self.rows for key, *_ in self.SERIES if row.get(key) is not None]
        low, high = min(values), max(values)
        padding = max((high - low) * 0.08, high * 0.01)
        low, high = low - padding, high + padding
        plot_w, plot_h = width - left - right, height - top - bottom
        x = lambda index: left + index / max(1, len(self.rows) - 1) * plot_w
        y = lambda value: top + (high - value) / max(high - low, 1e-9) * plot_h

        for index in range(5):
            grid_y = top + index / 4 * plot_h
            self.create_line(left, grid_y, width - right, grid_y, fill=COLORS["line"])
            self.create_text(width - right + 10, grid_y, anchor="w", text=f"{high - index / 4 * (high - low):,.0f}", fill=COLORS["muted"], font=("Segoe UI", 9))
        for index, anchor in ((0, "w"), (len(self.rows) // 2, "center"), (len(self.rows) - 1, "e")):
            self.create_text(x(index), height - 12, anchor=anchor, text=self.rows[index]["date"], fill=COLORS["muted"], font=("Segoe UI", 9))

        for key, _label, color_key, line_width in reversed(self.SERIES):
            segment: list[float] = []
            for index, row in enumerate(self.rows):
                value = row.get(key)
                if value is None:
                    if len(segment) >= 4:
                        self.create_line(*segment, fill=COLORS[color_key], width=line_width, smooth=False)
                    segment = []
                else:
                    segment.extend((x(index), y(float(value))))
            if len(segment) >= 4:
                self.create_line(*segment, fill=COLORS[color_key], width=line_width, smooth=False)


class MarketDesktopApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.theme_name = load_theme()
        COLORS.clear()
        COLORS.update(THEMES[self.theme_name])
        self.catalog = InstrumentCatalog()
        self.custom_manager = CustomInstrumentManager()
        self.online_custom_manager = OnlineCustomInstrumentManager(self.custom_manager)
        self.instruments = self.catalog.list(include_unavailable=False)
        self.current_symbol = self.instruments[0].symbol
        self.provider_status = "当前数据源：本地 CSV · 在线状态：待检查"
        self._configure_scaling()
        self._configure_window()
        self._configure_styles()
        self._build_ui()
        self.refresh()

    def _configure_scaling(self) -> None:
        dpi = float(self.root.winfo_fpixels("1i"))
        self.ui_scale = max(1.0, min(dpi / 96.0, 2.5))
        self.root.tk.call("tk", "scaling", dpi / 72.0)

    def _configure_window(self) -> None:
        self.root.title("市场航图 · 本地行情分析")
        icon_path = _app_icon_path()
        if icon_path.exists():
            self.root.iconbitmap(default=str(icon_path))
        screen_width, screen_height = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        width, height = calculate_window_size(screen_width, screen_height, self.ui_scale)
        left, top = max(0, (screen_width - width) // 2), max(0, (screen_height - height) // 2)
        self.root.geometry(f"{width}x{height}+{left}+{top}")
        self.root.minsize(min(round(980 * self.ui_scale), width), min(round(700 * self.ui_scale), height))
        self.root.configure(bg=COLORS["bg"])

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Toolbar.TCombobox", fieldbackground=COLORS["panel_alt"], background=COLORS["panel_alt"], foreground=COLORS["text"], arrowcolor=COLORS["mint"], bordercolor=COLORS["line"], lightcolor=COLORS["line"], darkcolor=COLORS["line"], padding=(10, 7), arrowsize=16, font=("Microsoft YaHei UI", 10))
        style.map("Toolbar.TCombobox", fieldbackground=[("readonly", COLORS["panel_alt"])], foreground=[("readonly", COLORS["text"])], bordercolor=[("focus", COLORS["mint"])])
        style.configure("Dropdown.Vertical.TScrollbar", background=COLORS["button"], troughcolor=COLORS["panel_alt"], arrowcolor=COLORS["mint"], bordercolor=COLORS["line"], lightcolor=COLORS["line"], darkcolor=COLORS["line"])
        style.configure("Treeview", background=COLORS["panel"], fieldbackground=COLORS["panel"], foreground=COLORS["text"], rowheight=31, borderwidth=0, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", background=COLORS["panel_alt"], foreground=COLORS["muted"], relief="flat", padding=(8, 9), font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Treeview", background=[("selected", COLORS["selected"])], foreground=[("selected", COLORS["text"])])
        style.configure("Main.TNotebook", background=COLORS["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("Main.TNotebook.Tab", background=COLORS["panel_alt"], foreground=COLORS["muted"], padding=(18, 9), borderwidth=0, font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Main.TNotebook.Tab", background=[("selected", COLORS["panel"])], foreground=[("selected", COLORS["mint"])])

    def _label(self, parent: tk.Misc, text: str, size: int = 10, color: str | None = None, weight: str = "normal", **kwargs: Any) -> tk.Label:
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color or COLORS["text"], font=("Microsoft YaHei UI", size, weight), **kwargs)

    def _panel(self, parent: tk.Misc) -> tk.Frame:
        return tk.Frame(parent, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1, padx=20, pady=17)

    def _build_ui(self) -> None:
        outer = tk.Frame(self.root, bg=COLORS["bg"], padx=22, pady=18)
        outer.pack(fill="both", expand=True)

        accent_line = tk.Frame(outer, bg=COLORS["mint"], height=3)
        accent_line.pack(fill="x", pady=(0, 12))
        header = tk.Frame(outer, bg=COLORS["bg"])
        header.pack(fill="x", pady=(0, 12))
        title_block = tk.Frame(header, bg=COLORS["panel"])
        title_block.configure(bg=COLORS["bg"])
        title_block.pack(side="left")
        eyebrow = tk.Frame(title_block, bg=COLORS["bg"])
        eyebrow.pack(anchor="w")
        self._label(eyebrow, "MARKET COMPASS", 8, COLORS["mint"], "bold").pack(side="left")
        self._label(eyebrow, "  LOCAL · v0.19.0", 8, COLORS["muted"], "bold").pack(side="left")
        self._label(title_block, "市场航图", 23, weight="bold").pack(anchor="w", pady=(2, 0))
        self._label(title_block, "先看结论，再展开研究", 9, COLORS["muted"]).pack(anchor="w", pady=(2, 0))

        self.source_var = tk.StringVar(value="自动")
        self.theme_var = tk.StringVar(value=self.theme_name)
        self._build_more_menu(header).pack(side="right", anchor="s")

        toolbar = self._panel(outer)
        toolbar.configure(padx=16, pady=12)
        toolbar.pack(fill="x", pady=(0, 10))
        selectors = tk.Frame(toolbar, bg=COLORS["panel"])
        selectors.pack(side="left", fill="x", expand=True)
        self.symbol_choices = self._build_symbol_choices()
        names = list(self.symbol_choices)
        self.symbol_var = tk.StringVar(value=names[0])
        self.symbol_box = self._selector_control(selectors, "当前标的", self.symbol_var, names, 28, self._on_symbol_change)
        self.period_var = tk.StringVar(value="1年")
        self._selector_control(selectors, "查看范围", self.period_var, list(PERIODS), 8, lambda _event: self.refresh(), last=True)
        buttons = tk.Frame(toolbar, bg=COLORS["panel"])
        buttons.pack(side="right", padx=(14, 0), anchor="s")
        self.update_button = self._action_button(buttons, "更新数据", self.update_online, "button", "mint")
        self.update_button.pack(side="left", padx=(0, 8))
        self._action_button(buttons, "AI 对话", self.open_ai_chat, "rank_button", "cyan").pack(side="left", padx=(0, 8))
        self.refresh_button = self._action_button(buttons, "刷新", self.refresh, "mint", "bg")
        self.refresh_button.pack(side="left")

        self.status_var = tk.StringVar(value="正在读取本地行情…")
        self._label(outer, "", 8, COLORS["cyan"], textvariable=self.status_var).pack(fill="x", pady=(0, 8))

        summary = self._panel(outer)
        summary.configure(padx=18, pady=14)
        summary.pack(fill="x", pady=(0, 10))
        summary_title = tk.Frame(summary, bg=COLORS["panel"])
        summary_title.pack(fill="x", pady=(0, 10))
        self._label(summary_title, "当前辅助信号", 12, weight="bold").pack(side="left")
        self._label(summary_title, "仅供决策参考，不构成投资建议", 8, COLORS["muted"]).pack(side="right")
        summary_body = tk.Frame(summary, bg=COLORS["panel"])
        summary_body.pack(fill="x")
        summary_body.grid_columnconfigure(0, weight=1, uniform="signal")
        summary_body.grid_columnconfigure(1, weight=1, uniform="signal")
        self.buy_widgets = self._signal_summary(summary_body, 0, "加仓", COLORS["mint"])
        self.sell_widgets = self._signal_summary(summary_body, 1, "减仓", COLORS["coral"])

        cards = tk.Frame(outer, bg=COLORS["bg"])
        cards.pack(fill="x", pady=(0, 10))
        for index in range(4):
            cards.grid_columnconfigure(index, weight=1, uniform="metric")
        self.price_card = self._metric_card(cards, 0, "最新收盘", "price", "cyan")
        self.bias_card = self._metric_card(cards, 1, "MA250 乖离", "bias", "mint")
        self.rsi_card = self._metric_card(cards, 2, "RSI14", "rsi", "gold")
        self.drawdown_card = self._metric_card(cards, 3, "250日高点回撤", "drawdown", "coral")

        notebook = ttk.Notebook(outer, style="Main.TNotebook")
        notebook.pack(fill="both", expand=True)
        chart_panel = self._panel(notebook)
        notebook.add(chart_panel, text="趋势图")
        chart_head = tk.Frame(chart_panel, bg=COLORS["panel"])
        chart_head.pack(fill="x")
        self._label(chart_head, "收盘价与长期均线", 13, weight="bold").pack(side="left")
        legend = tk.Frame(chart_head, bg=COLORS["panel"])
        legend.pack(side="right")
        for _key, name, color_key, _width in LineChart.SERIES:
            item = tk.Frame(legend, bg=COLORS["panel"]); item.pack(side="left", padx=(10, 0))
            tk.Label(item, text="━", bg=COLORS["panel"], fg=COLORS[color_key]).pack(side="left")
            self._label(item, name, 8, COLORS["muted"]).pack(side="left", padx=(3, 0))
        self.chart = LineChart(chart_panel)
        self.chart.pack(fill="both", expand=True, pady=(8, 0))

        returns_panel = self._panel(notebook)
        notebook.add(returns_panel, text="历史收益")
        returns_head = tk.Frame(returns_panel, bg=COLORS["panel"])
        returns_head.pack(fill="x", pady=(0, 8))
        self._label(returns_head, "历史持有收益", 12, weight="bold").pack(side="left")
        self._label(returns_head, "自然日口径 · 收益基于最接近的后续交易日", 8, COLORS["muted"]).pack(side="right")
        columns = ("period", "samples", "mean", "median", "positive", "min", "max")
        self.returns_table = ttk.Treeview(returns_panel, columns=columns, show="headings", height=8)
        headings = ("持有期", "样本数", "平均收益", "中位数", "正收益率", "最差", "最好")
        for column, heading in zip(columns, headings):
            self.returns_table.heading(column, text=heading)
            self.returns_table.column(column, anchor="center", width=105, stretch=True)
        self.returns_table.pack(fill="both", expand=True)

    def _action_button(self, parent: tk.Misc, text: str, command: Any, background: str, foreground: str) -> tk.Button:
        return tk.Button(
            parent, text=text, command=command, bg=COLORS[background], fg=COLORS[foreground],
            activebackground=COLORS["button_hover"], activeforeground=COLORS["text"], relief="flat",
            padx=16, pady=8, cursor="hand2", font=("Microsoft YaHei UI", 9, "bold"),
        )

    def _build_more_menu(self, parent: tk.Misc) -> tk.Menubutton:
        button = tk.Menubutton(
            parent, text="更多工具  ▾", bg=COLORS["button"], fg=COLORS["text"],
            activebackground=COLORS["button_hover"], activeforeground=COLORS["text"], relief="flat",
            padx=16, pady=9, cursor="hand2", font=("Microsoft YaHei UI", 9, "bold"),
        )
        menu_options = {
            "tearoff": False, "bg": COLORS["panel"], "fg": COLORS["text"],
            "activebackground": COLORS["selected"], "activeforeground": COLORS["text"],
            "font": ("Microsoft YaHei UI", 10), "borderwidth": 1,
        }
        menu = tk.Menu(button, **menu_options)
        menu.add_command(label="指数横向排名", command=self.open_comparison)
        menu.add_command(label="AI 策略优化", command=self.open_ai_strategy)
        menu.add_separator()
        menu.add_command(label="联网添加标的", command=self.add_online_instrument)
        menu.add_command(label="导入本地 CSV", command=self.import_local_csv)
        menu.add_separator()
        source_menu = tk.Menu(menu, **menu_options)
        for label in DATA_SOURCES:
            source_menu.add_radiobutton(label=label, variable=self.source_var, value=label)
        menu.add_cascade(label="在线数据源", menu=source_menu)
        theme_menu = tk.Menu(menu, **menu_options)
        for name in THEMES:
            theme_menu.add_radiobutton(label=name, variable=self.theme_var, value=name, command=lambda: self._on_theme_change(None))
        menu.add_cascade(label="界面主题", menu=theme_menu)
        menu.add_command(label="配置 API Key", command=self.configure_api_key)
        button.configure(menu=menu)
        self._themed_menus = (menu, source_menu, theme_menu)
        return button

    def _metric_card(self, parent: tk.Misc, column: int, title: str, name: str, accent_key: str) -> dict[str, tk.Label]:
        panel = self._panel(parent)
        panel.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 5, 0 if column == 3 else 5))
        tk.Frame(panel, bg=COLORS[accent_key], height=3).pack(fill="x", pady=(0, 13))
        heading = tk.Frame(panel, bg=COLORS["panel"])
        heading.pack(fill="x")
        self._label(heading, title.upper(), 8, COLORS["muted"], "bold").pack(side="left")
        self._label(heading, "●", 7, COLORS[accent_key]).pack(side="right")
        value = self._label(panel, "—", 22, weight="bold")
        value.pack(anchor="w", pady=(7, 2))
        detail = self._label(panel, "—", 8, COLORS["muted"])
        detail.pack(anchor="w")
        return {"value": value, "detail": detail, "name": name}

    def _signal_summary(self, parent: tk.Misc, column: int, title: str, accent: str) -> dict[str, tk.Label]:
        content = tk.Frame(parent, bg=COLORS["panel_alt"], padx=16, pady=12)
        content.grid(row=0, column=column, sticky="nsew", padx=(0, 6) if column == 0 else (6, 0))
        top = tk.Frame(content, bg=COLORS["panel_alt"])
        top.pack(fill="x")
        self._label(top, title, 10, COLORS["soft_text"], "bold").pack(side="left")
        level = self._label(top, "—", 8, accent, "bold")
        level.pack(side="right")
        value_row = tk.Frame(content, bg=COLORS["panel_alt"])
        value_row.pack(fill="x", pady=(7, 2))
        score = self._label(value_row, "—", 21, accent, "bold")
        score.pack(side="left")
        action = self._label(value_row, "—", 9, COLORS["text"], wraplength=370, justify="left")
        action.pack(side="left", padx=(14, 0), fill="x", expand=True)
        reasons = self._label(content, "—", 8, COLORS["muted"], wraplength=500, justify="left")
        reasons.pack(anchor="w", fill="x")
        return {"level": level, "score": score, "action": action, "reasons": reasons}

    def _selector_control(
        self,
        parent: tk.Misc,
        label: str,
        variable: tk.StringVar,
        values: list[str],
        width: int,
        command: Any | None = None,
        *,
        last: bool = False,
    ) -> ttk.Combobox:
        group = tk.Frame(parent, bg=COLORS["panel"])
        group.pack(side="left", padx=(0, 0 if last else 10))
        self._label(group, label, 8, COLORS["muted"], "bold").pack(anchor="w", pady=(0, 3))
        box = ttk.Combobox(
            group, textvariable=variable, values=values, state="readonly",
            width=width, style="Toolbar.TCombobox", height=min(16, len(values)),
        )
        box.pack(anchor="w")
        box.configure(postcommand=lambda widget=box: self._style_combobox_popup(widget))
        if command is not None:
            box.bind("<<ComboboxSelected>>", command)
        return box

    def _style_combobox_popup(self, box: ttk.Combobox) -> None:
        """Style the real popdown listbox, which is outside ttk's normal style tree."""
        try:
            popdown = str(self.root.tk.call("ttk::combobox::PopdownWindow", str(box)))
            listbox = f"{popdown}.f.l"
            scrollbar = f"{popdown}.f.sb"
            options = combobox_popup_options(COLORS)
            flattened = [value for pair in options.items() for value in pair]
            self.root.tk.call(listbox, "configure", *flattened)
            self.root.tk.call(scrollbar, "configure", "-style", "Dropdown.Vertical.TScrollbar")
        except tk.TclError:
            pass

    def _on_theme_change(self, _event: Any) -> None:
        name = self.theme_var.get()
        if name not in THEMES or name == self.theme_name:
            return
        old_colors = dict(COLORS)
        new_colors = THEMES[name]
        color_map = {old_colors[key]: new_colors[key] for key in old_colors}
        COLORS.clear()
        COLORS.update(new_colors)
        self.theme_name = name
        save_theme(name)
        self.root.configure(bg=COLORS["bg"])
        self._configure_styles()
        self._recolor_widget(self.root, color_map)
        for menu in getattr(self, "_themed_menus", ()):
            menu.configure(
                bg=COLORS["panel"], fg=COLORS["text"],
                activebackground=COLORS["selected"], activeforeground=COLORS["text"],
            )
        for widget in self._walk_widgets(self.root):
            if isinstance(widget, LineChart):
                widget.redraw()

    @classmethod
    def _walk_widgets(cls, widget: tk.Misc):
        for child in widget.winfo_children():
            yield child
            yield from cls._walk_widgets(child)

    @classmethod
    def _recolor_widget(cls, widget: tk.Misc, color_map: dict[str, str]) -> None:
        options = (
            "background", "foreground", "activebackground", "activeforeground",
            "highlightbackground", "highlightcolor", "insertbackground",
            "selectbackground", "selectforeground",
        )
        try:
            keys = widget.keys()
            updates = {}
            for option in options:
                if option in keys:
                    current = widget.cget(option)
                    if current in color_map:
                        updates[option] = color_map[current]
            if updates:
                widget.configure(**updates)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            cls._recolor_widget(child, color_map)

    def _on_symbol_change(self, _event: Any) -> None:
        self.current_symbol = self.symbol_choices[self.symbol_var.get()]
        self.refresh()

    def _build_symbol_choices(self) -> dict[str, str]:
        return {
            (
                f"[{MARKET_LABELS.get(item.market.upper(), item.market.upper())}·"
                f"{ASSET_CLASS_LABELS.get(item.asset_class, item.asset_class)}]  "
                f"{item.name}  ·  {item.provider_code or item.symbol}"
            ): item.symbol
            for item in self.instruments
        }

    def import_local_csv(self) -> None:
        source = filedialog.askopenfilename(
            parent=self.root,
            title="选择本地行情 CSV",
            filetypes=(("CSV 文件", "*.csv"), ("所有文件", "*.*")),
        )
        if not source:
            return
        self._show_import_dialog(Path(source))

    def _show_import_dialog(self, source: Path) -> None:
        window = tk.Toplevel(self.root)
        window.title("导入自定义标的 · Marketor")
        window.transient(self.root)
        window.grab_set()
        window.resizable(False, False)
        window.configure(bg=COLORS["bg"])
        panel = self._panel(window)
        panel.pack(fill="both", expand=True, padx=18, pady=18)
        self._label(panel, "导入本地 CSV", 17, weight="bold").grid(row=0, column=0, columnspan=2, sticky="w")
        self._label(panel, source.name, 9, COLORS["cyan"]).grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 14))

        try:
            default_symbol = normalize_symbol(source.stem)
        except ValueError:
            default_symbol = f"custom_{datetime.now():%Y%m%d_%H%M%S}"
        name_var = tk.StringVar(value=source.stem)
        symbol_var = tk.StringVar(value=default_symbol)
        type_var = tk.StringVar(value="指数")
        market_var = tk.StringVar(value="CUSTOM")
        currency_var = tk.StringVar(value="CNY")

        def add_entry(row: int, label: str, variable: tk.StringVar) -> tk.Entry:
            self._label(panel, label, 9, COLORS["muted"], "bold").grid(row=row, column=0, sticky="w", padx=(0, 16), pady=6)
            entry = tk.Entry(panel, textvariable=variable, width=34, bg=COLORS["panel_alt"], fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat", font=("Microsoft YaHei UI", 10))
            entry.grid(row=row, column=1, sticky="ew", pady=6, ipady=7)
            return entry

        name_entry = add_entry(2, "名称", name_var)
        add_entry(3, "代码（唯一）", symbol_var)
        self._label(panel, "类型", 9, COLORS["muted"], "bold").grid(row=4, column=0, sticky="w", padx=(0, 16), pady=6)
        type_box = ttk.Combobox(panel, textvariable=type_var, values=["指数", "股票", "基金"], state="readonly", width=31, style="Toolbar.TCombobox")
        type_box.grid(row=4, column=1, sticky="ew", pady=6)
        add_entry(5, "市场", market_var)
        add_entry(6, "币种", currency_var)
        hint = "支持 date/日期、close/收盘价/单位净值；开高低和成交额可选。"
        self._label(panel, hint, 8, COLORS["muted"], wraplength=390, justify="left").grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 12))
        actions = tk.Frame(panel, bg=COLORS["panel"])
        actions.grid(row=8, column=0, columnspan=2, sticky="e")

        def submit() -> None:
            type_codes = {"指数": "index", "股票": "stock", "基金": "fund"}
            kwargs = dict(
                symbol=symbol_var.get(), name=name_var.get(), asset_class=type_codes[type_var.get()],
                market=market_var.get(), currency=currency_var.get(),
            )
            try:
                instrument = self.custom_manager.import_csv(source, **kwargs)
            except ValueError as exc:
                if "已存在" in str(exc) and messagebox.askyesno("覆盖自定义标的", f"{exc}\n\n是否用当前 CSV 替换？", parent=window):
                    try:
                        instrument = self.custom_manager.import_csv(source, **kwargs, replace=True)
                    except Exception as replace_exc:
                        messagebox.showerror("导入失败", str(replace_exc), parent=window)
                        return
                else:
                    messagebox.showerror("导入失败", str(exc), parent=window)
                    return
            except Exception as exc:
                messagebox.showerror("导入失败", str(exc), parent=window)
                return
            window.destroy()
            self._reload_catalog(instrument.symbol)
            metadata = MarketService(instrument.symbol, catalog=self.catalog).metadata()
            messagebox.showinfo(
                "导入完成",
                f"已导入：{instrument.name}\n有效记录：{metadata['rows']:,} 条\n"
                f"日期范围：{metadata['first_date']} 至 {metadata['last_date']}",
                parent=self.root,
            )

        tk.Button(actions, text="取消", command=window.destroy, bg=COLORS["button"], fg=COLORS["text"], relief="flat", padx=16, pady=7).pack(side="left", padx=(0, 8))
        tk.Button(actions, text="导入并分析", command=submit, bg=COLORS["mint"], fg=COLORS["bg"], relief="flat", padx=18, pady=7, font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
        panel.grid_columnconfigure(1, weight=1)
        name_entry.focus_set()

    def _reload_catalog(self, selected_symbol: str) -> None:
        self.catalog = InstrumentCatalog()
        self.instruments = self.catalog.list(include_unavailable=False)
        self.symbol_choices = self._build_symbol_choices()
        self.symbol_box.configure(values=list(self.symbol_choices))
        selected_name = next(name for name, symbol in self.symbol_choices.items() if symbol == selected_symbol)
        self.symbol_var.set(selected_name)
        self.current_symbol = selected_symbol
        self.provider_status = "当前数据源：自定义本地 CSV · 在线状态：仅本地"
        self.refresh()

    def configure_api_key(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("同花顺 API Key · Marketor")
        window.transient(self.root)
        window.grab_set()
        window.resizable(False, False)
        window.configure(bg=COLORS["bg"])
        panel = self._panel(window)
        panel.pack(fill="both", expand=True, padx=18, pady=18)
        self._label(panel, "同花顺官方数据源", 17, weight="bold").pack(anchor="w")
        configured = hithink_api_key() is not None
        state_text = "已配置，可优先用于中国市场" if configured else "尚未配置"
        self._label(panel, state_text, 9, COLORS["mint"] if configured else COLORS["gold"]).pack(anchor="w", pady=(3, 14))
        self._label(panel, "API Key", 9, COLORS["muted"], "bold").pack(anchor="w", pady=(0, 5))
        value_var = tk.StringVar()
        entry = tk.Entry(
            panel, textvariable=value_var, show="●", width=48, bg=COLORS["panel_alt"],
            fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat",
            font=("Segoe UI", 10),
        )
        entry.pack(fill="x", ipady=8)
        self._label(
            panel,
            "Key 仅写入当前 Windows 用户环境变量，不写入项目、日志或 Git。留空不会覆盖现有 Key。",
            8, COLORS["muted"], wraplength=460, justify="left",
        ).pack(anchor="w", pady=(10, 14))
        actions = tk.Frame(panel, bg=COLORS["panel"])
        actions.pack(anchor="e")

        def save() -> None:
            key = value_var.get().strip()
            if not key:
                messagebox.showwarning("请输入 API Key", "请粘贴完整的同花顺 API Key。", parent=window)
                return
            try:
                save_hithink_api_key(key)
            except OSError as exc:
                messagebox.showerror("保存失败", str(exc), parent=window)
                return
            value_var.set("")
            window.destroy()
            self.status_var.set("同花顺 API Key 已配置 · 中国市场自动更新将优先尝试官方数据源")
            messagebox.showinfo("配置完成", "API Key 已保存到当前 Windows 用户环境。", parent=self.root)

        tk.Button(actions, text="取消", command=window.destroy, bg=COLORS["button"], fg=COLORS["text"], relief="flat", padx=16, pady=7).pack(side="left", padx=(0, 8))
        tk.Button(actions, text="保存 Key", command=save, bg=COLORS["mint"], fg=COLORS["bg"], relief="flat", padx=18, pady=7, font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
        entry.focus_set()

    def open_ai_strategy(self) -> None:
        instrument = self.catalog.get(self.current_symbol)
        window = tk.Toplevel(self.root)
        window.title(f"AI 个性化策略 · {instrument.name}")
        window.transient(self.root)
        window.grab_set()
        window.resizable(False, False)
        window.configure(bg=COLORS["bg"])
        panel = self._panel(window)
        panel.pack(fill="both", expand=True, padx=18, pady=18)
        self._label(panel, f"{instrument.name} · 个性化策略", 17, weight="bold").grid(row=0, column=0, columnspan=2, sticky="w")
        current = load_strategy_profile(instrument.symbol)
        state = "已有生效策略，可重新优化" if current and current.active else "尚未应用个性化策略"
        self._label(panel, state, 9, COLORS["mint"] if current else COLORS["gold"]).grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 14))

        provider_var = tk.StringVar(value="DeepSeek")
        key_var = tk.StringVar()
        base_url_var = tk.StringVar(value="https://api.deepseek.com")
        model_var = tk.StringVar(value="deepseek-v4-flash")
        status_var = tk.StringVar(value="AI 只接收训练区间统计摘要；候选参数由本地样本外回测筛选。")

        def label_at(row: int, text: str) -> None:
            self._label(panel, text, 9, COLORS["muted"], "bold").grid(row=row, column=0, sticky="w", padx=(0, 16), pady=6)

        def entry_at(row: int, variable: tk.StringVar, *, secret: bool = False) -> tk.Entry:
            entry = tk.Entry(panel, textvariable=variable, show="●" if secret else "", width=43, bg=COLORS["panel_alt"], fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat", font=("Segoe UI", 10))
            entry.grid(row=row, column=1, sticky="ew", pady=6, ipady=7)
            return entry

        label_at(2, "AI 服务")
        provider_box = ttk.Combobox(panel, textvariable=provider_var, values=["DeepSeek", "OpenAI 兼容接口"], state="readonly", width=40, style="Toolbar.TCombobox")
        provider_box.grid(row=2, column=1, sticky="ew", pady=6)
        label_at(3, "API Key")
        key_entry = entry_at(3, key_var, secret=True)
        label_at(4, "Base URL")
        entry_at(4, base_url_var)
        label_at(5, "模型")
        entry_at(5, model_var)
        self._label(panel, "约束：核心仓位≥60% · 最大加仓3× · 最大技术减仓40% · 指标定义不变", 8, COLORS["cyan"], wraplength=500, justify="left").grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 4))
        self._label(panel, "", 8, COLORS["gold"], wraplength=500, justify="left", textvariable=status_var).grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 12))
        actions = tk.Frame(panel, bg=COLORS["panel"])
        actions.grid(row=8, column=0, columnspan=2, sticky="e")

        def provider_changed(_event: Any = None) -> None:
            if provider_var.get() == "DeepSeek":
                base_url_var.set("https://api.deepseek.com")
                model_var.set("deepseek-v4-flash")
            else:
                base_url_var.set("https://api.openai.com/v1")
                model_var.set("")

        provider_box.bind("<<ComboboxSelected>>", provider_changed)

        def submit() -> None:
            env_name = DEEPSEEK_API_KEY_ENV if provider_var.get() == "DeepSeek" else "MARKETOR_AI_API_KEY"
            key = key_var.get().strip() or os.getenv(env_name, "").strip()
            if not key:
                messagebox.showwarning("需要 API Key", "请粘贴当前 AI 服务的 API Key。", parent=window)
                return
            if not base_url_var.get().strip() or not model_var.get().strip():
                messagebox.showwarning("配置不完整", "Base URL 和模型名称不能为空。", parent=window)
                return
            save_user_api_key(env_name, key)
            key_var.set("")
            optimize_button.configure(state="disabled")
            status_var.set("正在请求 AI 候选，并执行本地样本外回测…")
            client = OpenAICompatibleJSONClient(api_key=key, base_url=base_url_var.get(), model=model_var.get())

            def worker() -> None:
                try:
                    profile = InstrumentStrategyOptimizer(instrument.symbol, catalog=self.catalog).optimize(
                        client=client, provider_name=provider_var.get(), apply=True,
                    )
                    self.root.after(0, finish, profile)
                except Exception as exc:
                    self.root.after(0, failed, str(exc))

            threading.Thread(target=worker, daemon=True).start()

        def finish(profile: Any) -> None:
            window.destroy()
            metrics = profile.validation
            self.refresh()
            messagebox.showinfo(
                "AI 策略已验证并应用",
                f"标的：{profile.name}\n来源：{profile.source} · {profile.model}\n"
                f"样本外 CAGR：{metrics.get('cagr', 0):+.2%}\n"
                f"最大回撤：{metrics.get('max_drawdown', 0):+.2%}\n"
                f"Sharpe：{metrics.get('sharpe', 0):.2f}\n\n"
                f"加仓阈值：{', '.join(f'{x:+.1%}' for x in profile.buy_bias_levels)}\n"
                f"减仓阈值：{', '.join(f'{x:+.1%}' for x in profile.sell_bias_levels)}\n\n"
                "该结果仅为历史研究与辅助决策，不保证未来收益。",
                parent=self.root,
            )

        def failed(message: str) -> None:
            optimize_button.configure(state="normal")
            status_var.set(f"优化失败：{message}")

        def restore_default() -> None:
            if not current:
                return
            if not messagebox.askyesno("恢复全局策略", "停用该标的的个性化阈值，恢复项目默认策略？", parent=window):
                return
            set_strategy_profile_active(instrument.symbol, False)
            window.destroy()
            self.refresh()
            messagebox.showinfo("已恢复", f"{instrument.name} 已恢复全局默认策略。", parent=self.root)

        tk.Button(actions, text="取消", command=window.destroy, bg=COLORS["button"], fg=COLORS["text"], relief="flat", padx=16, pady=7).pack(side="left", padx=(0, 8))
        restore_button = tk.Button(actions, text="恢复全局策略", command=restore_default, state="normal" if current and current.active else "disabled", bg=COLORS["button"], fg=COLORS["coral"], relief="flat", padx=16, pady=7)
        restore_button.pack(side="left", padx=(0, 8))
        optimize_button = tk.Button(actions, text="AI 优化并应用", command=submit, bg=COLORS["mint"], fg=COLORS["bg"], relief="flat", padx=18, pady=7, font=("Microsoft YaHei UI", 9, "bold"))
        optimize_button.pack(side="left")
        panel.grid_columnconfigure(1, weight=1)
        key_entry.focus_set()

    def open_ai_chat(self) -> None:
        instrument = self.catalog.get(self.current_symbol)
        context: dict[str, Any] | None = None
        context_error = ""
        try:
            context = build_analysis_context(instrument.symbol, catalog=self.catalog)
        except Exception as exc:
            context_error = str(exc)

        window = tk.Toplevel(self.root)
        window.title("AI 自由聊天 · Marketor")
        screen_w, screen_h = window.winfo_screenwidth(), window.winfo_screenheight()
        width, height = min(940, int(screen_w * 0.88)), min(720, int(screen_h * 0.86))
        window.geometry(f"{width}x{height}")
        window.minsize(720, 560)
        window.transient(self.root)
        window.configure(bg=COLORS["bg"])

        outer = tk.Frame(window, bg=COLORS["bg"], padx=18, pady=16)
        outer.pack(fill="both", expand=True)
        header = self._panel(outer)
        header.pack(fill="x", pady=(0, 10))
        title_row = tk.Frame(header, bg=COLORS["panel"])
        title_row.pack(fill="x")
        self._label(title_row, "AI 自由聊天", 16, weight="bold").pack(side="left")
        cutoff = context["context_policy"]["data_cutoff"] if context is not None else "不可用"
        self._label(title_row, "自由对话 · 可选行情上下文", 8, COLORS["cyan"], "bold").pack(side="right")
        self._label(header, "普通聊天不会读取行情；需要分析时可手动带入当前标的摘要", 8, COLORS["muted"]).pack(anchor="w", pady=(4, 10))

        config = tk.Frame(header, bg=COLORS["panel"])
        config.pack(fill="x")
        provider_var = tk.StringVar(value="DeepSeek")
        key_var = tk.StringVar()
        base_url_var = tk.StringVar(value="https://api.deepseek.com")
        model_var = tk.StringVar(value="deepseek-v4-flash")

        def config_field(label: str, variable: tk.StringVar, width_chars: int, *, secret: bool = False) -> tk.Entry:
            group = tk.Frame(config, bg=COLORS["panel"])
            group.pack(side="left", fill="x", expand=label in {"API Key", "Base URL"}, padx=(0, 9))
            self._label(group, label, 8, COLORS["muted"], "bold").pack(anchor="w", pady=(0, 3))
            entry = tk.Entry(group, textvariable=variable, show="●" if secret else "", width=width_chars, bg=COLORS["panel_alt"], fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat", font=("Segoe UI", 9))
            entry.pack(fill="x", ipady=6)
            return entry

        provider_group = tk.Frame(config, bg=COLORS["panel"])
        provider_group.pack(side="left", padx=(0, 9))
        self._label(provider_group, "AI 服务", 8, COLORS["muted"], "bold").pack(anchor="w", pady=(0, 3))
        provider_box = ttk.Combobox(provider_group, textvariable=provider_var, values=["DeepSeek", "OpenAI 兼容接口"], state="readonly", width=16, style="Toolbar.TCombobox")
        provider_box.pack(ipady=2)
        key_entry = config_field("API Key", key_var, 18, secret=True)
        config_field("Base URL", base_url_var, 24)
        config_field("模型", model_var, 18)

        def provider_changed(_event: Any = None) -> None:
            if provider_var.get() == "DeepSeek":
                base_url_var.set("https://api.deepseek.com")
                model_var.set("deepseek-v4-flash")
            else:
                base_url_var.set("https://api.openai.com/v1")
                model_var.set("")

        provider_box.bind("<<ComboboxSelected>>", provider_changed)

        mode_bar = tk.Frame(header, bg=COLORS["panel"])
        mode_bar.pack(fill="x", pady=(11, 0))
        include_market_var = tk.BooleanVar(value=False)
        market_toggle = tk.Checkbutton(
            mode_bar, text=f"带入当前行情：{instrument.name}", variable=include_market_var,
            bg=COLORS["panel"], fg=COLORS["text"], activebackground=COLORS["panel"],
            activeforeground=COLORS["text"], selectcolor=COLORS["panel_alt"],
            font=("Microsoft YaHei UI", 9), cursor="hand2",
        )
        market_toggle.pack(side="left")
        mode_hint = self._label(mode_bar, "普通自由聊天模式", 8, COLORS["mint"], "bold")
        mode_hint.pack(side="right")
        if context is None:
            market_toggle.configure(state="disabled")
            mode_hint.configure(text=f"行情上下文不可用：{context_error}", fg=COLORS["coral"])

        transcript_panel = tk.Frame(outer, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        transcript_panel.pack(fill="both", expand=True, pady=(0, 10))
        scrollbar = ttk.Scrollbar(transcript_panel, orient="vertical", style="Dropdown.Vertical.TScrollbar")
        transcript = tk.Text(
            transcript_panel, wrap="word", state="disabled", undo=False,
            bg=COLORS["panel"], fg=COLORS["text"], insertbackground=COLORS["text"],
            selectbackground=COLORS["selected"], relief="flat", padx=16, pady=14,
            font=("Microsoft YaHei UI", 10), spacing1=3, spacing3=7,
            yscrollcommand=scrollbar.set,
        )
        scrollbar.configure(command=transcript.yview)
        scrollbar.pack(side="right", fill="y")
        transcript.pack(side="left", fill="both", expand=True)
        transcript.tag_configure("user_head", foreground=COLORS["mint"], font=("Microsoft YaHei UI", 9, "bold"))
        transcript.tag_configure("assistant_head", foreground=COLORS["cyan"], font=("Microsoft YaHei UI", 9, "bold"))
        transcript.tag_configure("system", foreground=COLORS["muted"], font=("Microsoft YaHei UI", 9))

        history: list[dict[str, str]] = []
        request_pending = False

        def append_message(role: str, content: str) -> None:
            if not window.winfo_exists():
                return
            labels = {"user": ("你", "user_head"), "assistant": ("Marketor AI", "assistant_head"), "system": ("系统", "system")}
            label, tag = labels[role]
            transcript.configure(state="normal")
            transcript.insert("end", f"{label}\n", tag)
            if role == "system":
                transcript.insert("end", f"{content.strip()}\n\n", "system")
            else:
                transcript.insert("end", f"{content.strip()}\n\n")
            transcript.configure(state="disabled")
            transcript.see("end")

        def chat_mode_message() -> str:
            if include_market_var.get() and context is not None:
                return f"行情分析模式：已带入 {instrument.name} 的本地摘要，数据截止 {cutoff}。"
            return "普通自由聊天模式：不会读取或发送本地行情数据，你可以聊任何话题。"

        append_message("system", chat_mode_message())

        input_panel = self._panel(outer)
        input_panel.pack(fill="x")
        input_box = tk.Text(
            input_panel, height=4, wrap="word", bg=COLORS["panel_alt"], fg=COLORS["text"],
            insertbackground=COLORS["text"], selectbackground=COLORS["selected"], relief="flat",
            padx=10, pady=8, font=("Microsoft YaHei UI", 10),
        )
        input_box.pack(side="left", fill="both", expand=True, padx=(0, 10))
        controls = tk.Frame(input_panel, bg=COLORS["panel"])
        controls.pack(side="right", fill="y")
        status_var = tk.StringVar(value="Ctrl+Enter 发送")
        self._label(controls, "", 8, COLORS["muted"], textvariable=status_var, wraplength=150, justify="center").pack(pady=(0, 7))

        def reset_chat() -> None:
            if request_pending:
                return
            history.clear()
            transcript.configure(state="normal")
            transcript.delete("1.0", "end")
            transcript.configure(state="disabled")
            mode_hint.configure(
                text=f"行情分析 · 截止 {cutoff}" if include_market_var.get() else "普通自由聊天模式",
                fg=COLORS["gold"] if include_market_var.get() else COLORS["mint"],
            )
            append_message("system", chat_mode_message())

        market_toggle.configure(command=reset_chat)

        def send() -> None:
            nonlocal request_pending
            if request_pending:
                return
            question = input_box.get("1.0", "end").strip()
            if not question:
                return
            if len(question) > 4000:
                messagebox.showwarning("问题过长", "单次问题请控制在 4000 字以内。", parent=window)
                return
            env_name = DEEPSEEK_API_KEY_ENV if provider_var.get() == "DeepSeek" else "MARKETOR_AI_API_KEY"
            key = key_var.get().strip() or os.getenv(env_name, "").strip()
            if not key:
                messagebox.showwarning("需要 API Key", "请在上方粘贴当前 AI 服务的 API Key。", parent=window)
                key_entry.focus_set()
                return
            if not base_url_var.get().strip() or not model_var.get().strip():
                messagebox.showwarning("配置不完整", "Base URL 和模型名称不能为空。", parent=window)
                return
            save_user_api_key(env_name, key)
            key_var.set("")
            input_box.delete("1.0", "end")
            append_message("user", question)
            history.append({"role": "user", "content": question})
            request_pending = True
            send_button.configure(state="disabled")
            clear_button.configure(state="disabled")
            status_var.set("AI 正在回复…")
            client = OpenAICompatibleJSONClient(api_key=key, base_url=base_url_var.get(), model=model_var.get())
            messages = history[-12:].copy()
            system_prompt = analysis_system_prompt(context) if include_market_var.get() and context is not None else free_chat_system_prompt()
            market_toggle.configure(state="disabled")

            def worker() -> None:
                try:
                    answer = client.chat(system_prompt, messages)
                    self.root.after(0, finish, answer)
                except Exception as exc:
                    self.root.after(0, failed, str(exc))

            threading.Thread(target=worker, daemon=True).start()

        def finish(answer: str) -> None:
            nonlocal request_pending
            if not window.winfo_exists():
                return
            request_pending = False
            history.append({"role": "assistant", "content": answer})
            append_message("assistant", answer)
            send_button.configure(state="normal")
            clear_button.configure(state="normal")
            market_toggle.configure(state="normal" if context is not None else "disabled")
            status_var.set("Ctrl+Enter 发送")
            input_box.focus_set()

        def failed(message: str) -> None:
            nonlocal request_pending
            if not window.winfo_exists():
                return
            request_pending = False
            append_message("system", f"本次对话失败：{message}")
            send_button.configure(state="normal")
            clear_button.configure(state="normal")
            market_toggle.configure(state="normal" if context is not None else "disabled")
            status_var.set("调用失败，可检查配置后重试")

        def send_shortcut(_event: Any) -> str:
            send()
            return "break"

        input_box.bind("<Control-Return>", send_shortcut)
        send_button = tk.Button(controls, text="发送", command=send, bg=COLORS["mint"], fg=COLORS["bg"], relief="flat", padx=18, pady=8, font=("Microsoft YaHei UI", 9, "bold"))
        send_button.pack(fill="x")
        clear_button = tk.Button(controls, text="清空会话", command=reset_chat, bg=COLORS["button"], fg=COLORS["text"], relief="flat", padx=14, pady=7)
        clear_button.pack(fill="x", pady=(7, 0))
        tk.Button(controls, text="关闭", command=window.destroy, bg=COLORS["button"], fg=COLORS["muted"], relief="flat", padx=14, pady=7).pack(fill="x", pady=(7, 0))
        input_box.focus_set()

    def add_online_instrument(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("联网查询并添加 · Marketor")
        window.transient(self.root)
        window.grab_set()
        window.resizable(False, False)
        window.configure(bg=COLORS["bg"])
        panel = self._panel(window)
        panel.pack(fill="both", expand=True, padx=18, pady=18)
        self._label(panel, "联网查询并添加", 17, weight="bold").grid(row=0, column=0, columnspan=2, sticky="w")
        self._label(panel, "同花顺 API Key 可选 · 查询成功后保存为本地 CSV", 9, COLORS["cyan"]).grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 14))

        type_labels = list(ONLINE_TYPE_LABELS.values())
        type_codes = {label: code for code, label in ONLINE_TYPE_LABELS.items()}
        type_var = tk.StringVar(value=ONLINE_TYPE_LABELS["cn_stock"])
        code_var = tk.StringVar(value="600519")
        symbol_var = tk.StringVar(value="stock_600519")
        name_var = tk.StringVar(value="")
        start_var = tk.StringVar(value="2005-01-01")

        def label_at(row: int, text: str) -> None:
            self._label(panel, text, 9, COLORS["muted"], "bold").grid(row=row, column=0, sticky="w", padx=(0, 16), pady=6)

        def entry_at(row: int, variable: tk.StringVar) -> tk.Entry:
            entry = tk.Entry(panel, textvariable=variable, width=36, bg=COLORS["panel_alt"], fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat", font=("Microsoft YaHei UI", 10))
            entry.grid(row=row, column=1, sticky="ew", pady=6, ipady=7)
            return entry

        label_at(2, "联网类型")
        type_box = ttk.Combobox(panel, textvariable=type_var, values=type_labels, state="readonly", width=33, style="Toolbar.TCombobox")
        type_box.grid(row=2, column=1, sticky="ew", pady=6)
        label_at(3, "行情代码")
        code_entry = entry_at(3, code_var)
        label_at(4, "本地唯一代码")
        entry_at(4, symbol_var)
        label_at(5, "显示名称（可留空）")
        entry_at(5, name_var)
        label_at(6, "历史起始日期")
        entry_at(6, start_var)
        hint_var = tk.StringVar()
        hint = self._label(panel, "", 8, COLORS["muted"], wraplength=430, justify="left", textvariable=hint_var)
        hint.grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 8))
        status_var = tk.StringVar(value="")
        status = self._label(panel, "", 8, COLORS["gold"], wraplength=430, justify="left", textvariable=status_var)
        status.grid(row=8, column=0, columnspan=2, sticky="w", pady=(0, 10))
        actions = tk.Frame(panel, bg=COLORS["panel"])
        actions.grid(row=9, column=0, columnspan=2, sticky="e")

        examples = {
            "cn_stock": ("600519", "stock_600519", "示例：600519、000001、510300；股票和场内 ETF 使用前复权价格。"),
            "cn_index": ("000300", "index_000300", "示例：000300、399006；指数保持原始点位，不做复权。"),
            "cn_fund": ("000001", "fund_000001", "示例：000001；使用开放式基金单位净值历史。"),
            "yahoo": ("AAPL", "global_aapl", "示例：AAPL、SPY、^GSPC、0700.HK；使用调整后价格。"),
        }

        def update_example(_event: Any = None) -> None:
            kind = type_codes[type_var.get()]
            code, symbol, message = examples[kind]
            code_var.set(code)
            symbol_var.set(symbol)
            hint_var.set(message)

        type_box.bind("<<ComboboxSelected>>", update_example)
        update_example()

        def submit() -> None:
            try:
                datetime.fromisoformat(start_var.get().strip())
                local_symbol = normalize_symbol(symbol_var.get())
            except ValueError as exc:
                messagebox.showerror("输入有误", f"请使用 YYYY-MM-DD 日期，并检查本地代码。\n{exc}", parent=window)
                return
            replace = False
            try:
                self.catalog.get(local_symbol)
            except KeyError:
                pass
            else:
                replace = messagebox.askyesno("标的已存在", f"本地代码 {local_symbol} 已存在，是否替换其行情？", parent=window)
                if not replace:
                    return
            submit_button.configure(state="disabled")
            status_var.set("正在连接行情源并下载历史数据…")
            online_type = type_codes[type_var.get()]
            provider_code = code_var.get()
            start_date = start_var.get().strip()
            display_name = name_var.get()

            def worker() -> None:
                try:
                    result = self.online_custom_manager.add(
                        online_type=online_type, provider_code=provider_code,
                        symbol=local_symbol, start_date=start_date,
                        name=display_name, replace=replace,
                    )
                    self.root.after(0, self._finish_online_add, window, result)
                except Exception as exc:
                    self.root.after(0, self._online_add_failed, submit_button, status_var, str(exc))

            threading.Thread(target=worker, daemon=True).start()

        tk.Button(actions, text="取消", command=window.destroy, bg=COLORS["button"], fg=COLORS["text"], relief="flat", padx=16, pady=7).pack(side="left", padx=(0, 8))
        submit_button = tk.Button(actions, text="查询并添加", command=submit, bg=COLORS["mint"], fg=COLORS["bg"], relief="flat", padx=18, pady=7, font=("Microsoft YaHei UI", 9, "bold"))
        submit_button.pack(side="left")
        panel.grid_columnconfigure(1, weight=1)
        code_entry.focus_set()

    def _finish_online_add(self, window: tk.Toplevel, result: OnlineImportResult) -> None:
        window.destroy()
        self._reload_catalog(result.instrument.symbol)
        self.provider_status = f"当前数据源：{result.provider} · 在线状态：正常 · 最新交易日：{result.last_date}"
        messagebox.showinfo(
            "联网添加完成",
            f"已添加：{result.instrument.name}\n数据源：{result.provider}\n"
            f"有效记录：{result.rows:,} 条\n日期范围：{result.first_date} 至 {result.last_date}",
            parent=self.root,
        )

    @staticmethod
    def _online_add_failed(button: tk.Button, status_var: tk.StringVar, message: str) -> None:
        button.configure(state="normal")
        status_var.set(f"查询失败：{message}")

    def refresh(self) -> None:
        self.refresh_button.configure(state="disabled")
        self.status_var.set("正在读取本地行情…")
        symbol = self.current_symbol
        days = PERIODS[self.period_var.get()]
        threading.Thread(target=self._load_data, args=(symbol, days), daemon=True).start()

    def update_online(self) -> None:
        instrument = self.catalog.get(self.current_symbol)
        if instrument.online_source:
            self.update_button.configure(state="disabled")
            self.refresh_button.configure(state="disabled")
            self.status_var.set("正在重新查询自定义标的完整历史…")
            threading.Thread(target=self._run_custom_online_update, args=(instrument.symbol,), daemon=True).start()
            return
        if not instrument.source_priority:
            messagebox.showinfo("仅本地数据", "该自定义标的目前使用本地 CSV，不执行在线更新。", parent=self.root)
            return
        self.update_button.configure(state="disabled")
        self.refresh_button.configure(state="disabled")
        self.status_var.set("正在检查在线增量行情…")
        source_mode = DATA_SOURCES[self.source_var.get()]
        threading.Thread(target=self._run_online_update, args=(self.current_symbol, source_mode), daemon=True).start()

    def _run_custom_online_update(self, symbol: str) -> None:
        try:
            result = self.online_custom_manager.refresh(symbol, catalog=self.catalog)
            self.root.after(0, self._finish_custom_online_update, result)
        except Exception as exc:
            self.root.after(0, self._custom_online_update_failed, str(exc))

    def _finish_custom_online_update(self, result: OnlineImportResult) -> None:
        self.catalog = InstrumentCatalog()
        self.provider_status = f"当前数据源：{result.provider} · 在线状态：正常 · 最新交易日：{result.last_date}"
        self.status_var.set(f"联网更新完成 · 共 {result.rows:,} 条记录")
        self.refresh()

    def _custom_online_update_failed(self, message: str) -> None:
        self.update_button.configure(state="normal")
        self.refresh_button.configure(state="normal")
        self.status_var.set("联网更新失败，继续使用原有本地数据")
        messagebox.showwarning(
            "联网更新未完成",
            f"联网查询失败，原有 CSV 未被覆盖。\n\n{message}",
            parent=self.root,
        )

    def open_comparison(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("今日相对便宜排名 · 市场航图")
        window.geometry("1220x520")
        window.minsize(900, 420)
        window.configure(bg=COLORS["bg"])
        header = tk.Frame(window, bg=COLORS["bg"], padx=20, pady=16)
        header.pack(fill="x")
        self._label(header, "今日相对便宜排名", 18, weight="bold").pack(side="left")
        info = tk.Frame(header, bg=COLORS["bg"])
        info.pack(side="right")
        status = self._label(info, "正在计算历史分位…", 9, COLORS["muted"])
        status.pack(anchor="e")
        self._label(info, "双击指数查看年线低位独立事件", 8, COLORS["cyan"]).pack(anchor="e", pady=(3, 0))
        columns = ("rank", "name", "bias250", "bias500", "rsi", "drawdown", "return1y", "volatility", "percentile", "buy", "sell", "state")
        tree = ttk.Treeview(window, columns=columns, show="headings")
        headings = ("排名", "指数", "250日乖离", "500日乖离", "RSI14", "一年回撤", "一年收益", "60日波动", "250乖离分位", "加仓分", "减仓分", "综合状态")
        widths = (50, 110, 85, 85, 65, 85, 85, 85, 95, 65, 65, 100)
        for column, heading, width in zip(columns, headings, widths):
            tree.heading(column, text=heading)
            tree.column(column, width=width, anchor="center", stretch=True)
        tree.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        tree.bind("<Double-1>", lambda _event: self._open_selected_events(tree))

        def load() -> None:
            try:
                rows = MarketComparisonService(self.catalog).snapshots()
                self.root.after(0, self._render_comparison, tree, status, rows)
            except Exception as exc:
                self.root.after(0, status.configure, {"text": f"计算失败：{exc}", "fg": COLORS["coral"]})

        threading.Thread(target=load, daemon=True).start()

    @staticmethod
    def _render_comparison(tree: ttk.Treeview, status: tk.Label, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            tree.insert("", "end", iid=row["symbol"], values=(
                row["rank"], row["name"], format_pct(row["bias250"]), format_pct(row["bias500"]),
                format_number(row["rsi14"], 1), format_pct(row["drawdown_1y"]), format_pct(row["return_1y"]),
                format_pct(row["volatility_60d"]), f"{row['bias250_percentile']:.1f}%" if row["bias250_percentile"] is not None else "—",
                row["buy_score"], row["sell_score"], row["buy_state"] if row["buy_score"] >= row["sell_score"] else row["sell_state"],
            ))
        status.configure(text=f"{rows[0]['date']} · 共 {len(rows)} 个指数", fg=COLORS["mint"])

    def _open_selected_events(self, tree: ttk.Treeview) -> None:
        selection = tree.selection()
        if selection:
            self.open_event_history(selection[0])

    def open_event_history(self, symbol: str) -> None:
        instrument = self.catalog.get(symbol)
        window = tk.Toplevel(self.root)
        window.title(f"{instrument.name} · 独立信号事件")
        window.geometry("1000x580")
        window.minsize(780, 420)
        window.configure(bg=COLORS["bg"])
        header = tk.Frame(window, bg=COLORS["bg"], padx=20, pady=16)
        header.pack(fill="x")
        self._label(header, f"{instrument.name} · 年线乖离 ≤ -10%", 17, weight="bold").pack(side="left")
        status = self._label(header, "正在寻找独立事件…", 9, COLORS["muted"])
        status.pack(side="right")
        summary = self._label(window, "触发后 60 个交易日内不重复计数", 9, COLORS["cyan"], padx=20, anchor="w")
        summary.pack(fill="x", pady=(0, 12))
        columns = ("date", "close", "bias", "rsi", "return1y", "return3y", "return5y")
        tree = ttk.Treeview(window, columns=columns, show="headings")
        headings = ("事件日期", "收盘点位", "250日乖离", "RSI14", "1年后收益", "3年后收益", "5年后收益")
        for column, heading in zip(columns, headings):
            tree.heading(column, text=heading)
            tree.column(column, anchor="center", width=120, stretch=True)
        tree.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        def load() -> None:
            try:
                result = EventBacktester(MarketService(symbol, catalog=self.catalog)).run()
                self.root.after(0, self._render_event_history, tree, status, summary, result)
            except Exception as exc:
                self.root.after(0, status.configure, {"text": f"计算失败：{exc}", "fg": COLORS["coral"]})

        threading.Thread(target=load, daemon=True).start()

    @staticmethod
    def _render_event_history(
        tree: ttk.Treeview,
        status: tk.Label,
        summary_label: tk.Label,
        result: dict[str, Any],
    ) -> None:
        for event in result["events"]:
            tree.insert("", "end", values=(
                event["date"], format_number(event["close"]), format_pct(event["metric"]),
                format_number(event["rsi14"], 1), format_pct(event.get("return_250d")),
                format_pct(event.get("return_750d")), format_pct(event.get("return_1250d")),
            ))
        stats = result["summary"]
        one_year = stats["return_250d"]
        summary_label.configure(text=(
            f"独立事件 {stats['event_count']} 次 · 1年有效样本 {one_year['samples']} 次 · "
            f"平均 {format_pct(one_year['mean'])} · 正收益率 {format_pct(one_year['positive_rate'])}"
        ))
        status.configure(text="事件模式 · 冷却 60 个交易日", fg=COLORS["mint"])

    def _run_online_update(self, symbol: str, source_mode: str) -> None:
        result = MarketDataUpdater(symbol, catalog=self.catalog, source_mode=source_mode).run(allow_fallback=True)
        self.root.after(0, self._finish_online_update, result)

    def _finish_online_update(self, result: UpdateResult) -> None:
        self.update_button.configure(state="normal")
        self.refresh_button.configure(state="normal")
        self.provider_status = (
            f"当前数据源：{result.data_source} · 在线状态："
            f"{'正常' if result.online_status == 'normal' else '仅本地' if result.online_status == 'local' else '更新失败'}"
            f" · 最新交易日：{result.latest.get('date', result.local_latest)}"
        )
        if not result.online_success:
            messagebox.showwarning(
                "在线更新未完成",
                f"在线更新失败，已继续使用本地 CSV。\n\n当前数据日期：{result.local_latest}",
                parent=self.root,
            )
        elif result.new_records:
            self.status_var.set(f"在线更新完成 · 新增 {result.new_records} 个交易日")
        else:
            self.status_var.set("在线数据已是最新")
        self.refresh()

    def _load_data(self, symbol: str, days: int) -> None:
        try:
            service = MarketService(symbol, catalog=self.catalog)
            payload = {
                "metadata": service.metadata(),
                "latest": service.latest(),
                "signal": service.signal(),
                "indicators": service.indicators(days),
                "returns": service.holding_returns((30, 365, 730, 1095, 1825)),
            }
            self.root.after(0, self._render, payload)
        except Exception as exc:  # UI boundary: display a useful error instead of crashing.
            self.root.after(0, self._show_error, str(exc))

    def _render(self, payload: dict[str, Any]) -> None:
        latest, metadata, signal = payload["latest"], payload["metadata"], payload["signal"]
        self.price_card["value"].configure(text=format_number(latest["close"]))
        self.price_card["detail"].configure(text=f"{metadata['name']} · {latest['date']} · 近20日 {format_pct(latest.get('ret_20d'))}")
        self.bias_card["value"].configure(text=format_pct(latest.get("bias250")), fg=direction_color(latest.get("bias250")))
        self.bias_card["detail"].configure(text=f"MA500 {format_pct(latest.get('bias500'))}  ·  MA1250 {format_pct(latest.get('bias1250'))}")
        self.rsi_card["value"].configure(text=format_number(latest.get("rsi14"), 1))
        self.rsi_card["detail"].configure(text="<30 超卖  ·  >70 过热")
        self.drawdown_card["value"].configure(text=format_pct(latest.get("drawdown_250d")), fg=direction_color(latest.get("drawdown_250d")))
        self.drawdown_card["detail"].configure(text=f"数据 {metadata['first_date']} — {metadata['last_date']}")
        self.chart.set_rows(payload["indicators"])
        self._render_signal(self.buy_widgets, signal["accumulation"], "×")
        self._render_signal(self.sell_widgets, signal["reduction"], "%")
        self.returns_table.delete(*self.returns_table.get_children())
        period_labels = {30: "1月", 365: "1年", 730: "2年", 1095: "3年", 1825: "5年"}
        for row in payload["returns"]:
            self.returns_table.insert("", "end", values=(period_labels[row["days"]], f"{row['samples']:,}", format_pct(row.get("mean")), format_pct(row.get("median")), format_pct(row.get("positive_rate")), format_pct(row.get("min")), format_pct(row.get("max"))))
        self.status_var.set(f"{self.provider_status} · {metadata['rows']:,} 条记录")
        self.refresh_button.configure(state="normal")
        self.update_button.configure(state="normal")

    @staticmethod
    def _render_signal(widgets: dict[str, tk.Label], signal: dict[str, Any], suffix: str) -> None:
        widgets["level"].configure(text=f"{signal['level']}信号")
        score = float(signal["score"])
        widgets["score"].configure(text=f"{score:.1f}{suffix}" if suffix == "×" else f"{score:.0f}{suffix}")
        widgets["action"].configure(text=signal["suggested_action"])
        widgets["reasons"].configure(text="\n".join(f"• {reason}" for reason in signal["reasons"]))

    def _show_error(self, message: str) -> None:
        self.status_var.set("数据读取失败")
        self.refresh_button.configure(state="normal")
        self.update_button.configure(state="normal")
        messagebox.showerror("市场航图", f"无法读取行情数据：\n{message}", parent=self.root)


def main() -> None:
    enable_high_dpi_awareness()
    root = tk.Tk()
    MarketDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

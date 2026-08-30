from __future__ import annotations

import json
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from .catalog import InstrumentCatalog
from .comparison import MarketComparisonService
from .events import EventBacktester
from .service import MarketService
from .updater import MarketDataUpdater, UpdateResult


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
    "自动": "auto", "BaoStock": "baostock", "腾讯": "tencent",
    "东方财富": "eastmoney", "Tushare": "tushare", "仅本地": "local",
}


def _theme_settings_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MarketCompass"
    return base / "settings.json"


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
        self.instruments = self.catalog.list()
        self.current_symbol = self.instruments[0].symbol
        self.provider_status = "当前数据源：本地 CSV · 在线状态：待检查"
        self._configure_window()
        self._configure_styles()
        self._build_ui()
        self.refresh()

    def _configure_window(self) -> None:
        self.root.title("市场航图 · 本地行情分析")
        self.root.geometry("1280x850")
        self.root.minsize(980, 700)
        self.root.configure(bg=COLORS["bg"])

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=COLORS["panel_alt"], background=COLORS["panel_alt"], foreground=COLORS["text"], arrowcolor=COLORS["mint"], bordercolor=COLORS["line"], lightcolor=COLORS["line"], darkcolor=COLORS["line"], padding=(9, 6), font=("Microsoft YaHei UI", 9))
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["panel_alt"])], foreground=[("readonly", COLORS["text"])])
        style.configure("Treeview", background=COLORS["panel"], fieldbackground=COLORS["panel"], foreground=COLORS["text"], rowheight=31, borderwidth=0, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", background=COLORS["panel_alt"], foreground=COLORS["muted"], relief="flat", padding=(8, 9), font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Treeview", background=[("selected", COLORS["selected"])], foreground=[("selected", COLORS["text"])])

    def _label(self, parent: tk.Misc, text: str, size: int = 10, color: str | None = None, weight: str = "normal", **kwargs: Any) -> tk.Label:
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color or COLORS["text"], font=("Microsoft YaHei UI", size, weight), **kwargs)

    def _panel(self, parent: tk.Misc) -> tk.Frame:
        return tk.Frame(parent, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1, padx=20, pady=17)

    def _build_ui(self) -> None:
        outer = tk.Frame(self.root, bg=COLORS["bg"], padx=24, pady=20)
        outer.pack(fill="both", expand=True)

        accent_line = tk.Frame(outer, bg=COLORS["mint"], height=3)
        accent_line.pack(fill="x", pady=(0, 14))
        header = tk.Frame(outer, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1, padx=20, pady=15)
        header.pack(fill="x", pady=(0, 16))
        title_block = tk.Frame(header, bg=COLORS["panel"])
        title_block.pack(side="left")
        eyebrow = tk.Frame(title_block, bg=COLORS["panel"])
        eyebrow.pack(anchor="w")
        self._label(eyebrow, "MARKET COMPASS", 8, COLORS["mint"], "bold").pack(side="left")
        self._label(eyebrow, "  LOCAL · v0.9", 8, COLORS["muted"], "bold").pack(side="left")
        self._label(title_block, "市场航图", 26, weight="bold").pack(anchor="w", pady=(3, 0))
        self._label(title_block, "多指数长期位置 · 动量 · 独立事件研究", 9, COLORS["muted"]).pack(anchor="w", pady=(3, 0))

        actions = tk.Frame(header, bg=COLORS["panel"])
        actions.pack(side="right", anchor="center")
        selectors = tk.Frame(actions, bg=COLORS["panel"])
        selectors.pack(anchor="e", pady=(0, 8))
        names = [f"{item.name} · {item.symbol}" for item in self.instruments]
        self.symbol_var = tk.StringVar(value=names[0])
        symbol_box = ttk.Combobox(selectors, textvariable=self.symbol_var, values=names, state="readonly", width=21)
        symbol_box.pack(side="left", ipady=5, padx=(0, 8))
        symbol_box.bind("<<ComboboxSelected>>", self._on_symbol_change)
        self.period_var = tk.StringVar(value="1年")
        period_box = ttk.Combobox(selectors, textvariable=self.period_var, values=list(PERIODS), state="readonly", width=6)
        period_box.pack(side="left", ipady=5, padx=(0, 8))
        period_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        self.source_var = tk.StringVar(value="自动")
        source_box = ttk.Combobox(selectors, textvariable=self.source_var, values=list(DATA_SOURCES), state="readonly", width=8)
        source_box.pack(side="left", ipady=5, padx=(0, 8))
        self.theme_var = tk.StringVar(value=self.theme_name)
        theme_box = ttk.Combobox(selectors, textvariable=self.theme_var, values=list(THEMES), state="readonly", width=9)
        theme_box.pack(side="left", ipady=5)
        theme_box.bind("<<ComboboxSelected>>", self._on_theme_change)
        buttons = tk.Frame(actions, bg=COLORS["panel"])
        buttons.pack(anchor="e")
        self.update_button = tk.Button(buttons, text="↻  在线更新", command=self.update_online, bg=COLORS["button"], fg=COLORS["mint"], activebackground=COLORS["button_hover"], activeforeground=COLORS["text"], relief="flat", padx=16, pady=7, cursor="hand2", font=("Microsoft YaHei UI", 9, "bold"))
        self.update_button.pack(side="left", padx=(0, 8))
        rank_button = tk.Button(buttons, text="◇  指数排名", command=self.open_comparison, bg=COLORS["rank_button"], fg=COLORS["cyan"], activebackground=COLORS["rank_hover"], activeforeground=COLORS["text"], relief="flat", padx=16, pady=7, cursor="hand2", font=("Microsoft YaHei UI", 9, "bold"))
        rank_button.pack(side="left", padx=(0, 8))
        self.refresh_button = tk.Button(buttons, text="刷新本地", command=self.refresh, bg=COLORS["mint"], fg=COLORS["bg"], activebackground=COLORS["cyan"], activeforeground=COLORS["bg"], relief="flat", padx=18, pady=7, cursor="hand2", font=("Microsoft YaHei UI", 9, "bold"))
        self.refresh_button.pack(side="left")

        self.status_var = tk.StringVar(value="正在读取本地行情…")
        self._label(outer, "", 9, COLORS["cyan"], textvariable=self.status_var).pack(fill="x", pady=(0, 9))

        cards = tk.Frame(outer, bg=COLORS["bg"])
        cards.pack(fill="x", pady=(0, 12))
        for index in range(4):
            cards.grid_columnconfigure(index, weight=1, uniform="metric")
        self.price_card = self._metric_card(cards, 0, "最新收盘", "price", "cyan")
        self.bias_card = self._metric_card(cards, 1, "MA250 乖离", "bias", "mint")
        self.rsi_card = self._metric_card(cards, 2, "RSI14", "rsi", "gold")
        self.drawdown_card = self._metric_card(cards, 3, "250日高点回撤", "drawdown", "coral")

        center = tk.Frame(outer, bg=COLORS["bg"])
        center.pack(fill="both", expand=True)
        center.grid_columnconfigure(0, weight=7)
        center.grid_columnconfigure(1, weight=3)
        center.grid_rowconfigure(0, weight=1)
        chart_panel = self._panel(center)
        chart_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
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

        signals = tk.Frame(center, bg=COLORS["bg"])
        signals.grid(row=0, column=1, sticky="nsew")
        signals.grid_rowconfigure(0, weight=1, uniform="signal")
        signals.grid_rowconfigure(1, weight=1, uniform="signal")
        signals.grid_columnconfigure(0, weight=1)
        self.buy_widgets = self._signal_card(signals, 0, "加仓辅助", COLORS["mint"])
        self.sell_widgets = self._signal_card(signals, 1, "减仓辅助", COLORS["coral"])

        returns_panel = self._panel(outer)
        returns_panel.pack(fill="x", pady=(12, 0))
        returns_head = tk.Frame(returns_panel, bg=COLORS["panel"])
        returns_head.pack(fill="x", pady=(0, 8))
        self._label(returns_head, "历史持有收益", 12, weight="bold").pack(side="left")
        self._label(returns_head, "自然日口径 · 收益基于最接近的后续交易日", 8, COLORS["muted"]).pack(side="right")
        columns = ("period", "samples", "mean", "median", "positive", "min", "max")
        self.returns_table = ttk.Treeview(returns_panel, columns=columns, show="headings", height=5)
        headings = ("持有期", "样本数", "平均收益", "中位数", "正收益率", "最差", "最好")
        for column, heading in zip(columns, headings):
            self.returns_table.heading(column, text=heading)
            self.returns_table.column(column, anchor="center", width=105, stretch=True)
        self.returns_table.pack(fill="x")

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

    def _signal_card(self, parent: tk.Misc, row: int, title: str, accent: str) -> dict[str, tk.Label]:
        panel = self._panel(parent)
        panel.grid(row=row, column=0, sticky="nsew", pady=(0, 6) if row == 0 else (6, 0))
        stripe = tk.Frame(panel, bg=accent, width=3)
        stripe.pack(side="left", fill="y", padx=(0, 13))
        content = tk.Frame(panel, bg=COLORS["panel"])
        content.pack(side="left", fill="both", expand=True)
        top = tk.Frame(content, bg=COLORS["panel"]); top.pack(fill="x")
        self._label(top, title, 11, weight="bold").pack(side="left")
        level = self._label(top, "—", 8, accent, "bold"); level.pack(side="right")
        score = self._label(content, "—", 24, accent, "bold"); score.pack(anchor="w", pady=(10, 0))
        action = self._label(content, "—", 8, COLORS["muted"], wraplength=280, justify="left"); action.pack(anchor="w")
        reasons = self._label(content, "—", 8, COLORS["soft_text"], wraplength=280, justify="left"); reasons.pack(anchor="w", pady=(10, 0))
        return {"level": level, "score": score, "action": action, "reasons": reasons}

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
        index = self.symbol_var.get().rpartition(" · ")[2]
        self.current_symbol = index
        self.refresh()

    def refresh(self) -> None:
        self.refresh_button.configure(state="disabled")
        self.status_var.set("正在读取本地行情…")
        symbol = self.current_symbol
        days = PERIODS[self.period_var.get()]
        threading.Thread(target=self._load_data, args=(symbol, days), daemon=True).start()

    def update_online(self) -> None:
        self.update_button.configure(state="disabled")
        self.refresh_button.configure(state="disabled")
        self.status_var.set("正在检查在线增量行情…")
        source_mode = DATA_SOURCES[self.source_var.get()]
        threading.Thread(target=self._run_online_update, args=(self.current_symbol, source_mode), daemon=True).start()

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
    root = tk.Tk()
    MarketDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

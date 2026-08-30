from csi300_service.desktop import (
    PERIODS,
    THEMES,
    LineChart,
    calculate_window_size,
    combobox_popup_options,
    direction_color,
    format_number,
    format_pct,
    load_theme,
    save_theme,
)


def test_desktop_formatters():
    assert format_number(4609.18) == "4,609.18"
    assert format_pct(-0.0123) == "-1.23%"
    assert format_pct(0.0123) == "+1.23%"
    assert format_pct(None) == "—"


def test_desktop_chart_series_shows_ma60():
    keys = [key for key, *_ in LineChart.SERIES]
    assert keys == ["close", "ma60", "ma250", "ma500", "ma1250"]


def test_desktop_periods_and_direction():
    assert PERIODS["1年"] == 250
    assert direction_color(1) != direction_color(-1)


def test_themes_have_a_consistent_palette():
    assert len(THEMES) >= 4
    expected = set(next(iter(THEMES.values())))
    assert all(set(palette) == expected for palette in THEMES.values())


def test_theme_preference_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_theme("深海蓝")
    assert load_theme() == "深海蓝"


def test_high_dpi_window_size_stays_inside_screen():
    assert calculate_window_size(3840, 2160, 2.0) == (2560, 1700)
    width, height = calculate_window_size(1920, 1080, 1.5)
    assert width <= 1920
    assert height <= 1080


def test_combobox_popup_uses_theme_and_readable_font():
    palette = THEMES["深海蓝"]
    options = combobox_popup_options(palette)
    assert options["-background"] == palette["panel"]
    assert options["-selectbackground"] == palette["selected"]
    assert "11" in str(options["-font"])
    assert options["-activestyle"] == "none"

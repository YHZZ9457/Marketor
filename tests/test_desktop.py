from csi300_service.desktop import PERIODS, THEMES, LineChart, direction_color, format_number, format_pct, load_theme, save_theme


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

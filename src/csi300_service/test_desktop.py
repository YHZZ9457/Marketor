from csi300_service.desktop import PERIODS, direction_color, format_number, format_pct


def test_desktop_formatters():
    assert format_number(4609.18) == "4,609.18"
    assert format_pct(-0.0123) == "-1.23%"
    assert format_pct(0.0123) == "+1.23%"
    assert format_pct(None) == "—"


def test_desktop_periods_and_direction():
    assert PERIODS["1年"] == 250
    assert direction_color(1) != direction_color(-1)

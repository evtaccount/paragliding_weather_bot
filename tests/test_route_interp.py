"""Интерполяция почасовых рядов на дробный час прибытия."""
import pytest

import route


def const(v):
    return [v] * 24


def test_linear_between_hours():
    s = const(0.0)
    s[12], s[13] = 10.0, 20.0
    assert route.interp(s, 12.0) == pytest.approx(10.0)
    assert route.interp(s, 12.5) == pytest.approx(15.0)
    assert route.interp(s, 13.0) == pytest.approx(20.0)


def test_none_in_series_gives_none():
    s = const(1.0)
    s[12] = None
    assert route.interp(s, 12.4) is None


def test_out_of_range_gives_none():
    assert route.interp(const(1.0), 24.5) is None
    assert route.interp(const(1.0), -1.0) is None


def test_wind_direction_across_north_does_not_flip():
    speeds, dirs = const(10.0), const(0.0)
    dirs[12], dirs[13] = 350.0, 10.0
    speed, deg = route.interp_wind(speeds, dirs, 12.5)
    assert deg == pytest.approx(0.0, abs=0.5) or deg == pytest.approx(360.0, abs=0.5)
    assert speed == pytest.approx(9.85, abs=0.1)


def test_wind_direction_plain_case():
    speeds, dirs = const(10.0), const(0.0)
    dirs[12], dirs[13] = 180.0, 200.0
    _, deg = route.interp_wind(speeds, dirs, 12.5)
    assert deg == pytest.approx(190.0, abs=0.5)


def test_wind_none_without_data():
    assert route.interp_wind(None, const(0.0), 12.5) == (None, None)


def test_precipitation_takes_worst_of_two_hours():
    s = const(0.0)
    s[12], s[13] = 0.0, 2.0
    assert route.worst_of_hours(s, 12.5) == pytest.approx(2.0)
    assert route.worst_of_hours(s, 12.0) == pytest.approx(2.0)


def test_worst_of_hours_ignores_none():
    s = const(0.0)
    s[12], s[13] = None, 2.0
    assert route.worst_of_hours(s, 12.5) == pytest.approx(2.0)

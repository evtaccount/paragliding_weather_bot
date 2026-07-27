"""Термическое окно в точке маршрута — пересечение солнечной рамки и порогов."""
import pytest

import route

DATE, SR, SS = "2026-07-25", "2026-07-25T05:00", "2026-07-25T20:00"


def series(value, hours=None, other=0.0):
    """24 часа `other`, а в перечисленных часах — `value`."""
    out = [other] * 24
    for h in (hours or range(24)):
        out[h] = value
    return out


def test_thresholds_narrow_the_solar_frame():
    blh = series(1500.0, range(11, 16))       # конвекция работает только 11–15
    rad = series(700.0, range(11, 16))
    w = route.thermal_window(DATE, 42.0, SR, SS, blh, rad)
    assert w == {"start_hour": 11, "end_hour": 15}


def test_solar_frame_narrows_the_thresholds():
    blh, rad = series(1500.0), series(700.0)  # пороги открыты все сутки
    w = route.thermal_window(DATE, 42.0, SR, SS, blh, rad)
    assert w["start_hour"] >= 7                # солнце не даёт открыть окно ночью
    assert w["end_hour"] <= 19


def test_no_working_hours_gives_none():
    blh, rad = series(100.0), series(10.0)
    assert route.thermal_window(DATE, 42.0, SR, SS, blh, rad) is None


def test_missing_series_gives_none():
    assert route.thermal_window(DATE, 42.0, SR, SS, None, None) is None


def test_time_margin_measured_to_end_of_last_working_hour():
    w = {"start_hour": 11, "end_hour": 15}
    assert route.time_margin_min(w, 14.0) == pytest.approx(120.0)   # до 16:00
    assert route.time_margin_min(w, 16.5) == pytest.approx(-30.0)


def test_time_margin_none_without_window():
    assert route.time_margin_min(None, 14.0) is None
    assert route.time_margin_min({"start_hour": 11, "end_hour": 15}, None) is None

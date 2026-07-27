"""Время прибытия: путевая скорость с крабингом и марш вперёд по сегментам."""
import pytest

import route

PTS = [route.Point(42.0, 44.0), route.Point(42.0 + 80.0 / 111.195, 44.0)]


def samples():
    s, _ = route.resample(PTS, step_km=20.0)
    return s


def test_ground_speed_pure_tailwind():
    gs, limited = route.ground_speed(25.0, 10.0, 0.0)
    assert gs == pytest.approx(35.0)
    assert limited is False


def test_ground_speed_crab_costs_speed():
    gs, _ = route.ground_speed(25.0, 0.0, 15.0)
    assert gs == pytest.approx(20.0, abs=0.1)   # 25·cos(asin(0.6)) = 20


def test_ground_speed_floor():
    gs, _ = route.ground_speed(25.0, -30.0, 0.0)
    assert gs == pytest.approx(route.MIN_GROUND_SPEED_KMH)


def test_crab_limited_when_cross_exceeds_airspeed():
    gs, limited = route.ground_speed(25.0, 0.0, 26.0)
    assert limited is True
    assert gs == pytest.approx(route.MIN_GROUND_SPEED_KMH)


def test_fixed_eta_is_plain_division():
    s = samples()
    route.fixed_eta(s, 25.0, 11.5)
    assert s[0].eta_fixed_h == pytest.approx(11.5)
    assert s[-1].eta_fixed_h == pytest.approx(11.5 + 80.0 / 25.0, abs=0.01)


def test_headwind_arrival_is_later_than_fixed():
    s = samples()
    route.fixed_eta(s, 25.0, 11.5)
    route.march(s, 25.0, lambda i, hour: (-10.0, 0.0), 11.5)
    assert s[-1].eta_h > s[-1].eta_fixed_h
    assert s[-1].eta_h == pytest.approx(11.5 + 80.0 / 15.0, abs=0.01)


def test_tailwind_arrival_is_earlier_than_fixed():
    s = samples()
    route.fixed_eta(s, 25.0, 11.5)
    route.march(s, 25.0, lambda i, hour: (10.0, 0.0), 11.5)
    assert s[-1].eta_h < s[-1].eta_fixed_h


def test_wind_is_sampled_at_the_time_already_computed():
    seen = []

    def wind(i, hour):
        seen.append((i, round(hour, 3)))
        return (0.0, 0.0)

    s = samples()
    route.march(s, 25.0, wind, 11.5)
    assert seen[0] == (0, 11.5)
    # второй сегмент опрашивается уже на времени прибытия в первую точку
    assert seen[1][1] == pytest.approx(11.5 + 20.0 / 25.0, abs=0.01)


def test_crab_limit_is_recorded_on_the_sample():
    s = samples()
    route.march(s, 25.0, lambda i, hour: (0.0, 30.0), 11.5)
    assert any(x.crab_limited for x in s)

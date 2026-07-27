"""Разворот маршрута: тот же набор точек, обратный порядок и пеленги."""
import pytest

import route

PTS = [route.Point(42.0, 44.0, "старт"),
       route.Point(42.0 + 40.0 / 111.195, 44.0, "финиш")]


def forward():
    s, _ = route.resample(PTS, step_km=10.0)
    return s


def test_same_number_of_points():
    assert len(route.reverse_samples(forward())) == len(forward())


def test_kilometres_count_from_the_new_start():
    rev = route.reverse_samples(forward())
    assert rev[0].km == pytest.approx(0.0)
    assert rev[-1].km == pytest.approx(forward()[-1].km)


def test_coordinates_are_the_same_points_in_reverse_order():
    fwd, rev = forward(), route.reverse_samples(forward())
    assert [(p.lat, p.lon) for p in rev] == [(p.lat, p.lon) for p in reversed(fwd)]


def test_bearings_are_opposite():
    fwd, rev = forward(), route.reverse_samples(forward())
    diff = abs(rev[0].track_bearing_deg - fwd[-1].track_bearing_deg)
    assert min(diff, 360 - diff) == pytest.approx(180.0, abs=1.0)


def test_roles_are_reassigned():
    rev = route.reverse_samples(forward())
    assert rev[0].role == "takeoff"
    assert rev[-1].role == "goal"
    assert {s.role for s in rev[1:-1]} == {"enroute"}


def test_leg_lengths_still_sum_to_total():
    rev = route.reverse_samples(forward())
    assert sum(s.leg_length_km for s in rev) == pytest.approx(rev[-1].km, rel=1e-6)


def test_original_samples_are_not_mutated():
    fwd = forward()
    before = [(s.km, s.role, s.track_bearing_deg) for s in fwd]
    route.reverse_samples(fwd)
    assert [(s.km, s.role, s.track_bearing_deg) for s in fwd] == before

"""Геометрия маршрута: расстояние, пеленг, ресэмплинг."""
import pytest

import route

A = route.Point(42.4776, 44.4787, "старт")
B = route.Point(42.2104, 44.6890, "финиш")


def test_haversine_distance_and_bearing():
    d, brg = route.haversine(A, B)
    assert d / 1000.0 == pytest.approx(35.0, abs=1.5)
    assert brg == pytest.approx(150.0, abs=3.0)


def test_bearing_cardinal_directions():
    o = route.Point(0.0, 0.0)
    assert route.haversine(o, route.Point(1.0, 0.0))[1] == pytest.approx(0.0, abs=0.1)
    assert route.haversine(o, route.Point(0.0, 1.0))[1] == pytest.approx(90.0, abs=0.1)
    assert route.haversine(o, route.Point(-1.0, 0.0))[1] == pytest.approx(180.0, abs=0.1)
    assert route.haversine(o, route.Point(0.0, -1.0))[1] == pytest.approx(270.0, abs=0.1)


def test_bearing_across_antimeridian():
    d, brg = route.haversine(route.Point(0.0, 179.9), route.Point(0.0, -179.9))
    assert d / 1000.0 == pytest.approx(22.2, abs=1.0)
    assert brg == pytest.approx(90.0, abs=0.5)


def _straight_80km():
    """Две точки, разнесённые ровно на ~80 км по меридиану."""
    return [route.Point(42.0, 44.0, "A"), route.Point(42.0 + 80.0 / 111.195, 44.0, "B")]


def test_two_points_over_80km_give_nine_samples():
    samples, step = route.resample(_straight_80km(), step_km=10.0)
    assert len(samples) == 9
    assert step == pytest.approx(10.0)
    assert [round(s.km) for s in samples] == [0, 10, 20, 30, 40, 50, 60, 70, 80]


def test_turnpoints_are_kept_and_flagged():
    samples, _ = route.resample(_straight_80km(), step_km=10.0)
    assert samples[0].is_turnpoint is True
    assert samples[-1].is_turnpoint is True
    assert sum(s.is_turnpoint for s in samples) == 2
    assert samples[0].name == "A" and samples[-1].name == "B"


def test_roles_assigned():
    samples, _ = route.resample(_straight_80km(), step_km=10.0)
    assert samples[0].role == "takeoff"
    assert samples[-1].role == "goal"
    assert {s.role for s in samples[1:-1]} == {"enroute"}


def test_leg_lengths_sum_to_total():
    samples, _ = route.resample(_straight_80km(), step_km=10.0)
    assert sum(s.leg_length_km for s in samples) == pytest.approx(samples[-1].km, rel=1e-6)


def test_long_track_capped_at_max_samples():
    """Поворотных точек ровно столько же, сколько мест: промежуточных не добавляем,
    а наружу отдаём фактическое среднее расстояние между сэмплами."""
    pts = [route.Point(42.0 + i * 0.05, 44.0) for i in range(50)]
    samples, step = route.resample(pts, step_km=10.0, max_samples=50)
    assert len(samples) <= 50
    assert step == pytest.approx(samples[-1].km / (len(samples) - 1), rel=1e-3)


def test_turnpoints_alone_may_fill_the_cap():
    pts = [route.Point(42.0 + i * 0.5, 44.0) for i in range(50)]
    samples, step = route.resample(pts, step_km=10.0, max_samples=50)
    assert len(samples) == 50
    assert all(s.is_turnpoint for s in samples)
    assert step > 10.0     # шаг вырос: поворотные разнесены дальше номинального


def test_track_bearing_of_last_sample_comes_from_previous():
    samples, _ = route.resample(_straight_80km(), step_km=10.0)
    assert samples[-1].track_bearing_deg == pytest.approx(samples[-2].track_bearing_deg, abs=0.5)

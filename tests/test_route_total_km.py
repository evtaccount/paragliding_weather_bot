"""Длина ломаной по точкам."""
import pytest

import route


def test_total_km_sums_the_legs():
    pts = [route.Point(42.0, 44.0), route.Point(42.0 + 40.0 / 111.195, 44.0)]
    assert route.total_km(pts) == pytest.approx(40.0, abs=0.1)


def test_total_km_of_a_single_point_is_zero():
    assert route.total_km([route.Point(42.0, 44.0)]) == 0.0


def test_total_km_of_nothing_is_zero():
    assert route.total_km([]) == 0.0

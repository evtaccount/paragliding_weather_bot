"""Шкалы маршрутных параметров."""
import pytest

import criteria as c


@pytest.mark.parametrize("value,grade", [
    (14, "ideal"), (8, "ideal"), (19.9, "ideal"),
    (4, "excellent"), (0, "excellent"), (24, "excellent"),
    (-4, "fair"), (30, "fair"),
    (-10, "marginal"),
    (-20, "no_fly"),
    (-30, "danger"),
])
def test_wind_along_scale(value, grade):
    assert c.grade_of("wind_along", value) == grade


def test_wind_along_is_asymmetric():
    """Попутный +14 — подарок, встречный −14 растягивает маршрут."""
    assert c.grade_of("wind_along", 14) == "ideal"
    assert c.grade_of("wind_along", -14) == "marginal"


@pytest.mark.parametrize("value,grade", [
    (5, "ideal"), (12, "excellent"), (20, "fair"),
    (30, "marginal"), (40, "no_fly"), (50, "danger"),
])
def test_wind_cross_scale(value, grade):
    assert c.grade_of("wind_cross", value) == grade


@pytest.mark.parametrize("value,grade", [
    (1500, "ideal"), (800, "excellent"), (400, "fair"),
    (200, "marginal"), (100, "no_fly"), (-50, "danger"),
])
def test_working_band_scale(value, grade):
    assert c.grade_of("working_band", value) == grade


@pytest.mark.parametrize("value,grade", [
    (200, "ideal"), (150, "excellent"), (90, "fair"),
    (30, "marginal"), (10, "no_fly"), (-15, "danger"),
])
def test_time_margin_scale(value, grade):
    assert c.grade_of("time_margin", value) == grade


def test_wind_working_reuses_the_aloft_scale():
    """Ветер на рабочей высоте — та же физика, что на 850 гПа: шкала берётся
    ссылкой, а не копией чисел."""
    assert c.PARAMS["wind_working"].bands is c.PARAMS["wind_850"].bands


def test_route_group_weights_sum_to_one():
    assert abs(sum(g.weight for g in c.ROUTE_GROUPS.values()) - 1.0) < 1e-9


def test_thresholds_moved_out_of_route_module():
    import route
    assert route.MIN_GROUND_SPEED_KMH is c.MIN_GROUND_SPEED_KMH
    assert route.MIN_WORKING_ALT_AGL is c.MIN_WORKING_ALT_AGL

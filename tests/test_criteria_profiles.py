"""Профили критериев: предохранитель поведения и разделение по ролям точки."""
import pytest

import criteria as c
from fixtures import ideal_hour

# Эталон снят с реализации ДО рефакторинга. Если хоть одно число здесь поедет,
# значит профиль «старт» перестал быть сегодняшним поведением, а это ломает
# /today, обзоры и /scan молча.
GOLDEN = {
    "ideal":     ({}, 100.0, "ideal", None, 1.0, 0),
    "windy":     ({"wind_10m": 8.0, "wind_925": 9.5}, 69, "fair", "wind_10m", 1.0, 0),
    "gusty":     ({"gust_factor": 1.5, "gust_delta": 3.8}, 69, "fair", "gust_delta", 1.0, 0),
    "offslope":  ({"dir_offset": 50.0}, 54, "marginal", "dir_offset", 1.0, 0),
    "stormy":    ({"cape": 1200.0, "lifted_index": -3.0}, 69, "fair", "lifted_index", 1.0, 0),
    "thin_data": ({"w_star": None, "bl_depth": None, "thermal_index": None,
                   "visibility": None, "shear_100m": None, "cape": None},
                  100.0, "ideal", None, 0.7, 4),
}


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_default_profile_reproduces_pre_refactor_behaviour(name):
    over, score, cat, lim, conf, unchecked = GOLDEN[name]
    a = c.score_hour(ideal_hour(**over), 13)
    assert a.score == score
    assert a.category == cat
    assert a.limiting == lim
    assert a.confidence == conf
    assert len(a.unchecked_vetoes) == unchecked


def test_explicit_takeoff_profile_equals_the_default():
    raw = ideal_hour(wind_10m=8.0)
    assert c.score_hour(raw, 13).score == c.score_hour(raw, 13, profile=c.TAKEOFF).score


def test_takeoff_profile_keeps_every_launch_veto():
    """Утверждения намеренно сформулированы так, чтобы пережить добавление
    маршрутных параметров и вето в задачах 2 и 4."""
    launch_only = {"lee_side", "base_below_route", "wind_launch", "gust_factor",
                   "gust_delta", "shear"}
    assert c.TAKEOFF.groups == c.GROUPS
    assert launch_only <= set(c.TAKEOFF.vetoes)
    assert "dir_offset" in c.TAKEOFF.params


def test_group_params_filters_by_profile():
    assert set(c.TAKEOFF.group_params("wind")) == {"wind_10m", "wind_925", "wind_850"}

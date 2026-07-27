"""Разделение критериев по ролям точки: старт, маршрут, финиш."""
import criteria as c
from fixtures import ideal_hour


def route_raw(**over):
    """Минимальный набор входов для маршрутной точки — всё идеально."""
    raw = {"wind_along": 12.0, "wind_cross": 5.0, "working_band": 1500.0,
           "time_margin": 200.0, "wind_working": 4.0,
           "w_star": 2.5, "bl_depth": 1500.0, "thermal_index": -4.0,
           "cape": 200.0, "lifted_index": 3.0, "cloud_low": 20.0,
           "precip_prob": 0.0, "visibility": 30000.0, "window_hours": 6.0,
           "precip_mm": 0.0, "cin": 100.0, "wind_at_base": 4.0,
           "ground_speed": 30.0, "dir_misalign": 10.0}
    raw.update(over)
    return raw


def test_all_three_profiles_are_registered():
    assert set(c.PROFILES) == {"takeoff", "enroute", "goal"}


def test_an_ideal_route_point_scores_a_hundred():
    assert c.score_hour(route_raw(), 13, profile=c.ENROUTE).score == 100.0


def test_slope_direction_does_not_affect_an_enroute_point():
    """В воздухе склона нет — отклонение ветра от него не должно значить ничего."""
    good = c.score_hour(route_raw(dir_offset=5.0), 13, profile=c.ENROUTE)
    bad = c.score_hour(route_raw(dir_offset=80.0), 13, profile=c.ENROUTE)
    assert good.score == bad.score


def test_ground_wind_does_not_affect_an_enroute_point():
    calm = c.score_hour(route_raw(wind_10m=2.0), 13, profile=c.ENROUTE)
    blown = c.score_hour(route_raw(wind_10m=9.0), 13, profile=c.ENROUTE)
    assert calm.score == blown.score


def test_ground_wind_still_matters_at_the_goal():
    calm = c.score_hour(ideal_hour(wind_10m=2.0), 13, profile=c.GOAL)
    blown = c.score_hour(ideal_hour(wind_10m=9.0), 13, profile=c.GOAL)
    assert blown.score < calm.score


def test_headwind_along_the_track_drags_the_enroute_score_down():
    tail = c.score_hour(route_raw(wind_along=14.0), 13, profile=c.ENROUTE)
    head = c.score_hour(route_raw(wind_along=-14.0), 13, profile=c.ENROUTE)
    assert head.score < tail.score
    assert head.limiting == "wind_along"
    assert head.limiting_label == "ветер вдоль курса"


def test_lee_side_veto_fires_only_at_takeoff():
    raw = ideal_hour(dir_offset=100.0)
    assert "lee_side" in c.score_hour(raw, 13, profile=c.TAKEOFF).vetoes
    assert "lee_side" not in c.score_hour(raw, 13, profile=c.GOAL).vetoes


def test_working_altitude_wind_veto_fires_in_all_three_profiles():
    """Отступление от ТЗ: на маршруте пилот в том же воздухе, что и над стартом."""
    for profile in (c.TAKEOFF, c.GOAL):
        a = c.score_hour(ideal_hour(wind_at_base=c.TRIM_MS + 1), 13, profile=profile)
        assert "wind_base" in a.vetoes, profile.key
    a = c.score_hour(route_raw(wind_at_base=c.TRIM_MS + 1), 13, profile=c.ENROUTE)
    assert "wind_base" in a.vetoes


def test_goal_profile_is_takeoff_without_the_direction_group():
    assert set(c.GOAL.groups) == set(c.GROUPS) - {"direction"}
    assert "dir_offset" not in c.GOAL.params
    assert "time_margin" in c.GOAL.params


def test_enroute_profile_has_no_ground_parameters():
    for key in ("wind_10m", "gust_factor", "gust_delta", "dir_offset", "shear_100m"):
        assert key not in c.ENROUTE.params


def test_launch_profile_has_no_route_parameters():
    for key in ("wind_along", "wind_cross", "working_band", "wind_working"):
        assert key not in c.TAKEOFF.params

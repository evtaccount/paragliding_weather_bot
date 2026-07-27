"""Свёртка маршрута: узкое место, статус выполнимости, граница лётной части."""
import pytest

import criteria as c


def pt(km, score, leg=10.0, vetoes=(), confidence=1.0, time_margin=200.0):
    """Точка с заранее заданной оценкой — свёртка не должна знать, откуда она."""
    a = c.HourAssessment(hour=13, score=score, category="fair", emoji="🟡", label="ок",
                         confidence=confidence, raw={"time_margin": time_margin})
    a.vetoes = list(vetoes)
    return {"km": km, "leg_length_km": leg, "assessment": a}


def test_formula_is_bottleneck_plus_weighted_mean():
    points = [pt(0, 80), pt(10, 80), pt(20, 40)]
    r = c.score_route(points)
    # балл округляется до десятой — сравниваем с тем же допуском
    assert r.score == pytest.approx(0.6 * 40 + 0.4 * (80 + 80 + 40) / 3, abs=0.05)


def test_mean_is_weighted_by_leg_length_not_by_point_count():
    short = c.score_route([pt(0, 100, leg=1.0), pt(10, 40, leg=99.0)])
    long = c.score_route([pt(0, 100, leg=99.0), pt(10, 40, leg=1.0)])
    assert long.score > short.score


def test_one_bad_point_does_not_make_the_day_excellent():
    points = [pt(i * 10, 90) for i in range(9)] + [pt(90, 20)]
    r = c.score_route(points)
    assert r.category not in ("ideal", "excellent")


def test_one_bad_point_does_not_zero_the_route():
    points = [pt(i * 10, 90) for i in range(9)] + [pt(90, 0, vetoes=["route_terrain_block"])]
    r = c.score_route(points)
    assert r.score > 0


def test_feasibility_blocked_names_kilometre_and_reason():
    points = [pt(0, 90), pt(10, 0, vetoes=["route_terrain_block"]), pt(20, 90)]
    r = c.score_route(points)
    assert r.feasibility == "blocked_at_km"
    assert r.blocked_at_km == 10
    assert r.blocked_reason == "route_terrain_block"


def test_feasibility_cannot_be_completable_with_a_veto():
    """Ошибка в сторону оптимизма — самая опасная из возможных."""
    points = [pt(0, 90), pt(10, 0, vetoes=["route_no_progress"])]
    assert c.score_route(points).feasibility != "completable"


def test_flyable_until_is_the_last_point_before_the_veto():
    points = [pt(0, 90), pt(10, 90), pt(20, 0, vetoes=["route_terrain_block"]), pt(30, 90)]
    assert c.score_route(points).flyable_until_km == 10


def test_flyable_until_is_the_whole_route_when_nothing_blocks():
    points = [pt(0, 90), pt(10, 90), pt(20, 90)]
    assert c.score_route(points).flyable_until_km == 20


def test_too_slow_when_the_goal_has_almost_no_margin():
    points = [pt(0, 90), pt(10, 90, time_margin=5.0)]
    assert c.score_route(points).feasibility == "too_slow"


def test_unknown_when_data_is_thin():
    points = [pt(0, 90), pt(10, 90, confidence=0.4)]
    assert c.score_route(points).feasibility == "unknown"


def test_points_without_a_score_do_not_enter_the_mean():
    points = [pt(0, 90), pt(10, None), pt(20, 90)]
    r = c.score_route(points)
    assert r.score == pytest.approx(90.0)
    assert r.feasibility == "unknown"


def test_all_points_without_a_score():
    r = c.score_route([pt(0, None), pt(10, None)])
    assert r.score is None
    assert r.feasibility == "unknown"


def test_bottleneck_reports_the_worst_point():
    points = [pt(0, 90), pt(10, 48), pt(20, 70)]
    b = c.score_route(points).bottleneck
    assert b["km"] == 10 and b["score"] == 48


# ---------------------------------------------------------------- гроза впереди
def stormy(km, leg=10.0, eta="14:20"):
    p = pt(km, 0, leg=leg, vetoes=["cape_cin"])
    p["eta"] = eta
    return p


def test_warning_appears_on_approach_not_only_at_the_cell():
    """Ячейка на 80-м км: со старта её не видно, а с 20-го и 40-го уже да."""
    points = [pt(0, 90), pt(20, 90), pt(40, 90), stormy(80)]
    for p in points:
        p.setdefault("eta", "12:00")
    ahead = c.storm_ahead(points)
    assert ahead[0] is None                     # 80 км — за горизонтом упреждения
    assert ahead[1] == {"km": 80, "eta": "14:20"}
    assert ahead[2] == {"km": 80, "eta": "14:20"}


def test_the_horizon_boundary_is_inclusive():
    """Ровно 60 км — ещё предупреждаем: ошибаться тут стоит в сторону осторожности."""
    points = [pt(0, 90), stormy(60)]
    points[0]["eta"] = "12:00"
    assert c.storm_ahead(points)[0] is not None


def test_nothing_beyond_the_lookahead_horizon():
    points = [pt(0, 90), stormy(70)]
    points[0]["eta"] = "12:00"
    assert c.storm_ahead(points)[0] is None


def test_only_storm_vetoes_count():
    points = [pt(0, 90), pt(20, 0, vetoes=["route_terrain_block"])]
    for p in points:
        p["eta"] = "12:00"
    assert c.storm_ahead(points)[0] is None


def test_the_nearest_cell_ahead_wins():
    points = [pt(0, 90), stormy(20, eta="13:00"), stormy(40, eta="14:00")]
    points[0]["eta"] = "12:00"
    assert c.storm_ahead(points)[0]["km"] == 20

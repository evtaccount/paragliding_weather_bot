"""Вето и штрафы.

Каждый тест стартует от идеального часа и портит РОВНО одно поле — так видно,
что сработало проверяемое правило, а не соседнее. Второй блок проверяет
обратное: если входа правила нет, вето не срабатывает, а честно попадает в
unchecked_vetoes. Молчаливое «не проверили — значит хорошо» опаснее, чем
отсутствие оценки.
"""
import pytest

import criteria as c
from fixtures import ideal_hour

# (ключ вето, поле, значение, которое обязано его вызвать)
TRIGGERS = [
    ("precip_hour",      "precip_mm", 0.4),
    ("precip_prob",      "precip_prob", 80.0),
    ("cape_extreme",     "cape", 3000.0),
    ("lifted_index",     "lifted_index", -5.0),
    ("lee_side",         "dir_offset", 120.0),
    ("wind_launch",      "wind_10m", 11.0),
    ("wind_base",        "wind_at_base", 12.0),
    ("gust_factor",      "gust_factor", 1.9),
    ("gust_delta",       "gust_delta", 6.0),
    ("base_below_route", "base_over_route", -50.0),
    ("visibility",       "visibility", 800.0),
    ("shear",            "shear_100m", 8.0),
]


def test_the_ideal_hour_scores_a_hundred():
    a = c.score_hour(ideal_hour(), 13)
    assert a.score == 100.0 and a.category == "ideal"
    assert a.vetoes == [] and a.penalties == []
    assert a.limiting is None            # ограничивать нечему
    assert a.confidence == 1.0


@pytest.mark.parametrize("veto,field,value", TRIGGERS, ids=[t[0] for t in TRIGGERS])
def test_each_veto_zeroes_the_score(veto, field, value):
    a = c.score_hour(ideal_hour(**{field: value}), 13)
    assert veto in a.vetoes
    assert a.score == 0.0 and a.category == "danger" and a.emoji == "⛔"


def test_cape_with_low_cin_is_a_veto_but_cape_alone_is_not():
    """Правило документа: опасен не сам CAPE, а CAPE при снятой крышке."""
    lid = c.score_hour(ideal_hour(cape=1800.0, cin=100.0), 13)   # крышка держит
    assert "cape_cin" not in lid.vetoes and lid.score > 0

    open_ = c.score_hour(ideal_hour(cape=1800.0, cin=10.0), 13)  # крышка снята
    assert "cape_cin" in open_.vetoes and open_.score == 0.0


@pytest.mark.parametrize("veto,field,_v", TRIGGERS, ids=[t[0] for t in TRIGGERS])
def test_missing_input_reports_unchecked_instead_of_firing(veto, field, _v):
    a = c.score_hour(ideal_hour(**{field: None}), 13)
    assert veto in a.unchecked_vetoes
    assert veto not in a.vetoes
    assert a.score > 0, "отсутствие данных не должно обнулять балл"


def test_high_cape_without_cin_caps_the_storm_group_instead_of_vetoing():
    """CIN неизвестен: вето проверить нечем, но зелёную группу «грозы» рисовать нельзя."""
    a = c.score_hour(ideal_hour(cape=1800.0, cin=None), 13)
    assert "cape_cin" in a.unchecked_vetoes and "cape_cin" not in a.vetoes
    assert a.groups["storms"] <= c.GRADE_SCORE["marginal"]
    assert a.score < 100.0


def test_veto_labels_are_human_readable():
    assert c.veto_labels(["visibility", "lee_side"]) == [
        "видимость <1,5 км", "старт с подветра"]


# ---------------------------------------------------------------- штрафы
def test_wind_times_thermals_penalty_is_multiplicative():
    """Сильный ветер и мощные потоки вместе дают мультипликативный риск."""
    calm = c.score_hour(ideal_hour(wind_10m=8.5), 13)
    both = c.score_hour(ideal_hour(wind_10m=8.5, w_star=4.0), 13)
    assert "wind_x_thermal" not in calm.penalties
    assert both.penalties == ["wind_x_thermal"]
    assert both.score < calm.score


def test_direction_misalignment_penalty():
    a = c.score_hour(ideal_hour(dir_misalign=60.0), 13)
    assert a.penalties == ["dir_misalign"]
    assert a.score == pytest.approx(85.0)   # 100 × 0,85


def test_low_base_penalty_needs_active_thermals():
    lazy = c.score_hour(ideal_hour(base_clearance=250.0, w_star=1.5), 13)
    active = c.score_hour(ideal_hour(base_clearance=250.0, w_star=2.5), 13)
    assert "low_base_active" not in lazy.penalties
    assert "low_base_active" in active.penalties


def test_penalty_with_missing_input_does_not_apply():
    a = c.score_hour(ideal_hour(dir_misalign=None), 13)
    assert a.penalties == []


def test_penalties_stack():
    a = c.score_hour(ideal_hour(wind_10m=8.5, w_star=4.0, dir_misalign=60.0), 13)
    assert set(a.penalties) == {"wind_x_thermal", "dir_misalign"}

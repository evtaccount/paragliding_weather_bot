"""Таблица порогов: структура и границы бэндов.

Границы полуоткрытые [lo, hi) — значение НА границе принадлежит верхнему
интервалу. Тест проходит по каждой границе каждого параметра, поэтому опечатка
в таблице (разрыв, наложение, чужой уровень) падает здесь, а не всплывает
молчаливым «параметр без оценки» в проде.
"""
import pytest

import criteria as c

EPS = 1e-6


def _edges(param):
    """Все внутренние границы интервалов параметра, по возрастанию."""
    xs = {lo for _g, ivs in param.bands for lo, _hi in ivs if lo is not None}
    xs |= {hi for _g, ivs in param.bands for _lo, hi in ivs if hi is not None}
    return sorted(xs)


@pytest.mark.parametrize("key", sorted(c.PARAMS))
def test_intervals_cover_the_axis_without_gaps(key):
    p = c.PARAMS[key]
    spans = sorted(((lo if lo is not None else float("-inf"),
                     hi if hi is not None else float("inf"))
                    for _g, ivs in p.bands for lo, hi in ivs))
    assert spans[0][0] == float("-inf")
    assert spans[-1][1] == float("inf")
    for (_lo1, hi1), (lo2, _hi2) in zip(spans, spans[1:]):
        assert hi1 == lo2, f"{key}: разрыв/наложение на {hi1}"


@pytest.mark.parametrize("key", sorted(c.PARAMS))
def test_every_edge_is_lower_inclusive(key):
    """На границе — уровень верхнего интервала; чуть ниже — предыдущего."""
    p = c.PARAMS[key]
    for x in _edges(p):
        at, below = p.grade(x), p.grade(x - EPS)
        assert at is not None and below is not None, f"{key}: нет уровня около {x}"
        assert at != below, f"{key}: граница {x} не разделяет уровни ({at})"


@pytest.mark.parametrize("key", sorted(c.PARAMS))
def test_grade_is_none_only_for_missing_value(key):
    assert c.grade_of(key, None) is None
    assert c.grade_of(key, 0.0) is not None


def test_weights_sum_to_one():
    assert abs(sum(g.weight for g in c.GROUPS.values()) - 1.0) < 1e-9


def test_every_group_has_at_least_one_parameter():
    for gkey in c.GROUPS:
        assert any(p.group == gkey for p in c.PARAMS.values()), f"группа {gkey} пустая"


def test_document_wind_thresholds():
    """Контрольные точки прямо из документа (км/ч → м/с)."""
    assert c.grade_of("wind_10m", 3.0) == "ideal"          # 11 км/ч
    assert c.grade_of("wind_10m", 5.0) == "excellent"      # 18 км/ч
    assert c.grade_of("wind_10m", 7.0) == "fair"           # 25 км/ч — раньше было «нелётно»
    assert c.grade_of("wind_10m", 8.5) == "marginal"       # 31 км/ч
    assert c.grade_of("wind_10m", 10.0) == "no_fly"        # 36 км/ч
    assert c.grade_of("wind_10m", c.TRIM_MS) == "danger"   # trim крыла


def test_non_monotonic_parameters_have_an_optimum_in_the_middle():
    # слабые потоки плохи, средние идеальны, слишком мощные — опасны
    assert c.grade_of("w_star", 0.5) == "no_fly"
    assert c.grade_of("w_star", 2.5) == "ideal"
    assert c.grade_of("w_star", 6.0) == "danger"
    # спред: насыщение плохо, 3–8 °C идеально, очень сухо — снова хуже
    assert c.grade_of("spread", 0.5) == "no_fly"
    assert c.grade_of("spread", 5.0) == "ideal"
    assert c.grade_of("spread", 20.0) == "marginal"
    # Thermal Index: чем отрицательнее, тем сильнее, но ≤−8 уже взрывная конвекция
    assert c.grade_of("thermal_index", 1.0) == "no_fly"
    assert c.grade_of("thermal_index", -4.0) == "ideal"
    assert c.grade_of("thermal_index", -9.0) == "danger"


def test_category_mapping_matches_the_document():
    assert c.category_of(90)[0] == "ideal"
    assert c.category_of(74)[0] == "excellent"
    assert c.category_of(60)[0] == "fair"
    assert c.category_of(45)[0] == "marginal"
    assert c.category_of(20)[0] == "no_fly"
    assert c.category_of(0)[0] == "danger"
    assert c.category_of(None)[0] == "no_data"


def test_flyable_covers_fair_and_better():
    assert c.flyable("ideal") and c.flyable("excellent") and c.flyable("fair")
    assert not c.flyable("marginal") and not c.flyable("no_fly") and not c.flyable("danger")

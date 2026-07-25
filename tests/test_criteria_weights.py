"""Перенормировка весов при неполных данных и свёртка дня.

Это самая тонкая часть: модель может не отдать целую группу параметров
(ECMWF не даёт ни глубины пограничного слоя, ни сдвига ветра, ни видимости).
Считать такой час нельзя ни как «идеальный», ни как «нулевой» — вес выбывшей
группы перераспределяется, а уверенность честно падает.
"""
import pytest

import criteria as c
from fixtures import ideal_hour


def _blank(*keys):
    """Идеальный час, из которого выбиты указанные параметры."""
    return ideal_hour(**{k: None for k in keys})


def test_missing_parameter_is_reported_and_excluded():
    a = c.score_hour(_blank("visibility"), 13)
    assert "no_data:visibility" in a.warnings
    assert "visibility" not in a.subs


def test_dropping_a_whole_group_renormalises_the_weights():
    """Группа «сдвиг ветра» (вес 0,06) выбывает целиком — остальные 0,94 делят балл."""
    a = c.score_hour(_blank("shear_100m"), 13)
    assert "shear" not in a.groups
    assert a.confidence == pytest.approx(0.94)
    assert a.score == 100.0     # оставшиеся группы всё ещё идеальны


def test_renormalised_weighted_sum_matches_a_hand_computed_number():
    """Ветер маргинален (40), сдвига нет вовсе, остальное идеально.

    Вручную: вес ветра 0,22, выбывший сдвиг 0,06 → сумма весов 0,94.
    (0,22×40 + 0,72×100) / 0,94 = 85,96
    Итоговый балл ниже: сверху его режет потолок по лимитирующему фактору.
    """
    a = c.score_hour(ideal_hour(shear_100m=None, wind_10m=8.5), 13)
    assert a.groups["wind"] == 40
    assert a.weighted == pytest.approx((0.22 * 40 + 0.72 * 100) / 0.94, abs=0.05)
    assert a.capped and a.score < a.weighted


def test_group_uses_the_worst_parameter_for_safety_groups():
    """Свёртка «по худшему»: удачное направление не компенсирует сильный ветер."""
    a = c.score_hour(ideal_hour(wind_850=13.0), 13)   # 850 гПа нелётно, у земли идеально
    assert a.groups["wind"] == c.GRADE_SCORE["no_fly"]


def test_group_uses_the_mean_for_thermals():
    """У термички важна общая картина, а не одно число."""
    a = c.score_hour(ideal_hour(bl_depth=400.0), 13)  # мелкий слой, W* и TI идеальны
    assert a.groups["thermals"] == pytest.approx((100 + 40 + 100) / 3)


def test_ecmwf_shaped_gaps_still_produce_a_score():
    """Реальный случай: модель без пограничного слоя, сдвига, видимости и LI."""
    a = c.score_hour(_blank("bl_depth", "w_star", "shear_100m", "visibility", "lifted_index"), 13)
    assert a.score is not None and a.category != "no_data"
    assert "shear" not in a.groups
    assert a.groups["thermals"] == 100          # остался только Thermal Index
    # Термичка считается по одному параметру из трёх, грозы и осадки — по одному
    # из двух, сдвиг выбыл целиком: 0,15×⅓ + 0,12×½ + 0,06×½ + 0 вместо полных весов
    assert a.confidence == pytest.approx(0.75)
    assert {"shear", "visibility"} <= set(a.unchecked_vetoes)


def test_confidence_counts_parameters_not_just_surviving_groups():
    """Группа «грозы» выживает на одном CAPE без Lifted Index — считать это
    стопроцентной уверенностью нельзя, иначе строка «критериев посчитано»
    показывала бы 100% при половине отсутствующих параметров."""
    a = c.score_hour(_blank("lifted_index"), 13)
    assert "storms" in a.groups                      # группа жива и участвует в балле
    assert a.confidence == pytest.approx(1.0 - 0.12 / 2)


def test_low_confidence_caps_the_category():
    """Нельзя объявить идеальный день, не проверив треть критериев."""
    drop = ["wind_10m", "wind_925", "wind_850",      # −0,22
            "gust_factor", "gust_delta",              # −0,15
            "dir_offset",                             # −0,12
            "cape", "lifted_index"]                   # −0,12  → остаётся 0,39
    a = c.score_hour(_blank(*drop), 13)
    assert a.confidence < c.MIN_CONFIDENCE
    assert "low_confidence" in a.warnings
    assert a.category == "fair" and a.score <= 69


def test_no_data_at_all_yields_no_score():
    a = c.score_hour({}, 13)
    assert a.score is None and a.category == "no_data" and a.emoji == "⚪"


# ---------------------------------------------------------------- свёртка дня
def _hours(scores, start=8):
    """Часы с заданными баллами — через реальный score_hour, меняя один параметр."""
    out = []
    for i, wind in enumerate(scores):
        out.append(c.score_hour(ideal_hour(wind_10m=wind), start + i))
    return out


def test_day_score_is_the_mean_over_the_thermal_window():
    hours = _hours([3.0, 3.0, 8.5, 8.5, 3.0])            # 100, 100, 86, 86, 100
    window = {"start_hour": 10, "end_hour": 11, "peak_hour": 10}
    day = c.score_day("2026-07-25", hours, window)
    inside = [h.score for h in hours if 10 <= h.hour <= 11]
    assert day.score == pytest.approx(sum(inside) / len(inside), abs=0.05)


def test_day_ignores_hours_outside_the_window():
    """Раздутый вечер вне окна не должен топить хороший день (и наоборот)."""
    hours = _hours([3.0, 3.0, 3.0, 11.0, 11.0])          # два последних часа — вето
    window = {"start_hour": 8, "end_hour": 10, "peak_hour": 9}
    day = c.score_day("2026-07-25", hours, window)
    assert day.score == 100.0 and day.category == "ideal"


def test_day_limiting_factor_is_the_most_common_one_in_the_window():
    hours = [c.score_hour(ideal_hour(gust_factor=1.5), 11),
             c.score_hour(ideal_hour(gust_factor=1.5), 12),
             c.score_hour(ideal_hour(wind_10m=8.5), 13)]
    window = {"start_hour": 11, "end_hour": 13, "peak_hour": 12}
    day = c.score_day("2026-07-25", hours, window)
    assert day.limiting == "gust_factor"
    assert day.limiting_label == c.PARAMS["gust_factor"].label


def test_day_reports_the_flyable_span_and_aggregates_warnings():
    hours = [c.score_hour(ideal_hour(wind_10m=11.0), 10),   # вето
             c.score_hour(_blank("visibility"), 11),
             c.score_hour(_blank("visibility"), 12)]
    window = {"start_hour": 10, "end_hour": 12, "peak_hour": 11}
    day = c.score_day("2026-07-25", hours, window)
    assert day.fly_window == (11, 12)
    assert day.warnings.count("no_data:visibility") == 1   # без повторов
    assert "visibility" in day.unchecked_vetoes


def test_day_without_a_window_falls_back_to_all_hours():
    hours = _hours([3.0, 8.5])
    day = c.score_day("2026-07-25", hours, None)
    assert day.score == pytest.approx((hours[0].score + hours[1].score) / 2, abs=0.05)

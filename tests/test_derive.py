"""Производные метрики: то, чего open-meteo не отдаёт напрямую.

Каждая величина проверяется против числа, посчитанного вручную, — иначе
«оценка» превращается в правдоподобно выглядящую выдумку. Отдельный блок
проверяет деградацию: если модель не отдала поле, метрика должна быть None,
а не подставленным значением.
"""
import math

import pytest

import criteria
import engine
from fixtures import om_1day, om_null, site


def _ctx(data, s):
    return engine.day_context(data, s)


def _raw(data, s, hour=13):
    ctx = _ctx(data, s)
    i = next(i for i in ctx["daylight_idx"] if engine.hour_of(data["hourly"]["time"][i]) == hour)
    return engine.derive_hour(data["hourly"], i, s, ctx)


# ---------------------------------------------------------------- порывистость
def test_gust_factor_and_delta():
    """Выше опорного ветра отношение считается напрямую: 11,2 / 8,0 = 1,4."""
    r = _raw(om_1day(wind_speed_10m=8.0, wind_gusts_10m=11.2), site())
    assert r["gust_factor"] == pytest.approx(1.4)
    assert r["gust_delta"] == pytest.approx(3.2)


def test_a_lively_but_flyable_thermic_day_is_not_called_unflyable():
    """4 м/с с порывом 7 (14→25 км/ч) — обычный рабочий день. По сырому
    отношению 1,75 группа порывов уходила в «нелётно» и топила весь день."""
    r = _raw(om_1day(wind_speed_10m=4.0, wind_gusts_10m=7.0), site())
    a = criteria.score_hour(r, 13)
    assert criteria.grade_of("gust_factor", r["gust_factor"]) == "ideal"
    assert a.groups["gusts"] == criteria.GRADE_SCORE["fair"]   # решает абсолютный отрыв
    assert criteria.flyable(a.category)


def test_gust_factor_denominator_is_floored_at_the_reference_wind():
    """Штиль 0,3 м/с с порывом 0,5 — это не «порывистость 1,67», это штиль."""
    r = _raw(om_1day(wind_speed_10m=0.3, wind_gusts_10m=0.5), site())
    assert r["gust_factor"] == pytest.approx(0.5 / criteria.GUST_FACTOR_REF_WIND_MS, abs=0.01)
    assert criteria.grade_of("gust_factor", r["gust_factor"]) == "ideal"
    assert r["gust_delta"] == pytest.approx(0.2)


def test_ordinary_thermic_afternoon_is_not_vetoed_by_the_gust_ratio():
    """Реальный час с Лалискури: ветер 2,1 м/с, порыв 5,6. До ограничения
    знаменателя «фактор 2,62» давал вето и красил обычный рабочий день в ⛔."""
    r = _raw(om_1day(wind_speed_10m=2.14, wind_gusts_10m=5.64), site())
    a = criteria.score_hour(r, 14)
    assert "gust_factor" not in a.vetoes
    assert a.category != "danger"
    # рваность всё равно видна — через абсолютный отрыв
    assert criteria.grade_of("gust_delta", r["gust_delta"]) == "marginal"
    assert a.groups["gusts"] == criteria.GRADE_SCORE["marginal"]


def test_a_real_gust_front_still_triggers_the_veto():
    """6 м/с с порывом 11 — отношение 1,83, это уже вето по порывистости."""
    r = _raw(om_1day(wind_speed_10m=6.0, wind_gusts_10m=11.0), site())
    a = criteria.score_hour(r, 14)
    assert "gust_factor" in a.vetoes and a.category == "danger"
    # тот же порыв при более слабом ветре ловится вторым правилом — по отрыву
    hard = _raw(om_1day(wind_speed_10m=4.0, wind_gusts_10m=11.0), site())
    assert "gust_delta" in criteria.score_hour(hard, 14).vetoes


# ---------------------------------------------------------------- сдвиг у земли
def test_shear_is_a_vector_difference_not_a_speed_difference():
    """Ветер 4 м/с с юга у земли и 4 м/с с запада на 100 м: скорости равны,
    но воздух разворачивает на 90° — сдвиг есть, и он не нулевой."""
    data = om_1day(wind_speed_10m=4.0, wind_direction_10m=180.0,
                   wind_speed_80m=4.0, wind_direction_80m=270.0,
                   wind_speed_120m=4.0, wind_direction_120m=270.0)
    r = _raw(data, site())
    assert r["shear_100m"] == pytest.approx(4.0 * math.sqrt(2), abs=0.05)


def test_shear_interpolates_100m_between_80_and_120():
    data = om_1day(wind_speed_10m=2.0, wind_direction_10m=180.0,
                   wind_speed_80m=4.0, wind_direction_80m=180.0,
                   wind_speed_120m=8.0, wind_direction_120m=180.0)
    # 100 м = ровно посередине между 80 (4 м/с) и 120 (8 м/с) → 6 м/с; сдвиг 6−2
    assert _raw(data, site())["shear_100m"] == pytest.approx(4.0)


def test_shear_falls_back_to_80m_when_120m_is_missing():
    data = om_null(om_1day(wind_speed_10m=2.0, wind_direction_10m=180.0,
                           wind_speed_80m=5.0, wind_direction_80m=180.0),
                   "wind_speed_120m", "wind_direction_120m")
    assert _raw(data, site())["shear_100m"] == pytest.approx(3.0)


def test_shear_is_none_without_the_80m_level():
    """925 гПа подменой не служит — это ~750 м, другая физическая величина."""
    data = om_null(om_1day(), "wind_speed_80m", "wind_direction_80m")
    assert _raw(data, site())["shear_100m"] is None


# ---------------------------------------------------------------- база облаков
def test_cloud_base_uses_the_espy_rule():
    r = _raw(om_1day(temperature_2m=25.0, dew_point_2m=5.0), site())
    assert r["spread"] == pytest.approx(20.0)
    assert r["base_clearance"] == criteria.LCL_M_PER_C * 20


def test_saturated_air_gives_a_zero_base_not_a_negative_one():
    r = _raw(om_1day(temperature_2m=10.0, dew_point_2m=12.0), site())
    assert r["base_clearance"] == 0


def test_route_top_clearance_only_exists_when_the_site_declares_one():
    data = om_1day(temperature_2m=20.0, dew_point_2m=15.0)   # база 610 м над стартом
    assert _raw(data, site())["base_over_route"] is None
    # старт 1500 м, база ~2110 MSL, вершины маршрута 2000 м → запас ~110 м
    r = _raw(data, site(route_top_m=2000))
    assert r["base_over_route"] == pytest.approx(110, abs=1)


# ---------------------------------------------------------------- W*
def test_w_star_matches_the_deardorff_formula():
    data = om_1day(boundary_layer_height=1500.0, shortwave_radiation=800.0, temperature_2m=20.0)
    elev = 1500
    rho = engine.air_density(elev)
    q = engine.SENSIBLE_HEAT_FRACTION * 800.0
    expect = ((9.81 / 293.15) * (q / (rho * 1005.0)) * 1500.0) ** (1 / 3)
    assert _raw(data, site(elevation_m=elev))["w_star"] == pytest.approx(expect, abs=0.01)


def test_w_star_accounts_for_altitude_density():
    """На 2500 м воздух реже — при том же прогреве потоки считаются сильнее."""
    data = om_1day(boundary_layer_height=1500.0, shortwave_radiation=800.0)
    low = _raw(data, site(elevation_m=200))["w_star"]
    high = _raw(data, site(elevation_m=2500))["w_star"]
    assert high > low
    assert engine.air_density(2500) < engine.air_density(200)


def test_w_star_is_zero_without_sun_and_none_without_a_boundary_layer():
    assert _raw(om_1day(shortwave_radiation=0.0), site())["w_star"] == 0.0
    data = om_null(om_1day(), "boundary_layer_height")
    assert _raw(data, site())["w_star"] is None


# ---------------------------------------------------------------- Thermal Index
def test_thermal_index_against_a_hand_computed_sounding():
    """Старт 1500 м, приземные 25 °C. Рабочий уровень 2500 м.
    Частица по сухой адиабате: 25 − 9,8 = 15,2 °C.
    Среда между 850 гПа (1500 м, 12 °C) и 700 гПа (3000 м, 3 °C):
    на 2500 м это 12 + (1000/1500)×(3−12) = 6,0 °C.  TI = 6,0 − 15,2 = −9,2
    """
    data = om_1day(temperature_2m=25.0, temperature_850hPa=12.0, temperature_700hPa=3.0,
                   geopotential_height_850hPa=1500.0, geopotential_height_700hPa=3000.0)
    r = _raw(data, site(elevation_m=1500))
    assert r["ti_level_m"] == 2500
    assert r["thermal_index"] == pytest.approx(-9.2, abs=0.05)


def test_thermal_index_does_not_extrapolate_beyond_the_profile():
    """Старт выше 700 гПа: уровень зажимается в границы профиля, а не улетает
    в экстраполяцию стратификации."""
    data = om_1day(geopotential_height_850hPa=1500.0, geopotential_height_700hPa=3000.0)
    assert _raw(data, site(elevation_m=3500))["ti_level_m"] == 3000


def test_thermal_index_is_none_without_upper_level_temperatures():
    data = om_null(om_1day(), "temperature_850hPa", "temperature_700hPa")
    assert _raw(data, site())["thermal_index"] is None


# ---------------------------------------------------------------- ветер на базе
def test_wind_at_base_interpolates_the_profile():
    """Старт 700 м, база 610 м над ним → 1310 MSL. Это между 925 гПа (760 м,
    3 м/с) и 850 гПа (1500 м, 4 м/с): 3 + (550/740)×1 = 3,74"""
    data = om_1day(temperature_2m=20.0, dew_point_2m=15.0)
    r = _raw(data, site(elevation_m=700))
    assert r["wind_at_base"] == pytest.approx(3.74, abs=0.05)


def test_profile_drops_pressure_levels_below_the_launch():
    """Под высоким стартом 925 гПа «под землёй» — брать оттуда ветер нельзя."""
    data = om_1day()
    assert engine._profile(data["hourly"], 13, 2685) == [(2695, 2.0), (3000, 6.0)]
    assert len(engine._profile(data["hourly"], 13, 400)) == 4


def test_wind_at_base_clamps_below_the_lowest_level():
    data = om_1day(temperature_2m=20.0, dew_point_2m=19.9)  # база почти у земли
    assert _raw(data, site())["wind_at_base"] == pytest.approx(2.0)


# ---------------------------------------------------------------- рассогласование
def test_direction_misalignment_across_the_boundary_layer():
    data = om_1day(wind_direction_10m=180.0, wind_direction_80m=180.0,
                   wind_direction_925hPa=200.0, wind_direction_850hPa=250.0,
                   geopotential_height_925hPa=1600.0, geopotential_height_850hPa=2000.0,
                   boundary_layer_height=1000.0)
    assert _raw(data, site(elevation_m=1500))["dir_misalign"] == pytest.approx(70.0)


def test_direction_misalignment_ignores_levels_above_the_boundary_layer():
    data = om_1day(wind_direction_10m=180.0, wind_direction_80m=180.0,
                   wind_direction_925hPa=200.0, wind_direction_850hPa=350.0,
                   geopotential_height_925hPa=1600.0, geopotential_height_850hPa=4000.0,
                   boundary_layer_height=1000.0)   # верх слоя 2500 MSL — 850 гПа выше
    assert _raw(data, site(elevation_m=1500))["dir_misalign"] == pytest.approx(20.0)


# ---------------------------------------------------------------- фён
def test_foehn_is_a_heuristic_warning_not_a_veto():
    data = om_1day(wind_speed_850hPa=12.0, wind_direction_850hPa=190.0,
                   temperature_2m=25.0, dew_point_2m=5.0,
                   relative_humidity_925hPa=25.0, cloud_cover_low=5.0)
    r = _raw(data, site())
    assert r["foehn_suspect"] is True
    a = criteria.score_hour(r, 13)
    assert "foehn" not in " ".join(a.vetoes), "фён не может быть вето на точечных данных"


def test_foehn_needs_all_signs_together():
    wet = om_1day(wind_speed_850hPa=12.0, wind_direction_850hPa=190.0,
                  temperature_2m=15.0, dew_point_2m=14.0,     # спред маленький
                  relative_humidity_925hPa=25.0, cloud_cover_low=5.0)
    assert _raw(wet, site())["foehn_suspect"] is False


# ---------------------------------------------------------------- контекст дня
def test_window_hours_comes_from_the_thermal_window():
    data = om_1day()
    ctx = _ctx(data, site())
    w = ctx["thermal_window"]
    assert _raw(data, site())["window_hours"] == w["end_hour"] - w["start_hour"] + 1


def test_assess_day_scores_every_daylight_hour():
    day, ctx = engine.assess_day(om_1day(), site())
    assert len(day.hours) == len(ctx["daylight_idx"])
    assert day.score is not None and day.category != "no_data"
    assert day.window == ctx["thermal_window"]


def test_assess_day_on_an_ecmwf_shaped_response_still_scores():
    """Модель без пограничного слоя, видимости, LI, CIN и ветра на 80/120 м."""
    data = om_null(om_1day(), "boundary_layer_height", "freezing_level_height",
                   "visibility", "lifted_index", "convective_inhibition",
                   "wind_speed_80m", "wind_direction_80m",
                   "wind_speed_120m", "wind_direction_120m")
    day, _ctx = engine.assess_day(data, site())
    assert day.score is not None
    assert day.confidence < 1.0
    noon = next(h for h in day.hours if h.hour == 13)
    assert "no_data:w_star" in noon.warnings and "no_data:shear_100m" in noon.warnings
    assert {"shear", "visibility", "cape_cin"} <= set(noon.unchecked_vetoes)


def test_adhoc_point_without_aspect_drops_the_direction_group():
    day, _ctx = engine.assess_day(om_1day(), site(aspect=None, aspect_deg=None))
    noon = next(h for h in day.hours if h.hour == 13)
    assert "no_data:dir_offset" in noon.warnings
    assert "direction" not in noon.groups
    assert "lee_side" in noon.unchecked_vetoes


def test_slope_deg_treats_a_none_value_the_same_as_a_missing_key():
    """Сохранённый старт из store.load_sites() и старт из старого JSON-формата
    описывают «уклон не задан» по-разному: у первого ключ slope_deg
    ПРИСУТСТВУЕТ со значением None (это колонка БД, она есть у каждой строки),
    у второго ключа нет вовсе. `dict.get(key, default)` подставляет default
    только когда ключ ОТСУТСТВУЕТ — на явный None он возвращает None. Без
    этого теста регрессия здесь выглядит как необъяснимый TypeError где-то
    глубоко в тригонометрии engine, а не как «форма старта из БД не
    обработана»."""
    assert engine._slope_deg({"slope_deg": None}) == engine.SLOPE_DEG
    assert engine._slope_deg({}) == engine.SLOPE_DEG
    assert engine._slope_deg({"slope_deg": 30.0}) == 30.0

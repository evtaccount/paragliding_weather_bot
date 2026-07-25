"""Графики берут пороги из criteria, а не из собственных литералов.

До этого charts.py повторял числа движка своими константами: `<= 7`, `<= 8`,
`> 6`, `> 10`, `0.2`, 122 м/°C. Совпадали они по случайности, и правка порога
в engine сдвинула бы текст карточки, но не картинку — а ни один тест этого
не ловил.
"""
import os

import charts
import criteria
import engine
from fixtures import om_1day, site


def test_grid_cell_colour_comes_from_the_level_own_band():
    """У земли, на 925 и на 850 пороги разные — одна шкала на всю таблицу врала бы."""
    # 7 м/с: у земли «удовлетворительно», на 925 ещё «отлично», на 850 «идеально»
    assert charts._grid_cell_color(7.0, "10 м") == charts.GRADE_RGB[criteria.grade_of("wind_10m", 7.0)]
    assert charts._grid_cell_color(7.0, "925") == charts.GRADE_RGB[criteria.grade_of("wind_925", 7.0)]
    assert charts._grid_cell_color(7.0, "850") == charts.GRADE_RGB[criteria.grade_of("wind_850", 7.0)]
    assert charts._grid_cell_color(7.0, "10 м") != charts._grid_cell_color(7.0, "850")


def test_levels_above_850_fall_back_to_the_850_scale():
    """Парапланерных порогов выше 850 гПа нет — берётся ближайшая осмысленная шкала."""
    for label in ("700", "600", "500"):
        assert charts._grid_cell_color(11.0, label) == charts._grid_cell_color(11.0, "850")


def test_every_grade_has_its_own_colour():
    colours = [charts.GRADE_RGB[g] for g in criteria.GRADES]
    assert len(set(colours)) == len(criteria.GRADES)


def test_meteogram_band_follows_the_assessment(tmp_path):
    """Полоса лётного окна рисуется по готовой оценке — своих порогов у графика нет."""
    data = om_1day()
    for h in range(16, 24):
        data["hourly"]["wind_speed_10m"][h] = 9.5
        data["hourly"]["wind_gusts_10m"][h] = 13.0
    assess, _ctx = engine.assess_day(data, site())
    path = charts.meteogram_png(data, site(), str(tmp_path), assess)
    assert os.path.getsize(path) > 1000
    assert max(assess.fly_hours) < 16


def test_meteogram_computes_the_assessment_itself_when_not_given(tmp_path):
    path = charts.meteogram_png(om_1day(), site(), str(tmp_path))
    assert os.path.exists(path)


def test_ceiling_chart_uses_the_shared_lcl_constant(tmp_path):
    """122 м на °C раньше был вписан числом и в engine, и в charts."""
    assert criteria.LCL_M_PER_C == 122
    path = charts.ceiling_png(om_1day(), site(), str(tmp_path))
    assert os.path.getsize(path) > 1000


def test_profile_chart_uses_the_shared_level_table(tmp_path):
    """Своя копия таблицы уровней молча теряла направления на 600 и 500 гПа."""
    labels = [lv[0] for lv in engine._GRID_LEVELS]
    assert labels[-2:] == ["600", "500"]
    assert all(lv[3] for lv in engine._GRID_LEVELS), "у каждого уровня есть направление"
    path = charts.profile_png(om_1day(), site(), str(tmp_path))
    assert os.path.getsize(path) > 1000

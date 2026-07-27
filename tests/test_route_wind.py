"""Знаки составляющих ветра и высотные величины.

Переворот знака попутного/встречного — самая частая содержательная ошибка на
маршрутных данных: ответ выглядит правдоподобно и советует противоположное.
Поэтому все восемь комбинаций проверяются явно.
"""
import pytest

import criteria
import route


@pytest.mark.parametrize("wind_from,track,along_sign,cross_sign", [
    (270, 90, +1, 0),    # запад в спину при курсе на восток — попутный
    (90, 90, -1, 0),     # восток в лоб при курсе на восток — встречный
    (0, 90, 0, +1),      # север дует на юг; при курсе на восток юг справа — снос вправо
    (180, 90, 0, -1),    # юг дует на север; при курсе на восток север слева — снос влево
    (180, 0, +1, 0),     # юг при курсе на север — попутный
    (0, 0, -1, 0),       # север при курсе на север — встречный
    (270, 0, 0, +1),     # запад при курсе на север — сносит вправо
    (90, 0, 0, -1),      # восток при курсе на север — сносит влево
])
def test_all_eight_wind_track_combinations(wind_from, track, along_sign, cross_sign):
    along, cross = route.wind_components(20.0, wind_from, track)
    assert (along > 1) == (along_sign > 0)
    assert (along < -1) == (along_sign < 0)
    assert (cross > 1) == (cross_sign > 0)
    assert (cross < -1) == (cross_sign < 0)


def test_tailwind_magnitude_equals_wind_speed():
    along, cross = route.wind_components(20.0, 270, 90)
    assert along == pytest.approx(20.0)
    assert cross == pytest.approx(0.0, abs=1e-9)


def test_quartering_wind_splits_by_root_two():
    along, cross = route.wind_components(20.0, 225, 90)
    assert along == pytest.approx(14.14, abs=0.02)
    assert cross == pytest.approx(-14.14, abs=0.02)


def test_components_none_without_wind():
    assert route.wind_components(None, 270, 90) == (None, None)
    assert route.wind_components(20.0, None, 90) == (None, None)


def test_cloud_base_uses_criteria_constant():
    base = route.cloud_base_m(1000.0, 20.0, 8.0)
    assert base == pytest.approx(1000.0 + criteria.LCL_M_PER_C * 12.0)


def test_cloud_base_none_without_inputs():
    assert route.cloud_base_m(None, 20.0, 8.0) is None
    assert route.cloud_base_m(1000.0, None, 8.0) is None


def test_working_band():
    assert route.working_band_m(3000.0, 1000.0) == pytest.approx(3000.0 - 1300.0)


def test_working_band_negative_when_base_below_safe_height():
    assert route.working_band_m(1100.0, 1000.0) == pytest.approx(-200.0)


def test_working_band_none_without_terrain():
    assert route.working_band_m(3000.0, None) is None
    assert route.working_band_m(None, 1000.0) is None


def test_ms_to_kmh():
    assert route.ms_to_kmh(10.0) == pytest.approx(36.0)
    assert route.ms_to_kmh(None) is None

"""Карточка на день и данные для LLM поверх скоринга.

Главное, что здесь проверяется, — что карточка, полоса на метеограмме и payload
для модели берут лётность из ОДНОГО расчёта. Раньше карточка и график сверяли
пороги независимо, совпадали по случайности и разъезжались от любой правки.
"""
import tempfile

import criteria
import engine
from fixtures import om_1day, om_null, site


def _card(data, s=None, **kw):
    text, pngs, card = engine.report_1day(data, s or site(), tempfile.mkdtemp(), **kw)
    return text, pngs, card


def test_card_shows_score_limiting_factor_and_hourly_strip():
    text, _pngs, _c = _card(om_1day(wind_speed_10m=7.0, wind_gusts_10m=9.0))
    assert "/100" in text
    assert "🎯 Ограничивает:" in text
    assert "📈 По часам:" in text
    # в полосе есть час, эмодзи категории и балл
    strip = next(l for l in text.splitlines() if l.startswith("📈"))
    assert "13 " in strip and any(e in strip for e in ("🟢", "🟡", "🟠", "🔴", "⛔"))


def test_hourly_strip_covers_the_thermal_window_only():
    data = om_1day()
    assess, ctx = engine.assess_day(data, site())
    strip = engine.hourly_strip(assess, ctx["thermal_window"])
    hours = [int(chunk.split()[0]) for chunk in strip.split(" · ")]
    assert min(hours) == ctx["thermal_window"]["start_hour"]
    assert max(hours) == ctx["thermal_window"]["end_hour"]


def test_flying_window_and_meteogram_band_come_from_the_same_assessment():
    """Ветер задувает после 15:00 — и текст, и полоса на графике обязаны
    сузиться одинаково, потому что источник у них один."""
    data = om_1day()
    for h in range(16, 24):
        data["hourly"]["wind_speed_10m"][h] = 9.5
        data["hourly"]["wind_gusts_10m"][h] = 13.0
    assess, _ctx = engine.assess_day(data, site())
    text, _pngs, _c = _card(data)
    assert assess.fly_window is not None
    lo, hi = assess.fly_window
    assert f"⏱️ Лётное окно: {lo:02d}:00–{hi:02d}:00" in text
    assert hi < 16
    # график рисует полосу по тому же списку часов, что назвала карточка
    assert (assess.fly_hours[0], assess.fly_hours[-1]) == assess.fly_window
    assert all(_ctx["thermal_window"]["start_hour"] <= h <= _ctx["thermal_window"]["end_hour"]
               for h in assess.fly_hours)


def test_card_names_unchecked_vetoes_instead_of_staying_silent():
    """«Нет данных по видимости» не должно выглядеть как «с видимостью хорошо»."""
    data = om_null(om_1day(), "visibility")
    text, _pngs, _c = _card(data)
    assert "не проверено вето" in text and "видимость" in text
    assert "📊 Критериев посчитано:" in text


def test_route_top_veto_is_a_setup_hint_not_permanent_noise():
    """Вершины маршрута — необязательная настройка старта. Если бы это вето
    висело в строке «не проверено» на каждой карточке, строку начали бы
    пролистывать ровно тогда, когда в ней окажется настоящий пробел в данных."""
    text, _pngs, _c = _card(om_1day())
    note = next(l for l in text.splitlines() if l.startswith("📊"))
    assert "база ниже вершин" not in note
    assert "route_top_m" in text          # подсказка есть, но в оговорках

    with_top, _p, _c = _card(om_1day(), site(route_top_m=2000))
    assert "route_top_m" not in with_top


def test_direction_wording_agrees_with_the_score():
    """Подпись направления идёт по той же шкале, что и скоринг. Своя мягкая
    шкала давала прямое противоречие в одной карточке: ветер под 60° к склону
    подписывался «в лоб склону ✅», хотя именно он и обрушивал день."""
    assert engine.dir_verdict(180.0, 180.0)[0].endswith("в лоб склону ✅")   # 0°
    assert engine.dir_verdict(210.0, 180.0)[1] == "in"                      # 30° — ещё в лоб
    assert engine.dir_verdict(220.0, 180.0)[1] == "cross"                   # 40° — уже боковой
    assert "в лоб" not in engine.dir_verdict(240.0, 180.0)[0]               # 60° — не «в лоб»
    assert engine.dir_verdict(300.0, 180.0) == ("в спину ❌", "tail")        # 120° — подветер

    # и в самой карточке подпись не спорит с лимитирующим фактором
    text, _pngs, _c = _card(om_1day(wind_direction_10m=240.0))
    assert "в лоб склону" not in text
    assert "🎯 Ограничивает: отклонение ветра от склона" in text


def test_card_reports_vetoed_hours_inside_the_window():
    data = om_1day(precipitation=0.5, precipitation_probability=90.0)
    text, _pngs, _c = _card(data)
    assert "вето внутри окна" in text
    assert "осадки в этот час" in text


def test_card_flags_foehn_as_a_heuristic_not_a_fact():
    data = om_1day(wind_speed_850hPa=12.0, wind_direction_850hPa=190.0,
                   temperature_2m=25.0, dew_point_2m=5.0,
                   relative_humidity_925hPa=25.0, cloud_cover_low=5.0)
    text, _pngs, _c = _card(data)
    assert "фён" in text and "эвристика" in text


def test_card_carries_the_open_meteo_attribution():
    """Условие лицензии CC BY 4.0, под которой отдаются данные."""
    text, _pngs, _c = _card(om_1day())
    assert "Open-Meteo.com" in text


def test_card_still_degrades_without_a_boundary_layer():
    data = om_null(om_1day(), "boundary_layer_height", "freezing_level_height")
    text, pngs, _c = _card(data)
    assert "🧗 Потолок: н/д" in text
    assert not any("ceiling" in p for p in pngs)
    assert "/100" in text        # скоринг всё равно посчитан


# ---------------------------------------------------------------- данные для LLM
def test_facts_carry_the_deterministic_assessment():
    f = engine.facts_1day(om_1day(wind_speed_10m=7.0), site())
    a = f["assessment"]
    assert a["score"] is not None and a["category"]
    assert a["limiting_factor_ru"]
    assert "confidence" in a and "unchecked_vetoes" in a
    assert f["criteria_version"] == criteria.CRITERIA_VERSION


def test_facts_hourly_rows_carry_score_category_and_limiting():
    f = engine.facts_1day(om_1day(), site())
    row = next(r for r in f["hourly_daytime"] if r["time"] == "13:00")
    assert "score" in row and "cat" in row and "lim" in row
    # прежние поля никуда не делись
    assert "wind_ms" in row and "slope_sun_index" in row


def test_facts_expose_the_derived_numbers_behind_the_score():
    f = engine.facts_1day(om_1day(), site())
    d = f["derived_peak_hour"]
    assert "w_star" in d and "thermal_index" in d and "shear_100m" in d
    assert "ti_level_m" in d, "уровень расчёта TI должен быть назван явно"


def test_facts_list_unchecked_vetoes_in_words():
    f = engine.facts_1day(om_null(om_1day(), "visibility"), site())
    assert any("видимость" in v for v in f["assessment"]["unchecked_vetoes"])


def test_assessment_is_computed_once_and_shared():
    """report_1day и facts_1day принимают готовую оценку — три места не должны
    считать лётность независимо."""
    data = om_1day()
    assessment = engine.assess_day(data, site())
    text, _pngs, _c = _card(data, assessment=assessment)
    f = engine.facts_1day(data, site(), assessment)
    assert f"{round(assessment[0].score)}/100" in text
    assert f["assessment"]["score"] == round(assessment[0].score)

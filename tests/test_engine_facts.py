"""facts_1day: the LLM payload must include upper-level (600/500 hPa) wind direction,
now that H_1D fetches wind_direction_600hPa / _500hPa."""
import re

import engine
from fixtures import om_1day as _full_1d, site as _site


def test_facts_1day_carries_the_thermal_window_and_per_hour_sun():
    f = engine.facts_1day(_full_1d(), _site())
    w = f["thermal_window"]
    assert w["start_hour"] >= 7 and w["end_hour"] <= 19   # sunrise 05:00 / sunset 20:00
    hours = {h["time"]: h for h in f["hourly_daytime"]}
    assert hours["12:00"]["slope_sun_index"] > hours["06:00"]["slope_sun_index"]
    assert 165 < hours["12:00"]["sun_az_deg"] < 195       # south slope, sun on the face


def test_facts_overview_carries_a_thermal_window_per_day():
    data = _full_1d()
    f = engine.facts_overview(data, _site(), "3d")
    assert f["days_daytime"][0]["thermal_window"]["start_hour"] >= 7


def test_facts_1day_includes_upper_level_directions():
    f = engine.facts_1day(_full_1d(), _site())
    prof = {r["level"]: r for r in f["wind_profile_peak_hour"]}
    # the two top levels now carry a direction (previously hard-coded None → key absent)
    assert prof["600hPa"]["dir_deg"] == 220
    assert prof["500hPa"]["dir_deg"] == 230
    # lower levels unchanged
    assert prof["700hPa"]["dir_deg"] == 210
    assert prof["10m"]["dir_deg"] == 180


def test_peak_hour_matches_between_card_and_facts(tmp_path):
    """report_1day и facts_1day выбирали час пика по-разному: карточка — по
    рабочему окну с тай-брейком по солнцу на склоне, факты — по простому
    максимуму температуры за световой день. Профиль ветра, уходящий в Gemini,
    мог относиться не к тому часу, что видит пилот.

    Дневной ход температуры делаем плоским на краях окна: при ровном профиле
    два правила расходятся, а на «остром» пике совпали бы случайно.
    """
    temps = [12.0] * 24
    for h, v in ((9, 24.0), (10, 26.0), (11, 27.4), (12, 27.4),
                 (13, 27.4), (14, 27.0), (15, 26.0), (16, 24.0)):
        temps[h] = v
    data = _full_1d(temperature_2m=temps)
    facts = engine.facts_1day(data, _site())
    _text, _pngs, card = engine.report_1day(data, _site(), str(tmp_path))
    # Карточка печатает не сам час, а диапазон вокруг него: «пик 12–14».
    # Сравнивать со строкой «пик 13» нельзя — peak_lo это peak_hour - 1.
    m = re.search(r"пик (\d{2})–(\d{2})", card)
    assert m, f"в карточке нет строки пика:\n{card}"
    lo, hi = int(m.group(1)), int(m.group(2))
    assert lo <= facts["peak_hour"] <= hi


def test_facts_carry_direction_verdict():
    facts = engine.facts_1day(_full_1d(), _site())
    # dir_class приходит из уже существующего dir_verdict() — его домен "in" /
    # "cross" / "tail" (см. engine.dir_verdict), не "head" / "cross" / "tail".
    assert facts["dir_class"] in ("in", "cross", "tail")
    assert facts["dir_verdict"]
    assert 0 <= facts["fly_dir_deg"] < 360


def test_facts_carry_caveats():
    facts = engine.facts_1day(_full_1d(), _site())
    assert isinstance(facts["caveats"], list)
    # старт из fixtures.site() без route_top_m — вето «база ниже вершин» не проверяется
    assert any("route_top_m" in c for c in facts["caveats"])

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


# ------------------------------------------------- «голубой» день, одна формула
#
# Три места решали, есть ли облака-маркеры, и решали по-разному: карточка и
# оговорки под ней сравнивали LCL с пограничным слоем в ЧАС ПИКА, а facts_1day —
# с максимумом пограничного слоя ЗА СУТКИ. Оговорки едут внутри того же словаря
# фактов, поэтому один payload мог содержать blue_thermals=False рядом со
# строкой «голубая термичка», а карточка в том же ответе печатала «· голубой».

def _blue_disagreement_day():
    """День, на котором старые две формулы расходились.

    Пик температуры в 11:00, пограничный слой там низкий (300 м), а к 15:00
    развит до 2500 м. LCL часа пика ≈ 2318 м: выше слоя в свой час (маркеров
    нет), но ниже суточного максимума — старая формула фактов отвечала «нет».
    """
    temps = [12.0] * 24
    for h, v in ((9, 22.0), (10, 25.0), (11, 27.0), (12, 26.0),
                 (13, 25.0), (14, 24.0), (15, 23.0), (16, 21.0)):
        temps[h] = v
    blh = [300.0] * 24
    blh[15] = 2500.0
    return _full_1d(temperature_2m=temps, boundary_layer_height=blh)


def test_blue_thermals_agrees_with_its_own_caveats(tmp_path):
    data = _blue_disagreement_day()
    facts = engine.facts_1day(data, _site())
    has_caveat = any("голубая термичка" in c for c in facts["caveats"])
    assert facts["blue_thermals"] is has_caveat, (
        f"blue_thermals={facts['blue_thermals']}, а оговорки говорят {has_caveat}")
    assert facts["blue_thermals"] is True


def test_blue_thermals_agrees_with_the_card(tmp_path):
    data = _blue_disagreement_day()
    facts = engine.facts_1day(data, _site())
    _text, _pngs, card = engine.report_1day(data, _site(), str(tmp_path))
    assert facts["blue_thermals"] is ("· голубой" in card)


def test_blue_thermals_needs_the_boundary_layer_series():
    """Модель без пограничного слоя (ECMWF) — «голубого» вердикта не бывает."""
    from fixtures import om_null
    data = om_null(_blue_disagreement_day(), "boundary_layer_height")
    facts = engine.facts_1day(data, _site())
    assert facts["blue_thermals"] is False
    assert not any("голубая термичка" in c for c in facts["caveats"])


def test_facts_name_the_model_that_counted_the_ceiling():
    """Потолок термиков считается ОДНОЙ моделью независимо от выбранной, и
    ответ говорит какой — готовым словом, а не константой, которую читателю
    предлагается знать наизусть.

    Мини-приложение писало «всегда по GFS» в трёх местах разметки при одной
    константе engine.CEILING_MODEL_KEY в домене: смена константы (повод
    реальный — у GFS может пропасть boundary_layer_height) оставила бы пилота
    с подписью «по GFS» под высотой, посчитанной другой моделью (финальное
    ревью ветки, I1).
    """
    facts = engine.facts_1day(_full_1d(), _site())
    assert facts["site"]["ceiling_model"] == engine.model_label(engine.CEILING_MODEL_KEY)
    assert facts["site"]["ceiling_model"] != facts["site"]["model"], (
        "подпись модели прогноза и модель потолка — разные строки")


def test_assessment_says_whether_the_day_is_flyable():
    """Лётность дня решает criteria.FLYABLE, и ответ несёт готовый ответ.

    Копия правила в мини-приложении («не лётно» только у no_fly и danger) уже
    расходилась с доменом на категории marginal: день, который скан считает
    нелётным, вкладка «Неделя» подписывала «лётно» (финальное ревью ветки, I2).
    Категории названы здесь поимённо намеренно — поднимут планку в
    criteria.FLYABLE, и этот тест потребует пересмотреть подписи, а не
    промолчит.
    """
    import criteria

    for category, expected in (("excellent", True), ("fair", True),
                               ("marginal", False), ("no_fly", False)):
        assert criteria.flyable(category) is expected, (
            f"{category}: правило лётности изменилось — пересмотрите подписи в приложении")

    facts = engine.facts_1day(_full_1d(), _site())
    assert facts["assessment"]["flyable"] is criteria.flyable(facts["assessment"]["category"])

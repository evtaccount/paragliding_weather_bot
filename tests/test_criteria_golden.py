"""Золотые кейсы: реалистичные часы → ожидаемая категория и лимитирующий фактор.

Это регрессионная сеть. Любая правка таблицы порогов, весов или штрафов, которая
меняет вердикт по знакомой погоде, падает здесь с конкретным именем кейса — а не
всплывает через месяц как «бот стал странно оценивать вечер».

Балл специально не фиксируется числом (он поедет от любой мелкой правки веса);
фиксируются КАТЕГОРИЯ и то, что именно тянет час вниз.
"""
import pytest

import criteria as c
from fixtures import ideal_hour

# (имя, что поменять, ожидаемая категория, ожидаемый лимит-фактор или None)
CASES = [
    (
        "рабочий полдень: слабый ветер в лоб, потоки 2,5 м/с, база высоко",
        {},
        "ideal", None,
    ),
    (
        "утро в окне: потоки только включаются, база ещё низко",
        dict(w_star=1.4, bl_depth=600.0, thermal_index=-1.5, base_clearance=350.0, spread=2.5),
        "excellent", "base_clearance",
    ),
    (
        "ветреный, но летаемый день: 7 м/с у земли, 10 м/с на 850",
        dict(wind_10m=7.0, wind_925=8.0, wind_850=10.0, gust_factor=1.3, gust_delta=2.2),
        "excellent", "wind_10m",
    ),
    (
        "порывистый пик: отрыв порыва 3,5 м/с при среднем 6",
        dict(wind_10m=6.0, gust_factor=1.5, gust_delta=3.5),
        "fair", "gust_delta",
    ),
    (
        "маргинальный ветер: 8,5 м/с, потоки мощные — плюс мультипликативный штраф",
        dict(wind_10m=8.5, wind_925=9.5, wind_850=11.0, w_star=4.0,
             gust_factor=1.4, gust_delta=3.0),
        "fair", "wind_10m",
    ),
    (
        "боковой ветер к склону: отклонение 50°",
        dict(dir_offset=50.0),
        "marginal", "dir_offset",
    ),
    (
        "подветер: ветер с тыла склона — вето независимо от прочего",
        dict(dir_offset=120.0),
        "danger", "dir_offset",
    ),
    (
        "переразвитие: CAPE 1800 при снятой крышке — вето",
        dict(cape=1800.0, cin=10.0, lifted_index=-3.0, cloud_low=70.0),
        "danger", "cape",
    ),
    (
        "неустойчивость без снятой крышки: CAPE 1800, CIN держит",
        dict(cape=1800.0, cin=120.0, lifted_index=-3.0),
        "fair", "cape",
    ),
    (
        "дождь в этот час — вето",
        dict(precip_mm=0.5, precip_prob=70.0, cloud_low=90.0, visibility=4000.0),
        "danger", "precip_prob",
    ),
    (
        "задавленный день: сплошная низкая облачность, потоки слабые",
        dict(cloud_low=90.0, w_star=1.1, bl_depth=400.0, thermal_index=-0.5,
             spread=1.5, base_clearance=180.0),
        "marginal", "cloud_low",
    ),
    (
        "ветер у земли достиг trim крыла — вето",
        dict(wind_10m=c.TRIM_MS, gust_factor=1.3, gust_delta=3.0),
        "danger", "wind_10m",
    ),
    (
        "сильный сдвиг у земли: 7 м/с между 10 и 100 м — вето",
        dict(shear_100m=7.0),
        "danger", "shear_100m",
    ),
    (
        "туман на старте: видимость 800 м — вето",
        dict(visibility=800.0, cloud_low=95.0, spread=0.5),
        "danger", "visibility",
    ),
    (
        "голубой день: облаков нет, спред большой, потоки резкие",
        dict(cloud_low=0.0, spread=17.0, w_star=3.8, bl_depth=2600.0, thermal_index=-6.5),
        "excellent", "spread",
    ),
    (
        "короткое окно: солнце на склоне всего час",
        dict(window_hours=1.0),
        "ideal", "window_hours",
    ),
]


@pytest.mark.parametrize("name,changes,category,limiting", CASES,
                         ids=[c_[0][:40] for c_ in CASES])
def test_golden_hour(name, changes, category, limiting):
    a = c.score_hour(ideal_hour(**changes), 13)
    assert a.category == category, f"{name}: {a.category} вместо {category} (балл {a.score})"
    assert a.limiting == limiting, f"{name}: лимит-фактор {a.limiting} вместо {limiting}"


def test_one_bad_group_cannot_be_outvoted_by_nine_good_ones():
    """Без потолка по лимитирующему фактору взвешенная сумма десяти групп
    делала «идеальным» день с ветром почти в спину — девять идеальных групп
    перевешивали одну нелётную. Это ровно то, чего пилот не простит."""
    a = c.score_hour(ideal_hour(dir_offset=50.0), 13)      # направление «нелётно» (15)
    assert a.groups["direction"] == c.GRADE_SCORE["no_fly"]
    assert a.category == "marginal", "нелётное направление не должно давать зелёный день"
    # ровно один уровень выше худшей группы, не больше
    assert a.score <= 54


def test_the_cap_lifts_by_exactly_one_level():
    worst_to_category = {
        7.0: "excellent",     # ветер «удовлетворительно» → потолок «отличная»
        8.5: "fair",          # ветер «маргинально»       → потолок «удовлетворительная»
        10.0: "marginal",     # ветер «нелётно»           → потолок «маргинальная»
    }
    for wind, expected in worst_to_category.items():
        a = c.score_hour(ideal_hour(wind_10m=wind), 13)
        assert a.category == expected, f"{wind} м/с → {a.category}, ожидалось {expected}"


def test_minor_groups_do_not_cap_the_day():
    """Стратификация и длительность окна весят 0,02 — документ сам объявил их
    второстепенными, они не должны обрушивать оценку."""
    a = c.score_hour(ideal_hour(window_hours=0.6, spread=0.5), 13)   # оба «плохи»
    assert a.groups["extra"] == c.GRADE_SCORE["marginal"]
    assert a.groups["temp"] == c.GRADE_SCORE["no_fly"]
    assert a.category == "ideal"


def test_veto_always_beats_a_high_weighted_sum():
    """Час, идеальный по всем группам, но с одним вето — всё равно опасный."""
    a = c.score_hour(ideal_hour(precip_mm=0.5), 13)
    assert a.score == 0.0 and a.category == "danger"


def test_scores_are_ordered_the_way_a_pilot_would_order_the_days():
    def s(**kw):
        return c.score_hour(ideal_hour(**kw), 13).score

    calm = s()
    breezy = s(wind_10m=6.0, gust_factor=1.3, gust_delta=2.0)
    windy = s(wind_10m=8.5, wind_925=9.5, gust_factor=1.5, gust_delta=3.5)
    blown = s(wind_10m=10.0, wind_925=11.0, wind_850=13.0, gust_factor=1.6, gust_delta=5.0)
    assert calm > breezy > windy > blown

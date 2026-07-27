# Маршрутный скоринг, спека 2 — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/route` отдаёт балл и категорию маршрута, узкое место, статус выполнимости, границу лётной части, предупреждение о грозе впереди, лучшее время вылета и сравнение с обратным направлением.

**Architecture:** `criteria.py` получает объект `Profile`, в который заворачиваются веса групп, набор параметров, вето и штрафы; `score_hour` принимает его аргументом с дефолтом «старт», равным сегодняшнему поведению. Добавляются пять параметров, три маршрутных вето, свёртка маршрута и упреждающая проверка гроз. `forecast.py` собирает входы критериев из уже интерполированного среза спеки 1 через синтетический одночасовой блок и существующую `engine.derive_hour`, затем сканирует времена вылета и обратное направление по тем же данным. `route.py` разворачивает маршрут и рисует расширенную карточку.

**Tech Stack:** Python 3.10, pytest (`asyncio_mode = auto`). Новых зависимостей нет.

**Спека:** `docs/superpowers/specs/2026-07-27-route-scoring-design.md`

## Global Constraints

- **Существующее поведение не меняется.** Профиль «старт» — сегодняшние веса, параметры и вето. Все 416 тестов остаются зелёными, `/today` и обзоры считают то же самое. На это есть отдельный тест-предохранитель (задача 1).
- Пороги живут только в `criteria.py`. Числа, которые сейчас лежат в `route.py` (`MIN_GROUND_SPEED_KMH`, `MIN_WORKING_ALT_AGL`), переезжают туда и в `route.py` остаются псевдонимами.
- `criteria.py` **не импортирует** `route.py` и `forecast.py` — зависимость строго в одну сторону, иначе получится цикл.
- Вето на точке не обнуляет маршрут: оно даёт статус «обрывается на N-м км».
- Скан времени вылета и обратное направление не делают **ни одного** нового запроса к API. На это есть тест со счётчиком обращений.
- Тесты: `.venv/bin/python -m pytest -q`, прогонять с `set -o pipefail` — иначе код возврата теряется в конвейере.
- Коммит после каждой задачи, ветка `feature/route-scoring`.

## File Structure

| Файл | Что меняется |
|---|---|
| `criteria.py` | `Profile`, параметризация `score_hour`, пять новых параметров, `ROUTE_GROUPS`, три профиля, три маршрутных вето, `score_route`, `storm_ahead`, `reference_text(profile)` |
| `route.py` | `reverse_samples`, расширенная `render_card`, псевдонимы порогов |
| `forecast.py` | сборка входов критериев, скоринг точек, скан вылета, обратное направление |
| `tests/test_criteria_profiles.py` | новый: предохранитель, профили, вето по профилям |
| `tests/test_criteria_route_params.py` | новый: шкалы новых параметров |
| `tests/test_criteria_route_score.py` | новый: свёртка, статус, граница лётной части, гроза впереди |
| `tests/test_route_reverse.py` | новый: разворот маршрута |
| `tests/test_route_scored.py` | новый: скоринг точек и скан вылета в `forecast` |
| `tests/test_route_card.py` | дополняется: вердикт, узкое место, лучший вылет |
| `tests/test_criteria_bands.py` | инвариант весов проверяется по профилям |

---

### Task 1: Профиль как объект и параметризация score_hour

**Files:**
- Modify: `criteria.py`
- Test: `tests/test_criteria_profiles.py`

**Interfaces:**
- Consumes: существующие `GROUPS`, `PARAMS`, `VETOES`, `PENALTIES`
- Produces: `Profile(key, label, groups, params, vetoes, penalties)` с методом `group_params(gkey)`; `TAKEOFF`; `score_hour(raw, hour=0, profile=TAKEOFF)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_criteria_profiles.py
"""Профили критериев: предохранитель поведения и разделение по ролям точки."""
import pytest

import criteria as c
from fixtures import ideal_hour

# Эталон снят с реализации ДО рефакторинга. Если хоть одно число здесь поедет,
# значит профиль «старт» перестал быть сегодняшним поведением, а это ломает
# /today, обзоры и /scan молча.
GOLDEN = {
    "ideal":     ({}, 100.0, "ideal", None, 1.0, 0),
    "windy":     ({"wind_10m": 8.0, "wind_925": 9.5}, 69, "fair", "wind_10m", 1.0, 0),
    "gusty":     ({"gust_factor": 1.5, "gust_delta": 3.8}, 69, "fair", "gust_delta", 1.0, 0),
    "offslope":  ({"dir_offset": 50.0}, 54, "marginal", "dir_offset", 1.0, 0),
    "stormy":    ({"cape": 1200.0, "lifted_index": -3.0}, 69, "fair", "lifted_index", 1.0, 0),
    "thin_data": ({"w_star": None, "bl_depth": None, "thermal_index": None,
                   "visibility": None, "shear_100m": None, "cape": None},
                  100.0, "ideal", None, 0.7, 4),
}


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_default_profile_reproduces_pre_refactor_behaviour(name):
    over, score, cat, lim, conf, unchecked = GOLDEN[name]
    a = c.score_hour(ideal_hour(**over), 13)
    assert a.score == score
    assert a.category == cat
    assert a.limiting == lim
    assert a.confidence == conf
    assert len(a.unchecked_vetoes) == unchecked


def test_explicit_takeoff_profile_equals_the_default():
    raw = ideal_hour(wind_10m=8.0)
    assert c.score_hour(raw, 13).score == c.score_hour(raw, 13, profile=c.TAKEOFF).score


def test_takeoff_profile_keeps_every_launch_veto():
    """Утверждения намеренно сформулированы так, чтобы пережить добавление
    маршрутных параметров и вето в задачах 2 и 4."""
    launch_only = {"lee_side", "base_below_route", "wind_launch", "gust_factor",
                   "gust_delta", "shear"}
    assert c.TAKEOFF.groups == c.GROUPS
    assert launch_only <= set(c.TAKEOFF.vetoes)
    assert "dir_offset" in c.TAKEOFF.params


def test_group_params_filters_by_profile():
    assert set(c.TAKEOFF.group_params("wind")) == {"wind_10m", "wind_925", "wind_850"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_criteria_profiles.py -q`
Expected: FAIL — `AttributeError: module 'criteria' has no attribute 'TAKEOFF'`

- [ ] **Step 3: Write minimal implementation**

В `criteria.py` сразу после `PENALTIES` добавить:

```python
@dataclass(frozen=True)
class Profile:
    """Роль точки определяет, по каким критериям её оценивать.

    У точки в воздухе нет склона, поэтому спрашивать «совпадает ли ветер с
    направлением склона» там бессмысленно; на финише наоборот снова важны
    приземный ветер и порывы — это посадка. Веса, набор параметров, вето и
    штрафы едут вместе, потому что менять их поодиночке нельзя: выкинутая
    группа без перенормировки весов тихо занижает балл.
    """
    key: str
    label: str
    groups: dict
    params: tuple
    vetoes: tuple
    penalties: tuple

    def group_params(self, gkey):
        return tuple(k for k in self.params if PARAMS[k].group == gkey)


TAKEOFF = Profile("takeoff", "старт", GROUPS, tuple(PARAMS),
                  tuple(r.key for r in VETOES), tuple(r.key for r in PENALTIES))
```

Заменить тело `score_hour` и `_present_share` на профильные версии:

```python
def _present_share(a, group_key, profile):
    """Доля параметров группы, у которых были данные."""
    keys = profile.group_params(group_key)
    return sum(1 for k in keys if k in a.subs) / len(keys) if keys else 0.0


def score_hour(raw, hour=0, profile=TAKEOFF):
    """Оценить один час по профилю роли точки. `raw` — плоский словарь.

    Дефолт — профиль старта: он равен поведению до появления профилей, поэтому
    все существующие вызовы считают ровно то же самое.
    """
    a = HourAssessment(hour=hour, score=None, category=NO_DATA[0],
                       emoji=NO_DATA[1], label=NO_DATA[2], raw=dict(raw))

    for key in profile.params:
        p = PARAMS[key]
        g = p.grade(raw.get(key))
        if g is None:
            a.warnings.append(f"no_data:{key}")
            continue
        a.grades[key] = g
        a.subs[key] = GRADE_SCORE[g]

    for gkey, group in profile.groups.items():
        vals = [a.subs[k] for k in profile.group_params(gkey) if k in a.subs]
        if not vals:
            continue
        a.groups[gkey] = min(vals) if group.agg == "min" else sum(vals) / len(vals)

    if "storms" in a.groups and _ge(raw.get("cape"), 1500) and raw.get("cin") is None:
        a.groups["storms"] = min(a.groups["storms"], GRADE_SCORE["marginal"])

    if not a.groups:
        return a

    total_w = sum(profile.groups[g].weight for g in a.groups)
    score = sum(profile.groups[g].weight * v for g, v in a.groups.items()) / total_w
    a.confidence = round(sum(
        profile.groups[g].weight * _present_share(a, g, profile) for g in a.groups), 3)
    a.weighted = round(score, 1)

    if a.subs and min(a.subs.values()) < GRADE_SCORE["ideal"]:
        lim = min(a.subs, key=lambda k: (a.subs[k], k))
        a.limiting, a.limiting_label = lim, PARAMS[lim].label

    for rule in PENALTIES:
        if rule.key not in profile.penalties:
            continue
        if any(raw.get(n) is None for n in rule.needs):
            continue
        if rule.test(raw):
            score *= rule.factor
            a.penalties.append(rule.key)

    heavy = [v for g, v in a.groups.items()
             if profile.groups[g].weight >= LIMIT_CAP_MIN_WEIGHT]
    if heavy:
        capped = _cap(score, _one_level_up(_grade_of_score(min(heavy))))
        a.capped = capped < score
        score = capped

    for rule in VETOES:
        if rule.key not in profile.vetoes:
            continue
        if any(raw.get(n) is None for n in rule.needs):
            a.unchecked_vetoes.append(rule.key)
            continue
        if rule.test(raw):
            a.vetoes.append(rule.key)
    if a.vetoes:
        score = 0.0
    elif a.confidence < MIN_CONFIDENCE:
        score = _cap(score, "fair")
        a.warnings.append("low_confidence")

    a.score = round(score, 1)
    a.category, a.emoji, a.label = category_of(a.score)
    return a
```

Обрати внимание: `confidence` в профиле старта считается по той же формуле, что и
раньше, потому что `profile.groups` там — тот же `GROUPS`, а `group_params` даёт тот же
набор ключей. Если эталонные числа в тесте поедут, ошибка именно здесь.

- [ ] **Step 4: Run test to verify it passes**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_criteria_profiles.py -q && .venv/bin/python -m pytest -q`
Expected: PASS, 9 passed в файле; весь набор — 425 passed

- [ ] **Step 5: Commit**

```bash
git add criteria.py tests/test_criteria_profiles.py
git commit -m "refactor(criteria): профиль роли точки как аргумент score_hour"
```

---

### Task 2: Маршрутные параметры и их шкалы

**Files:**
- Modify: `criteria.py`
- Test: `tests/test_criteria_route_params.py`

**Interfaces:**
- Consumes: `Param`, `Group` из задачи 1
- Produces: параметры `wind_along`, `wind_cross`, `working_band`, `time_margin`, `wind_working`; группы `ROUTE_GROUPS`; константы `MIN_GROUND_SPEED_KMH = 8.0`, `MIN_WORKING_ALT_AGL = 300`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_criteria_route_params.py
"""Шкалы маршрутных параметров."""
import pytest

import criteria as c


@pytest.mark.parametrize("value,grade", [
    (14, "ideal"), (8, "ideal"), (19.9, "ideal"),
    (4, "excellent"), (0, "excellent"), (24, "excellent"),
    (-4, "fair"), (30, "fair"),
    (-10, "marginal"),
    (-20, "no_fly"),
    (-30, "danger"),
])
def test_wind_along_scale(value, grade):
    assert c.grade_of("wind_along", value) == grade


def test_wind_along_is_asymmetric():
    """Попутный +14 — подарок, встречный −14 растягивает маршрут."""
    assert c.grade_of("wind_along", 14) == "ideal"
    assert c.grade_of("wind_along", -14) == "marginal"


@pytest.mark.parametrize("value,grade", [
    (5, "ideal"), (12, "excellent"), (20, "fair"),
    (30, "marginal"), (40, "no_fly"), (50, "danger"),
])
def test_wind_cross_scale(value, grade):
    assert c.grade_of("wind_cross", value) == grade


@pytest.mark.parametrize("value,grade", [
    (1500, "ideal"), (800, "excellent"), (400, "fair"),
    (200, "marginal"), (100, "no_fly"), (-50, "danger"),
])
def test_working_band_scale(value, grade):
    assert c.grade_of("working_band", value) == grade


@pytest.mark.parametrize("value,grade", [
    (200, "ideal"), (150, "excellent"), (90, "fair"),
    (30, "marginal"), (10, "no_fly"), (-15, "danger"),
])
def test_time_margin_scale(value, grade):
    assert c.grade_of("time_margin", value) == grade


def test_wind_working_reuses_the_aloft_scale():
    """Ветер на рабочей высоте — та же физика, что на 850 гПа: шкала берётся
    ссылкой, а не копией чисел."""
    assert c.PARAMS["wind_working"].bands is c.PARAMS["wind_850"].bands


def test_route_group_weights_sum_to_one():
    assert abs(sum(g.weight for g in c.ROUTE_GROUPS.values()) - 1.0) < 1e-9


def test_thresholds_moved_out_of_route_module():
    import route
    assert route.MIN_GROUND_SPEED_KMH is c.MIN_GROUND_SPEED_KMH
    assert route.MIN_WORKING_ALT_AGL is c.MIN_WORKING_ALT_AGL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_criteria_route_params.py -q`
Expected: FAIL — `KeyError: 'wind_along'`

- [ ] **Step 3: Write minimal implementation**

В `criteria.py` рядом с остальными порогами добавить:

```python
MIN_GROUND_SPEED_KMH = 8.0   # ниже этой путевой маршрут практически не идётся
MIN_WORKING_ALT_AGL = 300    # ниже пилот не идёт на переход, а ищет площадку
```

Вынести таблицу уровней ветра на высоте в константу перед `PARAMS`, чтобы её могли
разделить два параметра:

```python
# Шкала ветра на высоте. Общая для 850 гПа и для среднего ветра рабочего слоя:
# это одна и та же физика на близких высотах, и две копии чисел разъехались бы.
_WIND_ALOFT_BANDS = (
    ("ideal",     ((None, 6.1),)),
    ("excellent", ((6.1, 8.3),)),
    ("fair",      ((8.3, 10.6),)),
    ("marginal",  ((10.6, 12.5),)),
    ("no_fly",    ((12.5, 13.9),)),
    ("danger",    ((13.9, None),)),
)
```

Заменить литеральную таблицу у `Param("wind_850", ...)` на `_WIND_ALOFT_BANDS` — числа
те же, существующие тесты это подтвердят. Затем добавить в `PARAMS` пять параметров:

```python
    # --- маршрутные параметры -------------------------------------------------
    # Шкала асимметрична намеренно: сильный попутный — подарок, сильный встречный
    # растягивает маршрут и закрывает окно раньше, чем пилот долетит. Уровень
    # «опасно» ниже −25 км/ч: при воздушной 25 км/ч это отрицательная путевая.
    Param("wind_along", "wind_along", "ветер вдоль курса", "км/ч", (
        ("danger",    ((None, -25),)),
        ("no_fly",    ((-25, -15),)),
        ("marginal",  ((-15, -8),)),
        ("fair",      ((-8, 0), (28, None))),
        ("excellent", ((0, 8), (20, 28))),
        ("ideal",     ((8, 20),)),
    ), fmt="{:+.0f}"),
    # Значение подаётся ПО МОДУЛЮ: снос вправо и влево одинаково требует крабинга.
    # «Опасно» с 45 км/ч — заметно выше воздушной скорости, курс не удержать.
    Param("wind_cross", "wind_cross", "снос поперёк курса", "км/ч", (
        ("ideal",     ((None, 10),)),
        ("excellent", ((10, 18),)),
        ("fair",      ((18, 26),)),
        ("marginal",  ((26, 34),)),
        ("no_fly",    ((34, 45),)),
        ("danger",    ((45, None),)),
    ), fmt="{:.0f}"),
    Param("working_band", "working_band", "рабочий диапазон высот", "м", (
        ("danger",    ((None, 0),)),
        ("no_fly",    ((0, 150),)),
        ("marginal",  ((150, 300),)),
        ("fair",      ((300, 600),)),
        ("excellent", ((600, 1200),)),
        ("ideal",     ((1200, None),)),
    ), fmt="{:.0f}"),
    Param("time_margin", "extra", "запас времени до закрытия окна", "мин", (
        ("danger",    ((None, 0),)),
        ("no_fly",    ((0, 20),)),
        ("marginal",  ((20, 60),)),
        ("fair",      ((60, 120),)),
        ("excellent", ((120, 180),)),
        ("ideal",     ((180, None),)),
    ), fmt="{:.0f}"),
    Param("wind_working", "wind_abs", "ветер на рабочей высоте", "м/с",
          _WIND_ALOFT_BANDS),
```

После `GROUPS` добавить таблицу весов маршрутного профиля:

```python
# Веса маршрутного профиля. Направление к склону и порывы у земли ушли совсем —
# их место заняли ветер вдоль курса, рабочий диапазон высот и увеличенный вес гроз.
# Это и есть содержательная разница между «стою на старте» и «лечу».
ROUTE_GROUPS = {g.key: g for g in (
    Group("wind_along",   0.20, "ветер вдоль курса"),
    Group("thermals",     0.18, "термичка", agg="mean"),
    Group("working_band", 0.16, "рабочий диапазон высот"),
    Group("storms",       0.16, "неустойчивость/грозы"),
    Group("wind_abs",     0.10, "ветер на рабочей высоте"),
    Group("precip_vis",   0.08, "осадки и видимость"),
    Group("cloud",        0.06, "облачность"),
    Group("wind_cross",   0.04, "снос поперёк курса"),
    Group("extra",        0.02, "окно и запас времени"),
)}
```

Обновить `_check_table`: группа параметра проверяется по объединению таблиц, а сумма
весов — по каждой таблице отдельно.

```python
    for table, name in ((GROUPS, "GROUPS"), (ROUTE_GROUPS, "ROUTE_GROUPS")):
        w = sum(g.weight for g in table.values())
        assert abs(w - 1.0) < 1e-9, f"сумма весов {name} = {w}, должна быть 1.0"
    known_groups = set(GROUPS) | set(ROUTE_GROUPS)
    ...
        assert p.group in known_groups, f"{p.key}: неизвестная группа {p.group}"
```

В `route.py` заменить собственные константы псевдонимами:

```python
MIN_WORKING_ALT_AGL = criteria.MIN_WORKING_ALT_AGL  # пороги живут в criteria.py
MIN_GROUND_SPEED_KMH = criteria.MIN_GROUND_SPEED_KMH
```

- [ ] **Step 4: Run test to verify it passes**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_criteria_route_params.py -q && .venv/bin/python -m pytest -q`
Expected: PASS. Существующий `tests/test_criteria_bands.py` параметризован по всем `PARAMS` и теперь проверит покрытие оси у новых параметров тоже.

Если упадёт `test_every_group_has_at_least_one_parameter` — он обходит только `GROUPS`, а новые группы лежат в `ROUTE_GROUPS`; расширь его на объединение таблиц.

- [ ] **Step 5: Commit**

```bash
git add criteria.py route.py tests/test_criteria_route_params.py tests/test_criteria_bands.py
git commit -m "feat(criteria): маршрутные параметры и веса маршрутного профиля"
```

---

### Task 3: Три профиля и вето по ролям

**Files:**
- Modify: `criteria.py`
- Test: `tests/test_criteria_profiles.py` (дополняется)

**Interfaces:**
- Consumes: `Profile`, `ROUTE_GROUPS`, новые параметры
- Produces: `TAKEOFF`, `ENROUTE`, `GOAL`, `PROFILES` (ключ → профиль)

- [ ] **Step 1: Write the failing test**

Дописать в `tests/test_criteria_profiles.py`:

```python
def route_raw(**over):
    """Минимальный набор входов для маршрутной точки — всё идеально."""
    raw = {"wind_along": 12.0, "wind_cross": 5.0, "working_band": 1500.0,
           "time_margin": 200.0, "wind_working": 4.0,
           "w_star": 2.5, "bl_depth": 1500.0, "thermal_index": -4.0,
           "cape": 200.0, "lifted_index": 3.0, "cloud_low": 20.0,
           "precip_prob": 0.0, "visibility": 30000.0, "window_hours": 6.0,
           "precip_mm": 0.0, "cin": 100.0, "wind_at_base": 4.0,
           "ground_speed": 30.0, "dir_misalign": 10.0}
    raw.update(over)
    return raw


def test_all_three_profiles_are_registered():
    assert set(c.PROFILES) == {"takeoff", "enroute", "goal"}


def test_slope_direction_does_not_affect_an_enroute_point():
    """В воздухе склона нет — отклонение ветра от него не должно значить ничего."""
    good = c.score_hour(route_raw(dir_offset=5.0), 13, profile=c.ENROUTE)
    bad = c.score_hour(route_raw(dir_offset=80.0), 13, profile=c.ENROUTE)
    assert good.score == bad.score


def test_ground_wind_does_not_affect_an_enroute_point_but_does_at_goal():
    calm = c.score_hour(route_raw(wind_10m=2.0), 13, profile=c.ENROUTE)
    blown = c.score_hour(route_raw(wind_10m=9.0), 13, profile=c.ENROUTE)
    assert calm.score == blown.score


def test_lee_side_veto_fires_only_at_takeoff():
    from fixtures import ideal_hour
    raw = ideal_hour(dir_offset=100.0)
    assert "lee_side" in c.score_hour(raw, 13, profile=c.TAKEOFF).vetoes
    assert "lee_side" not in c.score_hour(raw, 13, profile=c.GOAL).vetoes


def test_working_altitude_wind_veto_fires_in_all_three_profiles():
    """Отступление от ТЗ: на маршруте пилот в том же воздухе, что и над стартом."""
    from fixtures import ideal_hour
    for profile in (c.TAKEOFF, c.GOAL):
        a = c.score_hour(ideal_hour(wind_at_base=c.TRIM_MS + 1), 13, profile=profile)
        assert "wind_base" in a.vetoes
    a = c.score_hour(route_raw(wind_at_base=c.TRIM_MS + 1), 13, profile=c.ENROUTE)
    assert "wind_base" in a.vetoes


def test_goal_profile_is_takeoff_without_the_direction_group():
    assert set(c.GOAL.groups) == set(c.GROUPS) - {"direction"}
    assert "dir_offset" not in c.GOAL.params
    assert "time_margin" in c.GOAL.params


def test_enroute_profile_has_no_ground_parameters():
    for key in ("wind_10m", "gust_factor", "gust_delta", "dir_offset", "shear_100m"):
        assert key not in c.ENROUTE.params
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_criteria_profiles.py -q`
Expected: FAIL — `AttributeError: module 'criteria' has no attribute 'ENROUTE'`

- [ ] **Step 3: Write minimal implementation**

Заменить одиночное определение `TAKEOFF` из задачи 1 на три профиля:

```python
_LAUNCH_PARAMS = ("wind_10m", "wind_925", "wind_850", "gust_factor", "gust_delta",
                  "dir_offset", "w_star", "bl_depth", "thermal_index", "cape",
                  "lifted_index", "cloud_low", "base_clearance", "precip_prob",
                  "visibility", "shear_100m", "spread", "window_hours")

_ENROUTE_PARAMS = ("wind_along", "wind_cross", "working_band", "wind_working",
                   "w_star", "bl_depth", "thermal_index", "cape", "lifted_index",
                   "cloud_low", "precip_prob", "visibility", "window_hours",
                   "time_margin")

# Вето, применимые везде: погода не спрашивает, стоишь ты или летишь.
_COMMON_VETOES = ("precip_hour", "precip_prob", "cape_extreme", "cape_cin",
                  "lifted_index", "visibility", "wind_base")
# Вето про близость к земле — старт и посадка.
_GROUND_VETOES = ("wind_launch", "gust_factor", "gust_delta", "shear")
# Вето, осмысленные только на старте.
_LAUNCH_ONLY_VETOES = ("lee_side", "base_below_route")
_ROUTE_VETOES = ("route_terrain_block", "route_no_progress", "route_window_closed")

_ALL_PENALTIES = tuple(r.key for r in PENALTIES)

TAKEOFF = Profile(
    "takeoff", "старт", GROUPS, _LAUNCH_PARAMS,
    _COMMON_VETOES + _GROUND_VETOES + _LAUNCH_ONLY_VETOES, _ALL_PENALTIES)

# Финиш — это посадка: приземный ветер и порывы снова важны, направление склона нет.
# Веса не перенормируются вручную: score_hour делит на сумму выживших групп сам.
GOAL = Profile(
    "goal", "финиш",
    {k: g for k, g in GROUPS.items() if k != "direction"},
    tuple(k for k in _LAUNCH_PARAMS if k != "dir_offset") + ("time_margin",),
    _COMMON_VETOES + _GROUND_VETOES, _ALL_PENALTIES)

# На маршруте из штрафов остаётся только расхождение направления по высотам.
# Два других завязаны на приземный ветер и запас под базой; выдумывать для них
# маршрутные аналоги значило бы калибровать без источника.
ENROUTE = Profile(
    "enroute", "маршрут", ROUTE_GROUPS, _ENROUTE_PARAMS,
    _COMMON_VETOES + _ROUTE_VETOES, ("dir_misalign",))

PROFILES = {p.key: p for p in (TAKEOFF, ENROUTE, GOAL)}
```

Проверь, что `_LAUNCH_PARAMS` перечисляет ровно те 18 ключей, что были в `PARAMS` до
задачи 2, — иначе профиль старта тихо потеряет критерий, а предохранитель это поймает
только если потерянный критерий влиял на эталонные случаи.

- [ ] **Step 4: Run test to verify it passes**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_criteria_profiles.py -q && .venv/bin/python -m pytest -q`
Expected: PASS; предохранитель из задачи 1 остаётся зелёным

- [ ] **Step 5: Commit**

```bash
git add criteria.py tests/test_criteria_profiles.py
git commit -m "feat(criteria): профили старта, маршрута и финиша"
```

---

### Task 4: Три маршрутных вето

**Files:**
- Modify: `criteria.py`
- Test: `tests/test_criteria_profiles.py` (дополняется)

**Interfaces:**
- Consumes: `Rule`, `MIN_GROUND_SPEED_KMH`
- Produces: правила `route_terrain_block`, `route_no_progress`, `route_window_closed` в `VETOES`

- [ ] **Step 1: Write the failing test**

```python
def test_route_terrain_block_veto():
    a = c.score_hour(route_raw(working_band=-50.0), 13, profile=c.ENROUTE)
    assert "route_terrain_block" in a.vetoes
    assert a.score == 0


def test_route_no_progress_veto():
    a = c.score_hour(route_raw(ground_speed=8.0), 13, profile=c.ENROUTE)
    assert "route_no_progress" in a.vetoes


def test_route_window_closed_veto():
    a = c.score_hour(route_raw(time_margin=-5.0), 13, profile=c.ENROUTE)
    assert "route_window_closed" in a.vetoes


def test_route_vetoes_do_not_fire_at_takeoff():
    from fixtures import ideal_hour
    a = c.score_hour(ideal_hour(working_band=-50.0, ground_speed=2.0), 13)
    assert not a.vetoes


def test_route_veto_is_unchecked_when_its_input_is_missing():
    a = c.score_hour(route_raw(working_band=None), 13, profile=c.ENROUTE)
    assert "route_terrain_block" in a.unchecked_vetoes
    assert "route_terrain_block" not in a.vetoes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_criteria_profiles.py -q -k route_`
Expected: FAIL — вето не срабатывает, `a.vetoes` пуст

- [ ] **Step 3: Write minimal implementation**

Добавить в конец кортежа `VETOES`:

```python
    # --- маршрутные вето ------------------------------------------------------
    # Срабатывают только в профиле маршрута и НЕ обнуляют весь маршрут: свёртка
    # переводит его в состояние «обрывается на N-м км» с указанием километра.
    Rule("route_terrain_block", "база ниже безопасной высоты над рельефом",
         ("working_band",), lambda r: r["working_band"] <= 0),
    Rule("route_no_progress", f"эффективная путевая ≤ {MIN_GROUND_SPEED_KMH:.0f} км/ч",
         ("ground_speed",), lambda r: r["ground_speed"] <= MIN_GROUND_SPEED_KMH),
    Rule("route_window_closed", "прилёт после закрытия термического окна",
         ("time_margin",), lambda r: r["time_margin"] < 0),
```

`ground_speed` — вход правила без собственной шкалы, как уже сделано для `precip_mm`,
`cin` и `wind_at_base`: в `PARAMS` его нет, он приходит в `raw` из слоя маршрута.

- [ ] **Step 4: Run test to verify it passes**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_criteria_profiles.py -q && .venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add criteria.py tests/test_criteria_profiles.py
git commit -m "feat(criteria): три маршрутных вето"
```

---

### Task 5: Свёртка маршрута и статус выполнимости

**Files:**
- Modify: `criteria.py`
- Test: `tests/test_criteria_route_score.py`

**Interfaces:**
- Consumes: `HourAssessment`, `category_of`, `MIN_CONFIDENCE`
- Produces: `RouteAssessment`; `score_route(points) -> RouteAssessment`; константы `BOTTLENECK_WEIGHT = 0.6`, `TOO_SLOW_MARGIN_MIN = 20.0`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_criteria_route_score.py
"""Свёртка маршрута: узкое место, статус выполнимости, граница лётной части."""
import pytest

import criteria as c


def pt(km, score, leg=10.0, vetoes=(), confidence=1.0, time_margin=200.0):
    """Точка с заранее заданной оценкой — свёртка не должна знать, откуда она."""
    a = c.HourAssessment(hour=13, score=score, category="fair", emoji="🟡", label="ок",
                         confidence=confidence, raw={"time_margin": time_margin})
    a.vetoes = list(vetoes)
    return {"km": km, "leg_length_km": leg, "assessment": a}


def test_formula_is_bottleneck_plus_weighted_mean():
    points = [pt(0, 80), pt(10, 80), pt(20, 40)]
    r = c.score_route(points)
    assert r.score == pytest.approx(0.6 * 40 + 0.4 * (80 + 80 + 40) / 3)


def test_mean_is_weighted_by_leg_length_not_by_point_count():
    short = c.score_route([pt(0, 100, leg=1.0), pt(10, 40, leg=99.0)])
    long = c.score_route([pt(0, 100, leg=99.0), pt(10, 40, leg=1.0)])
    assert long.score > short.score


def test_one_bad_point_does_not_make_the_day_excellent():
    points = [pt(i * 10, 90) for i in range(9)] + [pt(90, 20)]
    r = c.score_route(points)
    assert r.category not in ("ideal", "excellent")


def test_one_bad_point_does_not_zero_the_route():
    points = [pt(i * 10, 90) for i in range(9)] + [pt(90, 0, vetoes=["route_terrain_block"])]
    r = c.score_route(points)
    assert r.score > 0


def test_feasibility_blocked_names_kilometre_and_reason():
    points = [pt(0, 90), pt(10, 0, vetoes=["route_terrain_block"]), pt(20, 90)]
    r = c.score_route(points)
    assert r.feasibility == "blocked_at_km"
    assert r.blocked_at_km == 10
    assert r.blocked_reason == "route_terrain_block"


def test_feasibility_cannot_be_completable_with_a_veto():
    """Ошибка в сторону оптимизма — самая опасная из возможных."""
    points = [pt(0, 90), pt(10, 0, vetoes=["route_no_progress"])]
    assert c.score_route(points).feasibility != "completable"


def test_flyable_until_is_the_last_point_before_the_veto():
    points = [pt(0, 90), pt(10, 90), pt(20, 0, vetoes=["route_terrain_block"]), pt(30, 90)]
    assert c.score_route(points).flyable_until_km == 10


def test_flyable_until_is_the_whole_route_when_nothing_blocks():
    points = [pt(0, 90), pt(10, 90), pt(20, 90)]
    assert c.score_route(points).flyable_until_km == 20


def test_too_slow_when_the_goal_has_almost_no_margin():
    points = [pt(0, 90), pt(10, 90, time_margin=5.0)]
    r = c.score_route(points)
    assert r.feasibility == "too_slow"


def test_unknown_when_data_is_thin():
    points = [pt(0, 90), pt(10, 90, confidence=0.4)]
    assert c.score_route(points).feasibility == "unknown"


def test_points_without_a_score_do_not_enter_the_mean():
    points = [pt(0, 90), pt(10, None), pt(20, 90)]
    r = c.score_route(points)
    assert r.score == pytest.approx(90.0)
    assert r.feasibility == "unknown"


def test_all_points_without_a_score():
    r = c.score_route([pt(0, None), pt(10, None)])
    assert r.score is None
    assert r.feasibility == "unknown"


def test_bottleneck_reports_the_worst_point():
    points = [pt(0, 90), pt(10, 48), pt(20, 70)]
    b = c.score_route(points).bottleneck
    assert b["km"] == 10 and b["score"] == 48
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_criteria_route_score.py -q`
Expected: FAIL — `AttributeError: module 'criteria' has no attribute 'score_route'`

- [ ] **Step 3: Write minimal implementation**

```python
# Свёртка маршрута. Коэффициент из ТЗ: маршрут — цепь и рвётся по слабому звену,
# но одна плохая точка не должна обнулять хороший день. Величина компромиссная,
# измерений под ней нет.
BOTTLENECK_WEIGHT = 0.6
TOO_SLOW_MARGIN_MIN = 20.0
# С какого выигрыша в баллах обратный маршрут стоит отдельной строки. Порог
# подобран так, чтобы строка не появлялась на шуме округления; измерений нет.
REVERSE_GAIN = 12.0


@dataclass
class RouteAssessment:
    score: float | None
    category: str
    emoji: str
    label: str
    feasibility: str                     # completable | blocked_at_km | too_slow | unknown
    bottleneck: dict | None = None       # {"km", "score", "reason"}
    blocked_at_km: float | None = None
    blocked_reason: str | None = None
    flyable_until_km: float | None = None
    mean_score: float | None = None
    confidence: float = 0.0
    warnings: list = field(default_factory=list)


def score_route(points):
    """Точки маршрута → оценка маршрута.

    `points` — [{"km", "leg_length_km", "assessment"}]. Свёртка намеренно ничего
    не знает о том, откуда взялись оценки: её тестируют на заранее заданных баллах.

    Вето на точке НЕ обнуляет маршрут — оно переводит его в «обрывается на N-м км».
    Пилоту важно знать, что 60 км из 80 проходятся отлично: тогда маршрут
    перекраивают, а не отменяют день.
    """
    blocked = next((p for p in points if p["assessment"].vetoes), None)
    scored = [p for p in points if p["assessment"].score is not None]
    thin = (len(scored) != len(points)
            or any(p["assessment"].confidence < MIN_CONFIDENCE for p in points))

    if not scored:
        return RouteAssessment(None, *NO_DATA, feasibility="unknown",
                               flyable_until_km=_flyable_until(points, blocked))

    worst = min(scored, key=lambda p: p["assessment"].score)
    total = sum(p["leg_length_km"] for p in scored) or 1.0
    mean = sum(p["assessment"].score * p["leg_length_km"] for p in scored) / total
    score = BOTTLENECK_WEIGHT * worst["assessment"].score + (1 - BOTTLENECK_WEIGHT) * mean

    if blocked is not None:
        feasibility = "blocked_at_km"
    elif _goal_margin(points) is not None and _goal_margin(points) < TOO_SLOW_MARGIN_MIN:
        feasibility = "too_slow"
    elif thin:
        feasibility = "unknown"
    else:
        feasibility = "completable"

    cat, emoji, label = category_of(score)
    return RouteAssessment(
        score=round(score, 1), category=cat, emoji=emoji, label=label,
        feasibility=feasibility,
        bottleneck={"km": worst["km"], "score": round(worst["assessment"].score),
                    "reason": worst["assessment"].limiting},
        blocked_at_km=None if blocked is None else blocked["km"],
        blocked_reason=None if blocked is None else blocked["assessment"].vetoes[0],
        flyable_until_km=_flyable_until(points, blocked),
        mean_score=round(mean, 1),
        confidence=round(min(p["assessment"].confidence for p in points), 3))


def _goal_margin(points):
    return points[-1]["assessment"].raw.get("time_margin") if points else None


def _flyable_until(points, blocked):
    """Километр последней точки перед первым вето — ради этого вето и не обнуляет
    весь маршрут."""
    if not points:
        return None
    if blocked is None:
        return points[-1]["km"]
    # сравнение по идентичности, а не через .index: две точки с одинаковым
    # содержимым равны по ==, и километр уехал бы на первую попавшуюся
    i = next(k for k, p in enumerate(points) if p is blocked)
    return points[i - 1]["km"] if i else 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_criteria_route_score.py -q`
Expected: PASS, 13 passed

- [ ] **Step 5: Commit**

```bash
git add criteria.py tests/test_criteria_route_score.py
git commit -m "feat(criteria): свёртка маршрута и статус выполнимости"
```

---

### Task 6: Упреждающая проверка гроз

**Files:**
- Modify: `criteria.py`
- Test: `tests/test_criteria_route_score.py` (дополняется)

**Interfaces:**
- Consumes: `HourAssessment.vetoes`
- Produces: `storm_ahead(points, lookahead_km=STORM_LOOKAHEAD_KM) -> list[dict | None]`; константы `STORM_VETOES`, `STORM_LOOKAHEAD_KM = 60.0`

- [ ] **Step 1: Write the failing test**

```python
def stormy(km, leg=10.0, eta="14:20"):
    p = pt(km, 0, leg=leg, vetoes=["cape_cin"])
    p["eta"] = eta
    return p


def test_warning_appears_on_approach_not_only_at_the_cell():
    points = [pt(0, 90), pt(20, 90), pt(40, 90), stormy(60)]
    for p in points:
        p.setdefault("eta", "12:00")
    ahead = c.storm_ahead(points)
    assert ahead[0] is None                     # 60 км от старта — вне горизонта
    assert ahead[1] == {"km": 60, "eta": "14:20"}
    assert ahead[2] == {"km": 60, "eta": "14:20"}


def test_nothing_beyond_the_lookahead_horizon():
    points = [pt(0, 90), stormy(70)]
    points[0]["eta"] = "12:00"
    assert c.storm_ahead(points)[0] is None


def test_only_storm_vetoes_count():
    points = [pt(0, 90), pt(20, 0, vetoes=["route_terrain_block"])]
    for p in points:
        p["eta"] = "12:00"
    assert c.storm_ahead(points)[0] is None


def test_the_nearest_cell_ahead_wins():
    points = [pt(0, 90), stormy(20, eta="13:00"), stormy(40, eta="14:00")]
    points[0]["eta"] = "12:00"
    assert c.storm_ahead(points)[0]["km"] == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_criteria_route_score.py -q -k storm`
Expected: FAIL — `AttributeError: module 'criteria' has no attribute 'storm_ahead'`

- [ ] **Step 3: Write minimal implementation**

```python
# Грозовые вето — те, что говорят о конвекции, а не о рельефе или ветре.
STORM_VETOES = ("cape_extreme", "cape_cin", "lifted_index")
STORM_LOOKAHEAD_KM = 60.0


def storm_ahead(points, lookahead_km=STORM_LOOKAHEAD_KM):
    """Для каждой точки — ближайшая точка ВПЕРЕДИ с грозовым вето, либо None.

    На старте гроза в 60 км — не твоя проблема. На 40-м километре — твоя: ты
    летишь прямо в неё. Поэтому проверка упреждающая, и каждая точка впереди
    берётся в СВОЁ время прилёта, а не в текущее.
    """
    out = []
    for i, p in enumerate(points):
        found = None
        for q in points[i + 1:]:
            if q["km"] - p["km"] > lookahead_km:
                break
            if any(v in STORM_VETOES for v in q["assessment"].vetoes):
                found = {"km": q["km"], "eta": q.get("eta")}
                break
        out.append(found)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_criteria_route_score.py -q`
Expected: PASS, 17 passed

- [ ] **Step 5: Commit**

```bash
git add criteria.py tests/test_criteria_route_score.py
git commit -m "feat(criteria): упреждающая проверка гроз впереди по курсу"
```

---

### Task 7: Разворот маршрута

**Files:**
- Modify: `route.py`
- Test: `tests/test_route_reverse.py`

**Interfaces:**
- Consumes: `Sample`, `haversine`, `_set_leg_lengths`
- Produces: `reverse_samples(samples) -> list[Sample]`. Порог «обратный лучше» живёт
  в `criteria.REVERSE_GAIN` (задача 5) — пороги в этом проекте только там.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_route_reverse.py
"""Разворот маршрута: тот же набор точек, обратный порядок и пеленги."""
import pytest

import route

PTS = [route.Point(42.0, 44.0, "старт"),
       route.Point(42.0 + 40.0 / 111.195, 44.0, "финиш")]


def forward():
    s, _ = route.resample(PTS, step_km=10.0)
    return s


def test_same_number_of_points():
    assert len(route.reverse_samples(forward())) == len(forward())


def test_kilometres_count_from_the_new_start():
    rev = route.reverse_samples(forward())
    assert rev[0].km == pytest.approx(0.0)
    assert rev[-1].km == pytest.approx(forward()[-1].km)


def test_coordinates_are_the_same_points_in_reverse_order():
    fwd, rev = forward(), route.reverse_samples(forward())
    assert [(p.lat, p.lon) for p in rev] == [(p.lat, p.lon) for p in reversed(fwd)]


def test_bearings_are_opposite():
    fwd, rev = forward(), route.reverse_samples(forward())
    diff = abs(rev[0].track_bearing_deg - fwd[-1].track_bearing_deg)
    assert min(diff, 360 - diff) == pytest.approx(180.0, abs=1.0)


def test_roles_are_reassigned():
    rev = route.reverse_samples(forward())
    assert rev[0].role == "takeoff"
    assert rev[-1].role == "goal"
    assert {s.role for s in rev[1:-1]} == {"enroute"}


def test_leg_lengths_still_sum_to_total():
    rev = route.reverse_samples(forward())
    assert sum(s.leg_length_km for s in rev) == pytest.approx(rev[-1].km, rel=1e-6)


def test_original_samples_are_not_mutated():
    fwd = forward()
    before = [(s.km, s.role, s.track_bearing_deg) for s in fwd]
    route.reverse_samples(fwd)
    assert [(s.km, s.role, s.track_bearing_deg) for s in fwd] == before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_route_reverse.py -q`
Expected: FAIL — `AttributeError: module 'route' has no attribute 'reverse_samples'`

- [ ] **Step 3: Write minimal implementation**

Добавить `from dataclasses import dataclass, field, replace` к импортам и:

```python
def reverse_samples(samples):
    """Тот же маршрут в обратную сторону: те же координаты, новый километраж и пеленги.

    Второй ресэмплинг намеренно не делается — он мог бы дать другой набор точек, и
    сравнивать «туда» с «обратно» было бы не с чем. Погодные данные привязаны к
    координатам, поэтому вызывающий переиспользует их, просто развернув список.
    Исходные сэмплы не меняются: возвращаются копии.
    """
    total = samples[-1].km
    out = [replace(s, km=total - s.km) for s in reversed(samples)]
    for i, s in enumerate(out):
        a, b = (s, out[i + 1]) if i + 1 < len(out) else (out[i - 1], s)
        s.track_bearing_deg = haversine(Point(a.lat, a.lon), Point(b.lat, b.lon))[1]
        s.role = "enroute"
    out[0].role, out[-1].role = "takeoff", "goal"
    _set_leg_lengths(out)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_route_reverse.py -q`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add route.py tests/test_route_reverse.py
git commit -m "feat(route): разворот маршрута без повторного ресэмплинга"
```

---

### Task 8: Скоринг точек маршрута

**Files:**
- Modify: `forecast.py`
- Test: `tests/test_route_scored.py`

**Interfaces:**
- Consumes: `criteria.PROFILES`, `criteria.score_hour`, `engine.derive_hour`, поля `Sample` из спеки 1
- Produces: `forecast._raw_for(sample, body, date)`; `forecast._score_samples(samples, bodies, date)`; профиль маршрута дополняется полями `assessment` у точек и блоком `verdict`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_route_scored.py
"""Скоринг точек маршрута внутри профиля."""
import datetime as dt

import pytest

import criteria
import forecast
import route
from fixtures import om_route

PTS = [route.Point(42.0, 44.0, "старт"), route.Point(42.0 + 40.0 / 111.195, 44.0, "финиш")]
DATE = dt.date.today().isoformat()


def _n(url):
    return url.split("latitude=")[1].split("&")[0].count(",") + 1


@pytest.fixture()
def api(monkeypatch):
    calls = {"weather": 0, "terrain": 0}

    async def fake_weather(url):
        calls["weather"] += 1
        return om_route(_n(url))

    async def fake_terrain(coords):
        calls["terrain"] += 1
        return [1000.0] * len(coords)

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)
    return calls


async def test_every_point_gets_a_score_and_a_role_profile(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5)
    assert all(pt["score"] is not None for pt in p["points"])
    assert p["points"][0]["profile"] == "takeoff"
    assert p["points"][-1]["profile"] == "goal"
    assert {pt["profile"] for pt in p["points"][1:-1]} == {"enroute"}


async def test_verdict_block_is_present(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5)
    v = p["verdict"]
    assert set(v) >= {"score", "category", "feasibility", "bottleneck",
                      "flyable_until_km", "blocked_at_km"}


async def test_derived_inputs_match_the_engine_on_a_whole_hour(api):
    """Синтетический одночасовой блок должен давать те же производные, что и
    настоящий: иначе интерполяция спеки 1 меняет физику, а не только момент."""
    from fixtures import om_1day, site
    import engine

    data = om_1day()
    s = site()
    ctx = engine.day_context(data, s)
    real = engine.derive_hour(data["hourly"], 12, s, ctx)
    synth = {k: [v[12]] for k, v in data["hourly"].items()}
    assert engine.derive_hour(synth, 0, s, ctx) == real


async def test_storm_ahead_is_attached_to_points(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5)
    assert all("storm_ahead" in pt for pt in p["points"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_route_scored.py -q`
Expected: FAIL — `KeyError: 'score'` (в профиле точки нет поля оценки)

- [ ] **Step 3: Write minimal implementation**

В `forecast.py` добавить:

```python
def _profile_for(sample):
    return criteria.PROFILES[sample.role]


def _raw_for(sample, body, date):
    """Входы критериев для одной точки.

    Срез погоды на момент прилёта уже посчитан спекой 1 (с интерполяцией и с
    «худшим из двух часов» для осадков). Из него собирается синтетический блок
    из одного часа, и по нему зовётся существующая engine.derive_hour — так ни
    одна формула производных величин не дублируется, а интерполяция не теряется.
    """
    synth = {k: [v] for k, v in sample.weather.items()}
    hour = int(sample.eta_h)
    synth["time"] = [f"{date}T{hour:02d}:00"]
    D = body["daily"]
    elev = _elev_of(sample, body)
    site = {"name": sample.name or "точка", "lat": sample.lat, "lon": sample.lon,
            "elevation_m": elev,
            "aspect_deg": sample.site_aspect_deg,
            "slope_deg": engine.SLOPE_DEG}
    ctx = {"date": date, "sunrise": D["sunrise"][0], "sunset": D["sunset"][0],
           "daylight_idx": [0], "thermal_window": sample.window}

    raw = engine.derive_hour(synth, 0, site, ctx)
    raw["wind_along"] = sample.wind_along_kmh
    raw["wind_cross"] = None if sample.wind_cross_kmh is None else abs(sample.wind_cross_kmh)
    raw["working_band"] = sample.working_band_m
    raw["time_margin"] = sample.time_margin_min
    raw["wind_working"] = None if sample.wind_kmh is None else sample.wind_kmh / route.MS_TO_KMH
    raw["ground_speed"] = sample.gs_kmh
    if sample.role == "enroute":
        # На маршруте вето по ветру проверяется по среднему ветру рабочего слоя,
        # а не по ветру на базе: пилот весь переход идёт именно в этом слое.
        raw["wind_at_base"] = raw["wind_working"]
    return raw


def _score_samples(samples, bodies, date):
    """Оценить каждую точку по профилю её роли и вернуть свёртку маршрута."""
    for s, body in zip(samples, bodies):
        if s.eta_h is None:
            s.assessment = None
            continue
        s.assessment = criteria.score_hour(_raw_for(s, body, date), int(s.eta_h),
                                           profile=_profile_for(s))
    scored = [{"km": s.km, "leg_length_km": s.leg_length_km,
               "eta": _hhmm(s.eta_h), "assessment": s.assessment}
              for s in samples if s.assessment is not None]
    verdict = criteria.score_route(scored)
    for s, ahead in zip((s for s in samples if s.assessment is not None),
                        criteria.storm_ahead(scored)):
        s.storm_ahead = ahead
    return verdict
```

В `route.Sample` добавить поля `assessment = None`, `storm_ahead = None` и
`site_aspect_deg: float | None = None`. Последнее заполняется в `get_route` там же, где
сейчас считается `site_match`: если точка совпала с сохранённым стартом, берётся его
экспозиция, и критерий направления к склону начинает работать.

В `_point_dict` добавить:

```python
        "profile": s.role,
        "score": None if s.assessment is None else s.assessment.score,
        "category": None if s.assessment is None else s.assessment.category,
        "limiting": None if s.assessment is None else s.assessment.limiting_label,
        "vetoes": [] if s.assessment is None else criteria.veto_labels(s.assessment.vetoes),
        "storm_ahead": s.storm_ahead,
```

В `get_route` после цикла заполнения величин вызвать `_score_samples` и положить в
результат блок `verdict`:

```python
    verdict = _score_samples(samples, bodies, date)
    ...
    "verdict": {
        "score": verdict.score, "category": verdict.category,
        "label": verdict.label, "emoji": verdict.emoji,
        "feasibility": verdict.feasibility, "bottleneck": verdict.bottleneck,
        "blocked_at_km": verdict.blocked_at_km,
        "blocked_reason": verdict.blocked_reason,
        "flyable_until_km": verdict.flyable_until_km,
        "mean_score": verdict.mean_score, "confidence": verdict.confidence,
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_route_scored.py -q && .venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add forecast.py route.py tests/test_route_scored.py
git commit -m "feat(forecast): скоринг точек маршрута по профилям ролей"
```

---

### Task 9: Скан времени вылета и обратное направление

**Files:**
- Modify: `forecast.py`
- Test: `tests/test_route_scored.py` (дополняется)

**Interfaces:**
- Consumes: `_score_samples`, `route.reverse_samples`, `criteria.REVERSE_GAIN`
- Produces: `forecast._departure_options(samples)`; блоки `departure_scan` и `reverse` в профиле; константа `DEPARTURE_STEP_H = 0.5`

- [ ] **Step 1: Write the failing test**

```python
async def test_departure_scan_costs_no_extra_requests(api):
    p = await forecast.get_route(PTS, "Тест", DATE)
    assert api["weather"] == 1
    assert api["terrain"] == 1
    assert len(p["departure_scan"]) >= 2


async def test_scan_entries_carry_time_score_and_feasibility(api):
    p = await forecast.get_route(PTS, "Тест", DATE)
    e = p["departure_scan"][0]
    assert set(e) == {"departure", "score", "feasibility"}


async def test_best_departure_is_the_best_completable(api):
    p = await forecast.get_route(PTS, "Тест", DATE)
    ok = [e for e in p["departure_scan"] if e["feasibility"] == "completable"]
    if ok:
        assert p["best_departure"]["score"] == max(e["score"] for e in ok)


async def test_best_departure_is_none_when_nothing_is_completable(monkeypatch, api):
    """Показать «лучший из непроходимых» значит предложить пилоту выбрать,
    каким способом не долететь."""
    monkeypatch.setattr(forecast, "_score_samples",
                        lambda samples, bodies, date: criteria.RouteAssessment(
                            30.0, "no_fly", "🔴", "нелётно", "blocked_at_km"))
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5)
    assert p["best_departure"] is None


async def test_reverse_direction_is_computed_without_new_requests(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5)
    assert api["weather"] == 1
    assert "reverse" in p
    assert set(p["reverse"]) == {"score", "feasibility", "better"}


async def test_reverse_is_flagged_better_only_past_the_threshold(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5)
    gain = (p["reverse"]["score"] or 0) - (p["verdict"]["score"] or 0)
    assert p["reverse"]["better"] is (gain >= criteria.REVERSE_GAIN)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_route_scored.py -q -k "departure or reverse"`
Expected: FAIL — `KeyError: 'departure_scan'`

- [ ] **Step 3: Write minimal implementation**

```python
DEPARTURE_STEP_H = 0.5     # шаг скана времени вылета


def _departure_options(samples):
    """Времена вылета внутри термического окна первой точки, шагом полчаса."""
    w = samples[0].window
    if not w:
        return []
    step = DEPARTURE_STEP_H
    n = int((w["close_hour"] - w["open_hour"]) / step) + 1
    return [w["open_hour"] + k * step for k in range(max(0, n))]
```

Расчёт одного варианта выносится из `get_route` в отдельную функцию, чтобы её можно
было звать многократно по уже полученным данным:

```python
def _evaluate(samples, bodies, date, departure_h, cfg):
    """Времена прилёта, маршрутные величины и скоринг для ОДНОГО времени вылета.

    Работает на копии сэмплов: скан перебирает десятки вариантов, и мутировать
    общий список нельзя. Окна термической активности уже проставлены вызывающим
    и от времени вылета не зависят — они свойство точки, а не рейса.
    """
    work = copy.deepcopy(samples)
    notes = []
    speed = cfg["avg_route_speed_kmh"]

    def wind_for_segment(i, hour):
        pairs = []
        for s, body in ((work[i], bodies[i]), (work[i + 1], bodies[i + 1])):
            kmh, deg = _wind_at(s, body, hour)
            along, cross = route.wind_components(kmh, deg, work[i].track_bearing_deg)
            if along is not None:
                pairs.append((along, cross))
        if not pairs:
            return 0.0, 0.0
        return (sum(p[0] for p in pairs) / len(pairs),
                sum(p[1] for p in pairs) / len(pairs))

    route.fixed_eta(work, speed, departure_h)
    if cfg["wind_correction_enabled"]:
        route.march(work, speed, wind_for_segment, departure_h)
    else:
        for s in work:
            s.eta_h, s.gs_kmh = s.eta_fixed_h, speed

    over = [s for s in work if s.eta_h is not None and s.eta_h >= 24.0]
    if over:
        notes.append(f"С {over[0].km:.0f} км прилёт выходит за сутки — "
                     "дальше не считаю, данные запрошены на один день")
        for s in over:
            s.eta_h = None

    for s, body in zip(work, bodies):
        if s.eta_h is None:
            continue
        H = body["hourly"]
        elev_m = _elev_of(s, body)
        s.weather = _hourly_facts(H, s.eta_h)
        s.cloud_base_m = route.cloud_base_m(s.terrain_m, s.weather.get("temperature_2m"),
                                            s.weather.get("dew_point_2m"))
        s.working_band_m = route.working_band_m(s.cloud_base_m, s.terrain_m)
        s.wind_kmh, s.wind_dir_deg = _wind_at(s, body, s.eta_h)
        s.wind_along_kmh, s.wind_cross_kmh = route.wind_components(
            s.wind_kmh, s.wind_dir_deg, s.track_bearing_deg)
        s.time_margin_min = route.time_margin_min(s.window, s.eta_h)
        s.w_star_ms = engine.w_star(s.weather.get("boundary_layer_height"),
                                    s.weather.get("shortwave_radiation"),
                                    s.weather.get("temperature_2m"), elev_m)

    verdict = _score_samples(work, bodies, date)
    return work, verdict, notes
```

Тело `get_route` после этого сокращается: оно готовит сэмплы, рельеф, погоду и окна, а
затем зовёт `_evaluate` — один раз для запрошенного времени и по разу на каждый вариант
скана. Дублирования кода не остаётся, `_score_samples` из задачи 8 вызывается только
изнутри `_evaluate`.

Скан и обратное направление в `get_route`:

```python
    scan = []
    for h in _departure_options(samples):
        _w, v, _n = _evaluate(samples, bodies, date, h, cfg)
        scan.append({"departure": _hhmm(h), "score": v.score,
                     "feasibility": v.feasibility})
    completable = [e for e in scan if e["feasibility"] == "completable"]
    # Лучший из НЕПРОХОДИМЫХ не показывается намеренно: это предложение выбрать,
    # каким способом не долететь.
    best = max(completable, key=lambda e: e["score"] or 0) if completable else None

    rev_samples = route.reverse_samples(samples)
    _rw, rev_verdict, _rn = _evaluate(rev_samples, list(reversed(bodies)), date,
                                      departure_h, cfg)
    gain = (rev_verdict.score or 0) - (verdict.score or 0)
```

и в результат:

```python
    "departure_scan": scan,
    "best_departure": best,
    "reverse": {"score": rev_verdict.score, "feasibility": rev_verdict.feasibility,
                "better": gain >= criteria.REVERSE_GAIN},
```

`import copy` добавить к импортам `forecast.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_route_scored.py -q && .venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add forecast.py tests/test_route_scored.py
git commit -m "feat(forecast): скан времени вылета и обратное направление"
```

---

### Task 10: Карточка с вердиктом

**Files:**
- Modify: `route.py`
- Test: `tests/test_route_card.py` (дополняется)

**Interfaces:**
- Consumes: блоки `verdict`, `departure_scan`, `best_departure`, `reverse` и поля точек
- Produces: расширенная `render_card`

- [ ] **Step 1: Write the failing test**

Дополнить `profile()` в `tests/test_route_card.py` блоками вердикта и добавить:

```python
def with_verdict(**over):
    p = profile()
    for i, pt in enumerate(p["points"]):
        pt["score"] = [78, 62, 44][i]
        pt["category"] = ["excellent", "fair", "marginal"][i]
        pt["limiting"] = "рабочий диапазон высот"
        pt["vetoes"] = []
        pt["storm_ahead"] = None
        pt["profile"] = ["takeoff", "enroute", "goal"][i]
    p["verdict"] = {"score": 61, "category": "fair", "emoji": "🟡",
                    "label": "удовлетворительно", "feasibility": "completable",
                    "bottleneck": {"km": 40, "score": 44, "reason": "ветер вдоль курса"},
                    "blocked_at_km": None, "blocked_reason": None,
                    "flyable_until_km": 40, "mean_score": 61.3, "confidence": 1.0}
    p["departure_scan"] = [{"departure": "11:00", "score": 69, "feasibility": "completable"},
                           {"departure": "11:30", "score": 61, "feasibility": "completable"}]
    p["best_departure"] = p["departure_scan"][0]
    p["reverse"] = {"score": 74, "feasibility": "completable", "better": True}
    p.update(over)
    return p


def test_verdict_line_shows_category_and_score():
    text = route.render_card(with_verdict())
    assert "🟡" in text and "61" in text


def test_score_column_replaces_the_thermal_column():
    text = route.render_card(with_verdict())
    assert "балл" in text
    assert "поток" not in text


def test_table_still_fits_the_mobile_width():
    text = route.render_card(with_verdict())
    assert max(len(ln) for ln in text.splitlines()) <= route.CARD_WIDTH


def test_bottleneck_names_the_kilometre():
    text = route.render_card(with_verdict())
    assert "40" in text and "44" in text


def test_blocked_route_leads_with_the_reason_not_the_score():
    p = with_verdict()
    p["verdict"].update({"feasibility": "blocked_at_km", "blocked_at_km": 40,
                         "blocked_reason": "база ниже безопасной высоты над рельефом",
                         "flyable_until_km": 20})
    text = route.render_card(p)
    head = "\n".join(text.splitlines()[:8])
    assert "40" in head and "база ниже" in head
    assert "Лётно до 20 км" in text


def test_best_departure_and_alternatives():
    text = route.render_card(with_verdict())
    assert "11:00" in text and "11:30" in text


def test_no_completable_departure_is_said_plainly():
    p = with_verdict(best_departure=None)
    p["departure_scan"] = [{"departure": "11:00", "score": 30, "feasibility": "blocked_at_km"}]
    text = route.render_card(p)
    assert "ни одно время" in text.lower()


def test_reverse_line_appears_only_when_better():
    assert "74" in route.render_card(with_verdict())
    p = with_verdict()
    p["reverse"]["better"] = False
    assert "Обратный" not in route.render_card(p)


def test_storm_ahead_line_names_kilometre_and_time():
    p = with_verdict()
    p["points"][0]["storm_ahead"] = {"km": 60, "eta": "14:20"}
    text = route.render_card(p)
    assert "60" in text and "14:20" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_route_card.py -q`
Expected: FAIL — в карточке нет строки вердикта и колонки баллов

- [ ] **Step 3: Write minimal implementation**

Колонка «поток» в `_rows` заменяется на «балл». **Эмодзи категории в таблицу не идёт**:
в моноширинном блоке он вдвое шире цифр и ломает колонки — в проекте это уже отмечено
в `engine.hourly_strip`. Категория живёт на строке вердикта, где выравнивание не нужно.

```python
    out = [" км  время  вдоль  ветер  балл"]
    ...
        val = "  —" if p.get("score") is None else f"{p['score']:3.0f}"
        out.append(f"{p['km']:3.0f}  {eta}  {arrow}{along_txt}  {wind}  {val}")
```

Блок вердикта встаёт между шапкой и таблицей. Когда маршрут не проходится, первой идёт
причина и километр — балл в этом случае вторичен:

```python
FEASIBILITY_RU = {
    "completable": "маршрут проходится",
    "blocked_at_km": "маршрут обрывается",
    "too_slow": "не успеваешь до закрытия окна",
    "unknown": "данных не хватает для вердикта",
}


def _verdict_lines(v):
    if not v:
        return []
    out = []
    if v["feasibility"] == "blocked_at_km":
        out.append(f"⛔ Обрывается на {v['blocked_at_km']:.0f} км:")
        out += _wrap(v["blocked_reason"], indent="   ")
    else:
        out.append(f"{v['emoji']} {v['label'].capitalize()} · {v['score']:.0f}")
        out.append(f"   {FEASIBILITY_RU[v['feasibility']]}")
    if v.get("flyable_until_km") is not None:
        out.append(f"   Лётно до {v['flyable_until_km']:.0f} км")
    b = v.get("bottleneck")
    if b:
        out.append(f"   Узкое место: {b['score']} на {b['km']:.0f} км")
    return out
```

Перенос длинных строк — причина вето вроде «база ниже безопасной высоты над рельефом»
в одну строку не влезает:

```python
def _wrap(text, indent="   "):
    """Разбить строку по ширине карточки, каждую часть с отступом."""
    words, lines, cur = text.split(), [], indent
    for w in words:
        candidate = f"{cur} {w}" if cur.strip() else f"{indent}{w}"
        if len(candidate) > CARD_WIDTH and cur.strip():
            lines.append(cur)
            cur = f"{indent}{w}"
        else:
            cur = candidate
    if cur.strip():
        lines.append(cur)
    return lines
```

Строки лучшего вылета, обратного направления и грозы впереди — в хвост карточки:

```python
    best, scan = profile.get("best_departure"), profile.get("departure_scan") or []
    if best:
        tail.append(f"⏱ Лучший вылет {best['departure']} · {best['score']:.0f}")
        alts = [e for e in scan if e["departure"] != best["departure"]][:3]
        if alts:
            tail.append("   " + " · ".join(f"{e['departure']}→{e['score']:.0f}" for e in alts))
    elif scan:
        tail.append("⏱ Ни одно время вылета не даёт")
        tail.append("   проходимый маршрут")

    storm = next((p for p in pts if p.get("storm_ahead")), None)
    if storm:
        s = storm["storm_ahead"]
        tail.append(f"⚡ {storm['km']:.0f} км: гроза впереди на")
        tail.append(f"   {s['km']:.0f}-м км, подлёт {s['eta']}")

    rev = profile.get("reverse")
    if rev and rev.get("better"):
        tail.append(f"↩️ Обратный лучше: {rev['score']:.0f} против "
                    f"{profile['verdict']['score']:.0f}")
```

Все блоки необязательны: если ключа нет (карточка спеки 1), строка не появляется.

- [ ] **Step 4: Run test to verify it passes**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_route_card.py -q && .venv/bin/python -m pytest -q`
Expected: PASS

Отрисуй карточку глазами и проверь ширину:

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0,'tests')
from test_route_card import with_verdict
import route
for ln in route.render_card(with_verdict()).splitlines():
    print(f'{len(ln):2d}|{ln}')"
```

- [ ] **Step 5: Commit**

```bash
git add route.py tests/test_route_card.py
git commit -m "feat(route): карточка с вердиктом, узким местом и лучшим вылетом"
```

---

### Task 11: Блок порогов по профилям и README

**Files:**
- Modify: `criteria.py`, `README.md`
- Test: `tests/test_analysis.py` (дополняется)

**Interfaces:**
- Consumes: `PROFILES`
- Produces: `reference_text(profile=TAKEOFF)`

- [ ] **Step 1: Write the failing test**

```python
def test_reference_text_is_generated_per_profile():
    import criteria
    launch = criteria.reference_text(criteria.TAKEOFF)
    enroute = criteria.reference_text(criteria.ENROUTE)
    assert "направление к склону" in launch
    assert "направление к склону" not in enroute
    assert "ветер вдоль курса" in enroute
    assert f"{criteria.ROUTE_GROUPS['wind_along'].weight:.2f}" in enroute


def test_default_reference_text_is_still_the_launch_one():
    import criteria
    assert criteria.reference_text() == criteria.reference_text(criteria.TAKEOFF)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `set -o pipefail; .venv/bin/python -m pytest tests/test_analysis.py -q -k reference`
Expected: FAIL — `reference_text() takes 0 positional arguments`

- [ ] **Step 3: Write minimal implementation**

`reference_text(profile=TAKEOFF)` обходит `profile.groups` и `profile.group_params(gkey)`
вместо глобальных таблиц, а списки вето и штрафов фильтрует по профилю:

```python
def reference_text(profile=TAKEOFF):
    """Русский блок порогов для промпта — генерируется из таблицы, чтобы промпт
    не мог разойтись с расчётом. У каждой роли точки свой набор критериев."""
    ...
    for gkey, group in profile.groups.items():
        params = [PARAMS[k] for k in profile.group_params(gkey)]
        ...
    lines += [
        "ВЕТО ...: " + "; ".join(r.label for r in VETOES if r.key in profile.vetoes) + ".",
        "ШТРАФЫ ...: " + "; ".join(f"{r.label} ×{r.factor:.2f}"
                                   for r in PENALTIES if r.key in profile.penalties) + ".",
    ]
```

В `README.md` дописать в раздел «Погода по маршруту»: три профиля критериев и их разницу,
формулу свёртки, статус выполнимости, упреждающую проверку гроз, скан времени вылета и
обратное направление. Убрать абзац «балла и вердикта по маршруту пока нет» — он больше
не верен.

- [ ] **Step 4: Run test to verify it passes**

Run: `set -o pipefail; .venv/bin/python -m pytest -q`
Expected: PASS; существующий тест синхронности промпта с критериями остаётся зелёным,
потому что `analysis._REFERENCE` собирается из вызова без аргумента

- [ ] **Step 5: Commit**

```bash
git add criteria.py README.md tests/test_analysis.py
git commit -m "feat(criteria): блок порогов по профилям + README"
```

---

## Проверка перед сдачей

- [ ] `set -o pipefail; .venv/bin/python -m pytest -q` — зелёный, тестов около 480
- [ ] Предохранитель из задачи 1 зелёный: профиль старта считает то же, что до рефакторинга
- [ ] `grep -n "import route\|import forecast" criteria.py` — пусто: зависимость строго в одну сторону
- [ ] Скан вылета и обратное направление не увеличивают счётчик обращений к API (тест из задачи 9)
- [ ] Карточка не шире 32 символов ни в одной строке, включая заблокированный маршрут с длинной причиной
- [ ] В `criteria.py` есть комментарии-оговорки: коэффициент 0,6 компромиссный и не измерен; порог 12 баллов для обратного направления подобран, а не измерен; граница «лётно до N км» опирается на прямую между точками

# Маршрутная сводка, спека 3: разрез, карточка точки, маршруты, ИИ — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть маршрутную фичу: PNG-разрез вдоль маршрута, карточка отдельной точки, сохранённые маршруты, разбор KML и ИИ-интерпретация с проверкой ответа.

**Architecture:** Профиль маршрута из `forecast.get_route()` дополняется четырьмя полями и остаётся единственным источником данных для всего нового. Кнопки под карточкой держат в памяти бота не готовый профиль, а исходный запрос — по нажатию профиль пересчитывается поверх тёплого кэша погоды, без обращений к API. Отрисовка (`charts.py`), текст (`route.py`) и хранение (`routes.py`) остаются без сети и без aiogram.

**Tech Stack:** Python 3.10, aiogram 3, Pillow, httpx, google-genai, pytest (`asyncio_mode = auto`). Новых зависимостей нет.

**Спека:** `docs/superpowers/specs/2026-07-28-route-visuals-design.md`
**Ветка:** `feature/route-visuals` (уже создана, спека в ней закоммичена)

## Global Constraints

- Ширина текстовых карточек — `route.CARD_WIDTH` (32 символа). Ни одна строка не длиннее.
- `callback_data` не длиннее 64 байт; кнопки строятся только через `bot._btn`.
- Пороги живут в `criteria.py`. Своих копий чисел ни в `route.py`, ни в `charts.py`, ни в промпте не заводится.
- `criteria.py` не получает импортов из `route`, `forecast`, `charts`, `analysis`.
- `charts.py` и `route.py` — без сети и без aiogram. `routes.py` — без сети и без aiogram.
- Отсутствующая величина печатается как «н/д», строка не пропадает. Пропавшая строка читается как «нет проблемы», а «н/д» — как «неизвестно».
- Русские тексты — без выдуманных сокращений и аббревиатур.
- Прогон тестов только через `set -o pipefail`, иначе `tail` в конвейере съедает код возврата и коммит уходит на красных тестах.
- Каждая задача завершается коммитом. Ветка не сливается без явного разрешения пользователя.

## Порядок и одно отступление от спеки

§12 спеки ставит хранилище и команды перед токен-кэшем. Команда `/saveroute` сохраняет **последний посчитанный маршрут**, то есть читает тот самый кэш, поэтому кэш идёт раньше команд. Само хранилище (задача 2) от кэша по-прежнему не зависит и остаётся самостоятельным куском.

## Карта файлов

| Файл | Ответственность | Задачи |
|---|---|---|
| `forecast.py` | четыре поля в профиле, доставка PNG, сборка данных для модели | 1, 9, 11, 14 |
| `routes.py` (новый) | хранение сохранённых маршрутов | 2 |
| `route.py` | характерные точки, карточка точки, разбор KML, текст ИИ-разбора | 3, 6, 7, 14 |
| `bot.py` | токен-кэш, клавиатура, команды, обработчики кнопок | 4, 5, 6, 7, 9, 10, 14 |
| `charts.py` | отрисовка разреза | 8 |
| `analysis.py` | промпт, схема ответа, проверки | 12, 13 |
| `README.md` | описание новых команд и кнопок | 15 |

---

## Task 1: Четыре поля в профиле

**Files:**
- Modify: `forecast.py` (`_point_dict`, `get_route`)
- Test: `tests/test_route_scored.py`

**Interfaces:**
- Consumes: существующий `forecast.get_route(points, name, date, departure_h=None)`.
- Produces: в возвращаемом словаре появляется `profile["terrain"]` вида `{"km": [float, ...], "elevations": [float, ...]}` либо `None`; у каждой точки — `is_turnpoint: bool`, `thermal_ceiling_m: int | None`, `subs: dict`, `groups: dict`.

- [ ] **Step 1: Write the failing tests**

Дописать в конец `tests/test_route_scored.py`:

```python
# ---------------------------------------------------------------- поля для спеки 3
async def test_profile_carries_the_fine_terrain_grid(api):
    """Разрезу нужен рельеф между расчётными точками, а не только под ними."""
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5)
    t = p["terrain"]
    assert len(t["km"]) == len(t["elevations"])
    assert t["km"][0] == 0.0
    assert t["km"] == sorted(t["km"])
    assert t["km"][-1] == pytest.approx(p["route"]["total_km"], rel=1e-3)


async def test_terrain_grid_is_finer_than_the_weather_points(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5)
    assert len(p["terrain"]["km"]) > len(p["points"])


async def test_no_terrain_means_no_grid(monkeypatch):
    async def fake_weather(url):
        return om_route(_n(url))

    async def fake_terrain(coords):
        return None

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5)
    assert p["terrain"] is None


async def test_points_carry_turnpoint_ceiling_and_subscores(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5)
    first, middle = p["points"][0], p["points"][1]
    assert first["is_turnpoint"] is True
    assert middle["is_turnpoint"] is False
    assert first["thermal_ceiling_m"] > first["terrain_m"]
    assert first["subs"] and first["groups"]


async def test_ceiling_is_none_without_terrain(monkeypatch):
    """Потолок считается от рельефа: нет рельефа — нет и потолка, а не ноль."""
    async def fake_weather(url):
        return om_route(_n(url))

    async def fake_terrain(coords):
        return None

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5)
    assert all(pt["thermal_ceiling_m"] is None for pt in p["points"])
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
set -o pipefail; python -m pytest tests/test_route_scored.py -x -q 2>&1 | tail -20
```

Expected: FAIL — `KeyError: 'terrain'`.

- [ ] **Step 3: Implement**

В `forecast.py` перед `_point_dict` добавить:

```python
def _ceiling_m(s):
    """Потолок термиков в метрах MSL: рельеф плюс глубина пограничного слоя.

    Берётся terrain_m (максимум по участку), а не terrain_point_m — тот же
    консервативный выбор, что уже сделан для working_band_m. Иначе потолок и
    рабочий коридор считались бы от разных отметок.
    """
    blh = (s.weather or {}).get("boundary_layer_height")
    if s.terrain_m is None or blh is None:
        return None
    return round(s.terrain_m + blh)
```

В `_point_dict` добавить четыре ключа (после строки со `storm_ahead`):

```python
        "is_turnpoint": s.is_turnpoint,
        "thermal_ceiling_m": _ceiling_m(s),
        "subs": {} if s.assessment is None else s.assessment.subs,
        "groups": {} if s.assessment is None else s.assessment.groups,
```

В `get_route` в возвращаемый словарь, сразу после `"points": [...]`, добавить:

```python
        # Мелкая сетка рельефа отдаётся ЦЕЛИКОМ и со своим километражом.
        # terrain_grid делит каждое плечо на целое число равных частей, поэтому
        # шаг у разных плеч разный и «i * step_km» дал бы неверный километраж —
        # рельеф на разрезе молча съехал бы относительно погоды.
        "terrain": ({"km": [round(km, 3) for km, _lat, _lon in grid],
                     "elevations": elev} if elev else None),
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: все тесты зелёные (было 540, стало 545).

- [ ] **Step 5: Commit**

```bash
git add forecast.py tests/test_route_scored.py
git commit -m "feat(route): рельефная сетка, потолок термиков и субоценки в профиле"
```

---

## Task 2: Хранилище сохранённых маршрутов

**Files:**
- Create: `routes.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_routes_store.py`

**Interfaces:**
- Consumes: `route.Point`, `route.MAX_POINTS`, `route.MIN_POINTS`, `engine.SITES`.
- Produces: `routes.ROUTES_FILE`, `routes.MAX_ROUTES`, `routes.list_all() -> dict`, `routes.save(name, points)`, `routes.get(name) -> list[route.Point] | None`, `routes.delete(name) -> bool`, `route.total_km(points) -> float`.

- [ ] **Step 1: Write the failing tests**

Создать `tests/test_route_total_km.py`:

```python
"""Длина ломаной по точкам."""
import pytest

import route


def test_total_km_sums_the_legs():
    pts = [route.Point(42.0, 44.0), route.Point(42.0 + 40.0 / 111.195, 44.0)]
    assert route.total_km(pts) == pytest.approx(40.0, abs=0.1)


def test_total_km_of_a_single_point_is_zero():
    assert route.total_km([route.Point(42.0, 44.0)]) == 0.0


def test_total_km_of_nothing_is_zero():
    assert route.total_km([]) == 0.0
```

Создать `tests/test_routes_store.py`:

```python
"""Хранилище сохранённых маршрутов: файл рядом с sites.json."""
import json
import os

import pytest

import route
import routes

PTS = [route.Point(42.0, 44.0, "старт"),
       route.Point(42.0 + 40.0 / 111.195, 44.0, "финиш")]


def test_empty_when_there_is_no_file():
    assert routes.list_all() == {}


def test_save_then_get_round_trips_coordinates_and_names():
    routes.save("Гудаури", PTS)
    got = routes.get("Гудаури")
    assert [(p.lat, p.lon, p.name) for p in got] == [(p.lat, p.lon, p.name) for p in PTS]


def test_saved_entry_records_the_date():
    routes.save("Гудаури", PTS)
    assert routes.list_all()["Гудаури"]["saved"]


def test_get_of_an_unknown_name_is_none():
    assert routes.get("нет такого") is None


def test_delete_reports_whether_it_deleted():
    routes.save("Гудаури", PTS)
    assert routes.delete("Гудаури") is True
    assert routes.delete("Гудаури") is False
    assert routes.list_all() == {}


def test_saving_the_same_name_overwrites():
    routes.save("Гудаури", PTS)
    routes.save("Гудаури", PTS + [route.Point(41.9, 44.1, "ещё")])
    assert len(routes.get("Гудаури")) == 3
    assert len(routes.list_all()) == 1


def test_a_corrupt_file_gives_an_empty_list_not_a_crash():
    """Порча файла не должна ронять бота — как в settings.get()."""
    with open(routes.ROUTES_FILE, "w", encoding="utf-8") as f:
        f.write("{это не json")
    assert routes.list_all() == {}


def test_a_foreign_structure_is_ignored():
    with open(routes.ROUTES_FILE, "w", encoding="utf-8") as f:
        json.dump({"Гудаури": "строка вместо объекта"}, f)
    assert routes.list_all() == {}
    assert routes.get("Гудаури") is None


def test_a_broken_entry_reads_as_none():
    with open(routes.ROUTES_FILE, "w", encoding="utf-8") as f:
        json.dump({"Гудаури": {"points": [["север", "восток"]]}}, f)
    assert routes.get("Гудаури") is None


def test_an_entry_with_one_point_reads_as_none():
    """Маршрут из одной точки посчитать нельзя, значит и отдавать его нечего."""
    with open(routes.ROUTES_FILE, "w", encoding="utf-8") as f:
        json.dump({"Гудаури": {"points": [[42.0, 44.0, None]]}}, f)
    assert routes.get("Гудаури") is None


def test_the_store_has_a_ceiling():
    for i in range(routes.MAX_ROUTES):
        routes.save(f"маршрут {i}", PTS)
    with pytest.raises(ValueError, match=str(routes.MAX_ROUTES)):
        routes.save("лишний", PTS)


def test_overwriting_at_the_ceiling_still_works():
    """Потолок про число записей, а не про запрет трогать существующие."""
    for i in range(routes.MAX_ROUTES):
        routes.save(f"маршрут {i}", PTS)
    routes.save("маршрут 0", PTS)
    assert len(routes.list_all()) == routes.MAX_ROUTES


def test_too_many_points_is_refused():
    many = [route.Point(42.0 + i / 1000.0, 44.0) for i in range(route.MAX_POINTS + 1)]
    with pytest.raises(ValueError, match="точек"):
        routes.save("длинный", many)


def test_the_file_lives_next_to_sites_json():
    import engine
    assert os.path.dirname(routes.ROUTES_FILE) == os.path.dirname(engine.SITES)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
set -o pipefail; python -m pytest tests/test_routes_store.py tests/test_route_total_km.py -x -q 2>&1 | tail -20
```

Expected: FAIL — `ModuleNotFoundError: No module named 'routes'`.

- [ ] **Step 3: Implement**

Добавить в `route.py` в раздел геометрии, сразу после `haversine`:

```python
def total_km(points):
    """Длина ломаной по точкам в километрах."""
    return sum(haversine(a, b)[0] for a, b in zip(points, points[1:])) / 1000.0
```

Создать `routes.py`:

```python
"""Сохранённые маршруты — один файл на бота, как настройки и список стартов.

Хранится ТОЛЬКО геометрия. Погода всегда считается заново, поэтому устаревать
здесь нечему: сохранённый маршрут — это набор координат, а не прогноз.
"""
import datetime as dt
import json
import os

import engine
import route

ROUTES_FILE = (os.environ.get("ROUTES_FILE")
               or os.path.join(os.path.dirname(engine.SITES) or ".", "routes.json"))
MAX_ROUTES = 20


def list_all():
    """Все маршруты; пустой словарь при отсутствии файла, порче или чужой структуре."""
    try:
        with open(ROUTES_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items()
            if isinstance(v, dict) and isinstance(v.get("points"), list)}


def _save(data):
    with open(ROUTES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def save(name, points):
    """Сохранить точки под именем. ValueError при переполнении и слишком длинном маршруте."""
    if len(points) > route.MAX_POINTS:
        raise ValueError(f"слишком много точек: {len(points)}, "
                         f"максимум {route.MAX_POINTS}")
    data = list_all()
    if name not in data and len(data) >= MAX_ROUTES:
        raise ValueError(f"сохранено уже {MAX_ROUTES} маршрутов — "
                         "удали ненужный через /delroute")
    data[name] = {"points": [[p.lat, p.lon, p.name] for p in points],
                  "saved": dt.date.today().isoformat()}
    _save(data)


def get(name):
    """Точки маршрута или None. Битая запись читается как None, а не роняет бота."""
    entry = list_all().get(name)
    if not entry:
        return None
    out = []
    for item in entry["points"]:
        try:
            lat, lon = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError, KeyError):
            return None
        out.append(route.Point(lat, lon, item[2] if len(item) > 2 else None))
    return out if len(out) >= route.MIN_POINTS else None


def delete(name):
    """True, если удалили; False, если такого маршрута не было."""
    data = list_all()
    if name not in data:
        return False
    del data[name]
    _save(data)
    return True
```

В `tests/conftest.py` добавить импорт рядом с существующим `import settings`:

```python
import routes  # noqa: E402
```

и в фикстуру `fresh_state`, рядом с удалением `settings.SETTINGS_FILE`:

```python
    if os.path.exists(routes.ROUTES_FILE):
        os.remove(routes.ROUTES_FILE)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: всё зелёное.

- [ ] **Step 5: Commit**

```bash
git add routes.py route.py tests/conftest.py tests/test_routes_store.py tests/test_route_total_km.py
git commit -m "feat(routes): хранилище сохранённых маршрутов"
```

---

## Task 3: Характерные точки маршрута

**Files:**
- Modify: `route.py`
- Test: `tests/test_route_keypoints.py`

**Interfaces:**
- Consumes: словарь профиля из `forecast.get_route` (ключи `points`, `verdict`).
- Produces: `route.KEY_POINT_LIMIT = 8`, `route.key_points(profile) -> list[dict]`, где каждый элемент — `{"km": float, "mark": str, "kinds": set[str]}`.

- [ ] **Step 1: Write the failing test**

Создать `tests/test_route_keypoints.py`:

```python
"""Характерные точки маршрута: где реально что-то решается."""
import route


def profile(n=5, **over):
    pts = []
    for i in range(n):
        pts.append({"km": float(i * 10), "role": ("takeoff" if i == 0 else
                                                  "goal" if i == n - 1 else "enroute"),
                    "is_turnpoint": i in (0, n - 1), "is_terrain_peak": False})
    p = {"points": pts, "verdict": {"blocked_at_km": None, "bottleneck": None}}
    p.update(over)
    return p


def kms(profile_):
    return [k["km"] for k in route.key_points(profile_)]


def marks(profile_):
    return {k["km"]: k["mark"] for k in route.key_points(profile_)}


def test_start_and_goal_are_always_there():
    assert kms(profile()) == [0.0, 40.0]


def test_turnpoints_are_included():
    p = profile()
    p["points"][2]["is_turnpoint"] = True
    assert kms(p) == [0.0, 20.0, 40.0]


def test_terrain_peaks_are_included():
    p = profile()
    p["points"][3]["is_terrain_peak"] = True
    assert kms(p) == [0.0, 30.0, 40.0]


def test_bottleneck_and_blocked_point_are_included():
    p = profile(verdict={"blocked_at_km": 30.0, "bottleneck": {"km": 20.0}})
    assert kms(p) == [0.0, 20.0, 30.0, 40.0]


def test_a_point_appears_once_with_the_more_important_mark():
    """Вершина рельефа, оказавшаяся узким местом, — одна кнопка, а не две."""
    p = profile(verdict={"blocked_at_km": None, "bottleneck": {"km": 20.0}})
    p["points"][2]["is_terrain_peak"] = True
    assert kms(p).count(20.0) == 1
    assert marks(p)[20.0] == "⚠"


def test_blocked_outranks_the_bottleneck_on_the_same_point():
    p = profile(verdict={"blocked_at_km": 20.0, "bottleneck": {"km": 20.0}})
    assert marks(p)[20.0] == "⛔"


def test_marks_tell_the_kinds_apart():
    p = profile()
    p["points"][2]["is_turnpoint"] = True
    p["points"][3]["is_terrain_peak"] = True
    m = marks(p)
    assert m[0.0] == "△" and m[40.0] == "⚑" and m[20.0] == "◆" and m[30.0] == "▲"


def test_never_more_than_the_limit():
    p = profile(n=30)
    for pt in p["points"]:
        pt["is_terrain_peak"] = True
    assert len(route.key_points(p)) <= route.KEY_POINT_LIMIT


def test_the_limit_keeps_the_important_kinds_first():
    """Вершин много, но старт, финиш и узкое место обязаны остаться."""
    p = profile(n=30, verdict={"blocked_at_km": None, "bottleneck": {"km": 150.0}})
    for pt in p["points"]:
        pt["is_terrain_peak"] = True
    got = kms(p)
    assert 0.0 in got and 290.0 in got and 150.0 in got


def test_result_is_sorted_by_kilometre():
    p = profile(n=30)
    for pt in p["points"]:
        pt["is_terrain_peak"] = True
    got = kms(p)
    assert got == sorted(got)


def test_no_points_no_key_points():
    assert route.key_points({"points": [], "verdict": {}}) == []


def test_missing_verdict_does_not_crash():
    assert kms({"points": profile()["points"]}) == [0.0, 40.0]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
set -o pipefail; python -m pytest tests/test_route_keypoints.py -x -q 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: module 'route' has no attribute 'key_points'`.

- [ ] **Step 3: Implement**

Добавить в `route.py` перед разделом карточки (перед `def _signed`):

```python
# ---------------------------------------------------------------- характерные точки
KEY_POINT_LIMIT = 8            # длиннее ряд кнопок в Telegram не читается
_KM_EPS = 0.05                 # километраж округлён до десятой, сравнивать точно нельзя

# Вид точки → метка, в порядке убывания важности. Точка, подходящая под несколько
# видов, показывается ОДИН раз — с меткой самого важного из них.
_KEY_MARKS = (("blocked", "⛔"), ("bottleneck", "⚠"), ("takeoff", "△"),
              ("goal", "⚑"), ("turnpoint", "◆"), ("peak", "▲"))
# Кого выбрасывать первым, когда точек больше лимита: с хвоста этого списка.
_KEY_KEEP_ORDER = ("takeoff", "goal", "blocked", "bottleneck", "turnpoint", "peak")


def _kinds_of(p, blocked, bottleneck):
    kinds = set()
    if blocked is not None and abs(p["km"] - blocked) < _KM_EPS:
        kinds.add("blocked")
    if bottleneck is not None and abs(p["km"] - bottleneck) < _KM_EPS:
        kinds.add("bottleneck")
    if p.get("role") in ("takeoff", "goal"):
        kinds.add(p["role"])
    elif p.get("is_turnpoint"):
        kinds.add("turnpoint")
    if p.get("is_terrain_peak"):
        kinds.add("peak")
    return kinds


def key_points(profile):
    """Точки, ради которых стоит открывать подробности: старт, финиш, обрыв,
    узкое место, поворотные и вершины рельефа.

    Не больше KEY_POINT_LIMIT: расчётных точек бывает полсотни, и вываливать их
    все кнопками — значит не помочь выбрать, а переложить выбор на пилота.
    """
    pts = profile.get("points") or []
    v = profile.get("verdict") or {}
    blocked = v.get("blocked_at_km")
    bottleneck = (v.get("bottleneck") or {}).get("km")
    found = []
    for p in pts:
        kinds = _kinds_of(p, blocked, bottleneck)
        if kinds:
            mark = next(m for k, m in _KEY_MARKS if k in kinds)
            found.append({"km": p["km"], "mark": mark, "kinds": kinds})
    if len(found) <= KEY_POINT_LIMIT:
        return found
    rank = {k: i for i, k in enumerate(_KEY_KEEP_ORDER)}
    keep = sorted(found, key=lambda f: min(rank[k] for k in f["kinds"]))[:KEY_POINT_LIMIT]
    return sorted(keep, key=lambda f: f["km"])
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: всё зелёное.

- [ ] **Step 5: Commit**

```bash
git add route.py tests/test_route_keypoints.py
git commit -m "feat(route): выбор характерных точек маршрута"
```

---

## Task 4: Токен-кэш и клавиатура под карточкой

**Files:**
- Modify: `bot.py`
- Test: `tests/test_route_buttons.py`

**Interfaces:**
- Consumes: `route.key_points`, `analysis.available()`, существующие `bot._btn`, `bot._chunks`, `bot._send_route`.
- Produces: `bot._ROUTE_CACHE_MAX = 8`, `bot._route_cache` (`OrderedDict`), `bot._remember_route(points, name, date, departure) -> str`, `bot._route_keyboard(token, profile) -> InlineKeyboardMarkup | None`, `bot._profile_from_token(cb, token, departure=None) -> dict | None`.

- [ ] **Step 1: Write the failing test**

Создать `tests/test_route_buttons.py`:

```python
"""Кнопки под карточкой маршрута и токен, который их обслуживает."""
import datetime as dt

import pytest

import bot as botmod
import forecast
import route
from fixtures import om_route
from tg import buttons, cb_answers, keyboards, text_update, texts

DATE = dt.date.today().isoformat()
BODY = ("/route\n"
        "42.4776, 44.4787, старт\n"
        "42.1176, 44.4787, финиш")


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


def _last_token():
    return next(reversed(botmod._route_cache))


async def test_card_comes_with_a_keyboard(bot, session, api):
    await botmod.dp.feed_update(bot, text_update(BODY))
    assert keyboards(session), "под карточкой маршрута нет кнопок"


async def test_keyboard_has_point_buttons_and_actions(bot, session, api):
    await botmod.dp.feed_update(bot, text_update(BODY))
    labels = [b.text for b in buttons(keyboards(session)[-1])]
    assert any("△" in t for t in labels)
    assert any("⚑" in t for t in labels)
    assert any("Разрез" in t for t in labels)
    assert any("Другое время" in t for t in labels)


async def test_every_callback_data_fits_telegram(bot, session, api):
    await botmod.dp.feed_update(bot, text_update(BODY))
    for b in buttons(keyboards(session)[-1]):
        assert len(b.callback_data.encode("utf-8")) <= 64


async def test_the_token_remembers_the_request_not_the_answer(bot, session, api):
    await botmod.dp.feed_update(bot, text_update(BODY))
    entry = botmod._route_cache[_last_token()]
    assert set(entry) == {"points", "name", "date", "departure"}
    assert all(isinstance(p, route.Point) for p in entry["points"])


async def test_the_cache_has_a_ceiling(bot, session, api):
    for _ in range(botmod._ROUTE_CACHE_MAX + 3):
        await botmod.dp.feed_update(bot, text_update(BODY))
    assert len(botmod._route_cache) == botmod._ROUTE_CACHE_MAX


async def test_the_analysis_button_is_hidden_without_a_key(bot, session, api):
    """Кнопка, которая всегда отвечает «недоступно», хуже отсутствующей кнопки."""
    await botmod.dp.feed_update(bot, text_update(BODY))
    labels = [b.text for b in buttons(keyboards(session)[-1])]
    assert not any("Разбор" in t for t in labels)


async def test_the_analysis_button_appears_with_a_key(bot, session, api, monkeypatch):
    monkeypatch.setattr(botmod.analysis, "available", lambda: True)
    await botmod.dp.feed_update(bot, text_update(BODY))
    labels = [b.text for b in buttons(keyboards(session)[-1])]
    assert any("Разбор" in t for t in labels)
```

Прогон требует фикстур `bot` и `session` — они уже есть в `tests/conftest.py` и используются остальными диалоговыми тестами.

- [ ] **Step 2: Run the test to verify it fails**

```bash
set -o pipefail; python -m pytest tests/test_route_buttons.py -x -q 2>&1 | tail -20
```

Expected: FAIL — под карточкой нет клавиатуры.

- [ ] **Step 3: Implement**

В `bot.py` к импортам добавить:

```python
import itertools
from collections import OrderedDict

import analysis
import routes
```

(`analysis` может быть уже импортирован — проверить и не дублировать; `routes` понадобится в задаче 5, но импорт удобнее добавить сразу.)

Рядом с `ROUTE_HELP` добавить:

```python
_ROUTE_CACHE_MAX = 8
_route_cache: "OrderedDict[str, dict]" = OrderedDict()
_route_token = itertools.count(1)


def _remember_route(points, name, date, departure):
    """Положить ЗАПРОС в кэш и вернуть короткий токен для callback_data.

    Хранится запрос, а не готовый профиль. Погода уже лежит в forecast._rcache,
    поэтому пересчёт профиля по нажатию кнопки — чистый процессор и ноль
    обращений к API. Взамен «другое время вылета» становится тем же вызовом
    get_route с другим departure, а не отдельной веткой кода, и расхождений
    между показанной карточкой и данными кнопки быть не может.
    """
    token = format(next(_route_token), "x")
    _route_cache[token] = {"points": points, "name": name,
                           "date": date, "departure": departure}
    while len(_route_cache) > _ROUTE_CACHE_MAX:
        _route_cache.popitem(last=False)
    return token


def _route_keyboard(token, profile):
    """Кнопки под карточкой: характерные точки, разрез, разбор, другое время."""
    rows = []
    marks = [_btn(f"{k['mark']} {k['km']:.0f}", f"rt|{token}|pt|{k['km']:.0f}")
             for k in route.key_points(profile)]
    marks = [b for b in marks if b]
    if marks:
        rows.append(marks)
    actions = [_btn("📈 Разрез", f"rt|{token}|sec")]
    if analysis.available():
        actions.append(_btn("🤖 Разбор", f"rt|{token}|ai"))
    if profile.get("departure_scan"):
        actions.append(_btn("🕐 Другое время", f"rt|{token}|dep"))
    actions = [b for b in actions if b]
    if actions:
        rows.append(actions)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def _profile_from_token(cb: CallbackQuery, token: str, departure=None):
    """Пересчитать профиль по токену. None (и ответ пользователю), если токена нет."""
    entry = _route_cache.get(token)
    if entry is None:
        await cb.answer("Маршрут устарел, посчитай заново: /route", show_alert=True)
        return None
    dep = entry["departure"] if departure is None else departure
    return await forecast.get_route(entry["points"], entry["name"], entry["date"], dep)
```

Заменить `_send_route`:

```python
async def _send_route(message: Message, points, name, date, departure):
    try:
        profile = await forecast.get_route(points, name, date, departure)
    except forecast.ForecastError as e:
        return await message.answer(str(e))
    token = _remember_route(points, name, date, departure)
    chunks = list(_chunks(route.render_card(profile)))
    for chunk in chunks[:-1]:
        await message.answer(chunk)
    await message.answer(chunks[-1], reply_markup=_route_keyboard(token, profile))
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: всё зелёное.

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_route_buttons.py
git commit -m "feat(bot): токен маршрута и клавиатура под карточкой"
```

---

## Task 5: Команды сохранённых маршрутов

**Files:**
- Modify: `route.py` (переименование `_plural` → `plural`), `bot.py`
- Test: `tests/test_route_saved_dialog.py`

**Interfaces:**
- Consumes: `routes.list_all/save/get/delete`, `route.total_km`, `bot._route_cache`, `bot.name_error`, `bot._send_route`.
- Produces: `route.plural(n, one, few, many) -> str` (публичная, `_plural` больше нет), команды `/saveroute`, `/routes`, `/delroute`, разбор имени в `/route`, обработчик `rr|<имя>`.

- [ ] **Step 1: Write the failing test**

Создать `tests/test_route_saved_dialog.py`:

```python
"""Команды сохранённых маршрутов."""
import datetime as dt

import pytest

import bot as botmod
import forecast
import route
import routes
from fixtures import om_route
from tg import buttons, callback_update, keyboards, text_update, texts

DATE = dt.date.today().isoformat()
BODY = ("/route\n"
        "42.4776, 44.4787, старт\n"
        "42.1176, 44.4787, финиш")
PTS = [route.Point(42.4776, 44.4787, "старт"), route.Point(42.1176, 44.4787, "финиш")]


def _n(url):
    return url.split("latitude=")[1].split("&")[0].count(",") + 1


@pytest.fixture()
def api(monkeypatch):
    async def fake_weather(url):
        return om_route(_n(url))

    async def fake_terrain(coords):
        return [1000.0] * len(coords)

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)


async def test_saveroute_without_a_computed_route_says_so(bot, session):
    await botmod.dp.feed_update(bot, text_update("/saveroute Гудаури"))
    assert "/route" in texts(session)[-1]


async def test_saveroute_stores_the_last_computed_route(bot, session, api):
    await botmod.dp.feed_update(bot, text_update(BODY))
    await botmod.dp.feed_update(bot, text_update("/saveroute Гудаури"))
    assert routes.get("Гудаури") is not None
    assert "Гудаури" in texts(session)[-1]


async def test_saveroute_needs_a_name(bot, session, api):
    await botmod.dp.feed_update(bot, text_update(BODY))
    await botmod.dp.feed_update(bot, text_update("/saveroute"))
    assert routes.list_all() == {}


async def test_saveroute_refuses_a_name_that_breaks_buttons(bot, session, api):
    await botmod.dp.feed_update(bot, text_update(BODY))
    await botmod.dp.feed_update(bot, text_update("/saveroute " + "я" * 40))
    assert routes.list_all() == {}
    assert "❌" in texts(session)[-1]


async def test_routes_lists_what_is_saved(bot, session):
    routes.save("Гудаури", PTS)
    await botmod.dp.feed_update(bot, text_update("/routes"))
    out = texts(session)[-1]
    assert "Гудаури" in out and "км" in out


async def test_routes_offers_a_button_per_route(bot, session):
    routes.save("Гудаури", PTS)
    await botmod.dp.feed_update(bot, text_update("/routes"))
    assert [b.callback_data for b in buttons(keyboards(session)[-1])] == ["rr|Гудаури"]


async def test_routes_when_empty_points_at_saveroute(bot, session):
    await botmod.dp.feed_update(bot, text_update("/routes"))
    assert "/saveroute" in texts(session)[-1]


async def test_the_button_computes_the_saved_route(bot, session, api):
    routes.save("Гудаури", PTS)
    await botmod.dp.feed_update(bot, callback_update("rr|Гудаури"))
    assert any("Гудаури" in t for t in texts(session))


async def test_delroute_removes_it(bot, session):
    routes.save("Гудаури", PTS)
    await botmod.dp.feed_update(bot, text_update("/delroute Гудаури"))
    assert routes.list_all() == {}


async def test_delroute_of_an_unknown_name_lists_the_known_ones(bot, session):
    routes.save("Гудаури", PTS)
    await botmod.dp.feed_update(bot, text_update("/delroute Казбеги"))
    assert "Гудаури" in texts(session)[-1]


async def test_route_by_saved_name(bot, session, api):
    routes.save("Гудаури", PTS)
    await botmod.dp.feed_update(bot, text_update("/route Гудаури"))
    assert any("🗺" in t for t in texts(session))


async def test_route_by_saved_name_with_date_and_time(bot, session, api):
    routes.save("Гудаури", PTS)
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    await botmod.dp.feed_update(bot, text_update("/route Гудаури завтра 11:30"))
    card = next(t for t in texts(session) if "🗺" in t)
    assert "11:30" in card


async def test_a_multi_word_name_still_resolves(bot, session, api):
    """Имя из нескольких слов — обычное дело: «Гудаури → Пасанаури»."""
    routes.save("Гудаури Пасанаури", PTS)
    await botmod.dp.feed_update(bot, text_update("/route Гудаури Пасанаури завтра"))
    assert any("🗺" in t for t in texts(session))


async def test_an_unknown_name_falls_back_to_the_help(bot, session):
    await botmod.dp.feed_update(bot, text_update("/route Казбеги"))
    assert "координат" in texts(session)[-1]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
set -o pipefail; python -m pytest tests/test_route_saved_dialog.py -x -q 2>&1 | tail -20
```

Expected: FAIL — команда `/saveroute` не зарегистрирована, бот отвечает «Не понял».

- [ ] **Step 3: Implement**

В `route.py` переименовать `_plural` в `plural` (объявление и оба вызова внутри `render_card`). Тело и комментарий не трогать:

```python
def plural(n, one, few, many):
    """«1 точка», «3 точки», «5 точек» — иначе карточка читается как машинный вывод."""
```

В `bot.py` добавить рядом с `_parse_when`:

```python
def _saved_route_from_args(args):
    """«Гудаури Пасанаури завтра 11:30» → (точки, имя, остаток строки).

    Имя примеряется целиком, потом без последнего слова, и так далее: иначе
    маршрут с именем из нескольких слов вызвать было бы нельзя. Не нашлось —
    (None, None, исходные аргументы).
    """
    words = (args or "").split()
    for cut in range(len(words), 0, -1):
        name = " ".join(words[:cut])
        pts = routes.get(name)
        if pts:
            return pts, name, " ".join(words[cut:])
    return None, None, args or ""
```

Заменить тело `cmd_route` (первые строки — до разбора текста):

```python
@dp.message(Command("route"), flags={"forecast": True})
async def cmd_route(message: Message, command: CommandObject):
    body = "\n".join((message.text or "").splitlines()[1:])
    if not body.strip():
        pts, name, rest = _saved_route_from_args(command.args)
        if pts is None:
            return await message.answer(ROUTE_HELP)
        date, departure = _parse_when(rest)
        return await _send_route(message, pts, name, date, departure)
    date, departure = _parse_when(command.args or "")
    try:
        points = route.parse_text(body, first_line_no=2)  # первая строка — сама команда
    except route.RouteError as e:
        return await message.answer(f"❌ {e}")
    await _send_route(message, points, None, date, departure)
```

Добавить три команды и обработчик кнопки (после `cmd_route`):

```python
@dp.message(Command("saveroute"), flags={"forecast": True})
async def cmd_saveroute(message: Message, command: CommandObject):
    name = (command.args or "").strip()
    if not name:
        return await message.answer("Как назвать маршрут? /saveroute <имя>")
    err = name_error(name)
    if err:
        return await message.answer(f"❌ {err}")
    if not _route_cache:
        return await message.answer("Сначала посчитай маршрут через /route.")
    entry = next(reversed(_route_cache.values()))
    existed = name in routes.list_all()
    try:
        routes.save(name, entry["points"])
    except ValueError as e:
        return await message.answer(f"❌ {e}")
    n = len(entry["points"])
    await message.answer(("Перезаписал" if existed else "Сохранил") +
                         f" маршрут «{name}»: {n} "
                         f"{route.plural(n, 'точка', 'точки', 'точек')}.")


@dp.message(Command("routes"), flags={"forecast": True})
async def cmd_routes(message: Message):
    saved = routes.list_all()
    if not saved:
        return await message.answer(
            "Сохранённых маршрутов нет. Посчитай маршрут через /route "
            "и сохрани: /saveroute <имя>")
    lines, rows = [], []
    for name in sorted(saved):
        pts = routes.get(name) or []
        n = len(pts)
        lines.append(f"• {name} — {route.total_km(pts):.0f} км, {n} "
                     f"{route.plural(n, 'точка', 'точки', 'точек')}, "
                     f"{saved[name].get('saved', '—')}")
        btn = _btn(name, f"rr|{name}")
        if btn:
            rows.append([btn])
    await message.answer(
        "🗂 Сохранённые маршруты:\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None)


@dp.message(Command("delroute"), flags={"forecast": True})
async def cmd_delroute(message: Message, command: CommandObject):
    name = (command.args or "").strip()
    if routes.delete(name):
        return await message.answer(f"Удалил маршрут «{name}».")
    known = ", ".join(sorted(routes.list_all())) or "пусто"
    await message.answer(f"Нет такого маршрута. Сохранённые: {known}")


@dp.callback_query(F.data.startswith("rr|"))
async def cb_saved_route(cb: CallbackQuery):
    name = cb.data.split("|", 1)[1]
    await cb.answer()
    msg = await cb_message(cb)
    if msg is None:
        return
    pts = routes.get(name)
    if not pts:
        return await msg.answer("Маршрут не читается — сохрани его заново.")
    await _send_route(msg, pts, name, dt.date.today().isoformat(), None)
```

В `BOT_COMMANDS` добавить три записи, в `HELP` — три строки:

```python
    BotCommand(command="routes", description="сохранённые маршруты"),
    BotCommand(command="saveroute", description="сохранить последний маршрут"),
    BotCommand(command="delroute", description="удалить маршрут"),
```

```
/routes — сохранённые маршруты
/saveroute <имя> — сохранить последний посчитанный маршрут
/delroute <имя> — удалить сохранённый маршрут
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: всё зелёное.

- [ ] **Step 5: Commit**

```bash
git add route.py bot.py tests/test_route_saved_dialog.py
git commit -m "feat(bot): команды сохранённых маршрутов"
```

---

## Task 6: Разбор KML

**Files:**
- Modify: `route.py`, `bot.py`
- Test: `tests/test_route_kml.py`

**Interfaces:**
- Consumes: `route._tag`, `route._find_all`, `route._child_name`, `route._thin`, `route._checked_count`, `route.MAX_GPX_BYTES`, `route.RouteError`.
- Produces: `route.parse_kml(data) -> (list[route.Point], str | None)`; обработчик документов в `bot.py` принимает `.gpx` и `.kml`.

- [ ] **Step 1: Write the failing test**

Создать `tests/test_route_kml.py`:

```python
"""Разбор KML. Главная ловушка формата — порядок «долгота,широта»."""
import pytest

import route

LINE = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<name>Гудаури тур</name>
<Placemark><name>трек</name><LineString><coordinates>
44.4787,42.4776,2196 44.5513,42.3428,2510 44.6890,42.2104,1050
</coordinates></LineString></Placemark>
</Document></kml>"""

PINS = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>старт</name><Point><coordinates>44.4787,42.4776</coordinates></Point></Placemark>
<Placemark><name>финиш</name><Point><coordinates>44.6890,42.2104</coordinates></Point></Placemark>
</Document></kml>"""

BARE = """<?xml version="1.0"?><kml><Folder>
<coordinates>44.4787,42.4776 44.6890,42.2104</coordinates>
</Folder></kml>"""


def test_longitude_comes_first_in_kml():
    """Перепутать порядок значит молча улететь в другое полушарие."""
    pts, _name = route.parse_kml(LINE.encode())
    assert pts[0].lat == pytest.approx(42.4776)
    assert pts[0].lon == pytest.approx(44.4787)
    assert pts[-1].lat == pytest.approx(42.2104)
    assert pts[-1].lon == pytest.approx(44.6890)


def test_all_line_points_are_read():
    pts, _name = route.parse_kml(LINE.encode())
    assert len(pts) == 3


def test_altitude_in_the_third_field_is_ignored():
    """Высоту берём из DEM, а не из файла: в KML она бывает над эллипсоидом."""
    pts, _name = route.parse_kml(LINE.encode())
    assert all(not hasattr(p, "alt") for p in pts)
    assert pts[0].lat == pytest.approx(42.4776)


def test_document_name_wins():
    _pts, name = route.parse_kml(LINE.encode())
    assert name == "Гудаури тур"


def test_placemark_points_are_read_with_their_names():
    pts, _name = route.parse_kml(PINS.encode())
    assert [p.name for p in pts] == ["старт", "финиш"]


def test_placemark_name_is_used_when_the_document_has_none():
    _pts, name = route.parse_kml(PINS.encode())
    assert name == "старт"


def test_a_line_wins_over_scattered_points():
    both = LINE.replace("</Document>",
                        "<Placemark><Point><coordinates>1,1</coordinates>"
                        "</Point></Placemark></Document>")
    pts, _name = route.parse_kml(both.encode())
    assert len(pts) == 3
    assert all(p.lat > 40 for p in pts)


def test_bare_coordinates_are_the_last_resort():
    pts, name = route.parse_kml(BARE.encode())
    assert len(pts) == 2
    assert name is None


def test_namespaces_do_not_matter():
    ns = LINE.replace("<kml xmlns=", "<kml xmlns:x=").replace(
        "http://www.opengis.net/kml/2.2", "http://earth.google.com/kml/2.1")
    pts, _name = route.parse_kml(ns.encode())
    assert len(pts) == 3


def test_a_document_without_coordinates_is_refused():
    with pytest.raises(route.RouteError, match="нет"):
        route.parse_kml(b"<kml><Document><name>пусто</name></Document></kml>")


def test_broken_xml_is_refused():
    with pytest.raises(route.RouteError, match="разобрать"):
        route.parse_kml(b"<kml><Document>")


def test_a_single_point_is_refused():
    one = PINS.replace(
        '<Placemark><name>финиш</name><Point>'
        '<coordinates>44.6890,42.2104</coordinates></Point></Placemark>', "")
    with pytest.raises(route.RouteError, match="минимум"):
        route.parse_kml(one.encode())


def test_entity_declarations_are_refused():
    """Килобайт вложенных сущностей разворачивается в гигабайты («billion laughs»)."""
    bomb = (b'<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY a "aaaa">]>'
            b"<kml><coordinates>44,42 45,43</coordinates></kml>")
    with pytest.raises(route.RouteError, match="DOCTYPE"):
        route.parse_kml(bomb)


def test_an_oversized_file_is_refused():
    with pytest.raises(route.RouteError, match="КБ"):
        route.parse_kml(b"x" * (route.MAX_GPX_BYTES + 1))


def test_a_long_track_is_thinned_to_the_cap():
    coords = " ".join(f"{44.0 + i / 1000.0},{42.0 + i / 1000.0}" for i in range(500))
    doc = (f'<kml><Document><Placemark><LineString><coordinates>{coords}'
           "</coordinates></LineString></Placemark></Document></kml>")
    pts, _name = route.parse_kml(doc.encode())
    assert len(pts) == route.MAX_POINTS


def test_garbage_triples_are_skipped_not_fatal():
    doc = ("<kml><coordinates>44.4787,42.4776 мусор 44.6890,42.2104"
           "</coordinates></kml>")
    pts, _name = route.parse_kml(doc.encode())
    assert len(pts) == 2
```

Дописать в `tests/test_route_dialog.py`:

```python
async def test_a_kml_document_is_parsed(bot, session, monkeypatch, api):
    """KML-файл маршрута должен обрабатываться так же, как GPX."""
    doc = ('<kml><Document><name>тур</name><Placemark><LineString><coordinates>'
           '44.4787,42.4776 44.4787,42.1176</coordinates></LineString>'
           "</Placemark></Document></kml>")
    await _send_document(bot, monkeypatch, "route.kml", doc.encode())
    assert any("🗺" in t for t in texts(session))


async def test_a_kmz_document_is_refused_with_advice(bot, session, monkeypatch):
    await _send_document(bot, monkeypatch, "route.kmz", b"PK\x03\x04")
    assert ".kml" in texts(session)[-1]


async def test_an_unknown_extension_names_both_formats(bot, session, monkeypatch):
    await _send_document(bot, monkeypatch, "route.txt", b"nope")
    assert "GPX" in texts(session)[-1] and "KML" in texts(session)[-1]
```

`_send_document` — вспомогательная функция; если её в файле ещё нет, добавить рядом с существующим тестом GPX-документа, повторив тот способ подмены `message.bot.download`, который там уже используется.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
set -o pipefail; python -m pytest tests/test_route_kml.py -x -q 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: module 'route' has no attribute 'parse_kml'`.

- [ ] **Step 3: Implement**

В `route.py` после `parse_gpx` добавить:

```python
# ---------------------------------------------------------------- KML
def _kml_coords(text):
    """«долгота,широта[,высота] ...» → [(широта, долгота), ...].

    Порядок в KML обратный GPX, и это главная ловушка формата: перепутать —
    значит молча улететь в другое полушарие. Высота игнорируется: рельеф
    берётся из DEM, а в файлах она бывает то над геоидом, то над эллипсоидом.
    """
    out = []
    for chunk in (text or "").replace("\n", " ").split():
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        out.append((lat, lon))
    return out


def _kml_points(el, name=None):
    out = []
    for c in el.iter():
        if _tag(c) == "coordinates":
            out += [Point(lat, lon, name) for lat, lon in _kml_coords(c.text)]
    return out


def parse_kml(data):
    """KML → (точки, имя маршрута). Приоритет: <LineString> → <Point> → любые
    <coordinates> — та же логика «маршрут важнее трека важнее точек», что у GPX."""
    if len(data) > MAX_GPX_BYTES:
        raise RouteError(f"файл больше {MAX_GPX_BYTES // 1024} КБ — пришли маршрут покороче")
    # Та же защита от «billion laughs», что и в parse_gpx: килобайтный файл с
    # вложенными <!ENTITY> разворачивается в гигабайты и съедает память бота.
    if b"<!DOCTYPE" in data[:4096].upper() or b"<!ENTITY" in data.upper():
        raise RouteError("в файле есть объявления DOCTYPE или сущностей — "
                         "такой KML не разбираю")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise RouteError(f"не удалось разобрать KML: {e}") from None

    marks = _find_all(root, "placemark")
    name = next((_child_name(d) for d in _find_all(root, "document")
                 if _child_name(d)), None)
    if name is None:
        name = next((_child_name(pm) for pm in marks if _child_name(pm)), None)

    line = []
    for ls in _find_all(root, "linestring"):
        line += _kml_points(ls)
    if line:
        return _checked_count(_thin(line, MAX_POINTS)), name

    pins = []
    for pm in marks:
        for pt in (el for el in pm.iter() if _tag(el) == "point"):
            pins += _kml_points(pt, _child_name(pm))
    if pins:
        return _checked_count(_thin(pins, MAX_POINTS)), name

    loose = _kml_points(root)
    if loose:
        return _checked_count(_thin(loose, MAX_POINTS)), name
    raise RouteError("в KML нет ни линии маршрута, ни точек")
```

В `bot.py` заменить `route_gpx_document`:

```python
_DOC_PARSERS = ((".gpx", route.parse_gpx), (".kml", route.parse_kml))


@dp.message(F.document, flags={"forecast": True})
async def route_document(message: Message):
    doc = message.document
    fname = (doc.file_name or "").lower()
    if fname.endswith(".kmz"):
        return await message.answer("KMZ — это архив. Распакуй и пришли .kml")
    parser = next((p for ext, p in _DOC_PARSERS if fname.endswith(ext)), None)
    if parser is None:
        return await message.answer("Я понимаю маршруты в форматах GPX и KML.")
    if (doc.file_size or 0) > route.MAX_GPX_BYTES:
        return await message.answer(
            f"❌ файл больше {route.MAX_GPX_BYTES // 1024} КБ — пришли маршрут покороче")
    buf = io.BytesIO()
    await message.bot.download(doc, destination=buf)
    try:
        points, name = parser(buf.getvalue())
    except route.RouteError as e:
        return await message.answer(f"❌ {e}")
    date, departure = _parse_when(message.caption or "")
    await _send_route(message, points, name, date, departure)
```

Обновить `ROUTE_HELP`: «GPX-файл тоже подойдёт» → «Файл GPX или KML тоже подойдёт.»

- [ ] **Step 4: Run the tests to verify they pass**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: всё зелёное.

- [ ] **Step 5: Commit**

```bash
git add route.py bot.py tests/test_route_kml.py tests/test_route_dialog.py
git commit -m "feat(route): разбор KML"
```

---

## Task 7: Карточка отдельной точки

**Files:**
- Modify: `route.py`, `bot.py`
- Test: `tests/test_route_point_card.py`

**Interfaces:**
- Consumes: `criteria.PARAMS`, `criteria.CATEGORIES`, `engine.card`, `route.CARD_WIDTH`, `route._wrap`.
- Produces: `route.ROLE_RU`, `route.render_point_card(profile, km) -> str | None`; обработчик кнопки `rt|<токен>|pt|<км>`.

- [ ] **Step 1: Write the failing test**

Создать `tests/test_route_point_card.py`:

```python
"""Карточка отдельной точки: почему у неё такой балл."""
import route


def profile(**over):
    pts = []
    for i, km in enumerate([0.0, 40.0, 78.0]):
        pts.append({
            "km": km, "eta": f"1{i + 1}:00", "eta_fixed": f"1{i + 1}:00",
            "role": ["takeoff", "enroute", "goal"][i],
            "is_turnpoint": i in (0, 2), "is_terrain_peak": i == 1,
            "wind_along_kmh": [5.2, -8.4, -17.2][i],
            "wind_cross_kmh": [-17.1, -24.6, -19.4][i],
            "wind_working_alt_kmh": [18.0, 26.0, 34.0][i],
            "wind_working_alt_dir": [232.0, 268.0, 272.0][i],
            "effective_ground_speed_kmh": [30.2, 16.6, 7.8][i],
            "w_star_ms": [1.8, 2.7, 0.9][i],
            "terrain_m": [2196, 2510, 1050][i],
            "cloud_base_m": [3626, 3230, 2960][i],
            "thermal_ceiling_m": [3696, 4260, 2450][i],
            "working_band_m": [1130, 420, 1610][i],
            "time_margin_min": [330, 210, 95][i],
            "score": [79, 61, 44][i],
            "category": ["excellent", "fair", "marginal"][i],
            "limiting": "рабочий диапазон",
            "vetoes": [], "storm_ahead": None,
            "subs": {"working_band": 38.0, "wind_along": 54.0, "thermals": 72.0,
                     "clouds": 90.0},
            "groups": {"wind_along": 54.0},
            "weather": {"precipitation": 0.0, "cape": 850.0, "lifted_index": -3.2,
                        "convective_inhibition": 35.0, "visibility": 25000.0,
                        "cloud_cover_low": 40.0, "cloud_cover_mid": 20.0,
                        "wind_speed_10m": 4.7, "wind_gusts_10m": 6.1},
        })
    p = {"points": pts, "route": {"name": "Тест"}, "verdict": {}}
    p.update(over)
    return p


def card(km=40.0, **over):
    return route.render_point_card(profile(**over), km)


def test_every_line_fits_the_mobile_width():
    for km in (0.0, 40.0, 78.0):
        text = route.render_point_card(profile(), km)
        assert max(len(ln) for ln in text.splitlines()) <= route.CARD_WIDTH


def test_head_names_kilometre_time_and_role():
    text = card()
    assert "40 км" in text and "12:00" in text and "маршрут" in text


def test_roles_are_named_in_russian():
    assert "старт" in card(0.0)
    assert "финиш" in card(78.0)


def test_score_and_category_are_shown():
    assert "61" in card() and "удовлетворительная" in card()


def test_limiting_factor_is_named():
    assert "рабочий диапазон" in card()


def test_heights_are_present_here_on_purpose():
    """Из таблицы маршрута высоты убраны, но эту карточку открывают ради них."""
    text = card()
    assert "3230" in text and "2510" in text and "420" in text


def test_wind_along_and_cross_carry_their_signs():
    text = card()
    assert "←" in text and "8" in text
    assert "25" in text or "24" in text


def test_wind_direction_is_shown_as_a_compass_point():
    assert "З" in card()


def test_ground_wind_only_for_takeoff_and_goal():
    """В воздухе наземный ветер в оценке не участвует — печатать его значит
    предлагать решение по числу, которое ни на что не влияет."""
    assert "Земля" in card(0.0)
    assert "Земля" in card(78.0)
    assert "Земля" not in card(40.0)


def test_terrain_peak_is_marked():
    assert "▲" in card(40.0)
    assert "▲" not in card(0.0)


def test_storm_numbers_are_shown():
    text = card()
    assert "CAPE" in text and "850" in text


def test_worst_subscores_are_listed_lowest_first():
    text = card()
    tail = text.split("Что тянет вниз:")[1]
    assert tail.index("38") < tail.index("54") < tail.index("72")


def test_only_three_subscores():
    tail = card().split("Что тянет вниз:")[1]
    assert "90" not in tail


def test_missing_values_read_as_unknown_not_as_absent():
    p = profile()
    p["points"][1]["cloud_base_m"] = None
    p["points"][1]["wind_working_alt_dir"] = None
    text = route.render_point_card(p, 40.0)
    assert text.count("н/д") >= 2


def test_vetoes_are_shown_and_wrapped():
    p = profile()
    p["points"][1]["vetoes"] = ["база ниже безопасной высоты над рельефом"]
    text = route.render_point_card(p, 40.0)
    assert "база ниже" in text
    assert max(len(ln) for ln in text.splitlines()) <= route.CARD_WIDTH


def test_an_unknown_kilometre_gives_nothing():
    assert route.render_point_card(profile(), 999.0) is None


def test_a_point_without_a_score_still_renders():
    p = profile()
    p["points"][1].update({"score": None, "category": None, "limiting": None,
                           "subs": {}, "groups": {}})
    assert "40 км" in route.render_point_card(p, 40.0)
```

Дописать в `tests/test_route_buttons.py`:

```python
async def test_a_point_button_answers_with_the_point_card(bot, session, api):
    await botmod.dp.feed_update(bot, text_update(BODY))
    token = _last_token()
    await botmod.dp.feed_update(bot, callback_update(f"rt|{token}|pt|0"))
    assert any("📍" in t for t in texts(session))


async def test_a_lost_token_says_so_instead_of_going_quiet(bot, session, api):
    await botmod.dp.feed_update(bot, callback_update("rt|неттакого|pt|0"))
    assert cb_answers(session)
    assert "устарел" in cb_answers(session)[-1].text
```

и добавить `callback_update` в импорт `tg` в этом файле.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
set -o pipefail; python -m pytest tests/test_route_point_card.py -x -q 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: module 'route' has no attribute 'render_point_card'`.

- [ ] **Step 3: Implement**

В `route.py` после `render_card` добавить:

```python
# ---------------------------------------------------------------- карточка точки
ROLE_RU = {"takeoff": "старт", "enroute": "маршрут", "goal": "финиш"}
SUBS_SHOWN = 3

# Категория → (эмодзи, название). Берётся из criteria.CATEGORIES, чтобы своей
# копии названий здесь не заводилось.
_CAT = {key: (emoji, label) for key, _lo, emoji, label in criteria.CATEGORIES}


def _pair(label, value):
    """Строка «подпись … значение» по ширине карточки."""
    gap = CARD_WIDTH - len(label) - len(value)
    return label + " " * max(1, gap) + value


def _num(v, unit, fmt="{:.0f}"):
    return "н/д" if v is None else (fmt.format(v) + " " + unit).replace(".", ",")


def _point_by_km(profile, km):
    return next((p for p in profile.get("points") or []
                 if abs(p["km"] - km) < _KM_EPS), None)


def _worst_subs(p, limit=SUBS_SHOWN):
    """Самые низкие субоценки с русскими названиями параметров."""
    subs = (p.get("subs") or {})
    ranked = sorted((v, k) for k, v in subs.items() if v is not None)
    out = []
    for value, key in ranked[:limit]:
        param = criteria.PARAMS.get(key)
        out.append((param.label if param else key, value))
    return out


def render_point_card(profile, km):
    """Подробности одной точки маршрута. None, если такой точки нет.

    Высоты здесь есть намеренно. Из таблицы маршрута их убрали потому, что там
    их было десять и они мешали читать погоду; сюда пилот приходит сам, чтобы
    разобраться в диапазоне и запасе, — без чисел ответить нечем.
    """
    p = _point_by_km(profile, km)
    if p is None:
        return None
    w = p.get("weather") or {}
    out = [f"📍 {p['km']:.0f} км · {p.get('eta') or '—'} · "
           f"{ROLE_RU.get(p.get('role'), p.get('role') or '')}",
           "─" * CARD_WIDTH]

    if p.get("score") is not None:
        emoji, label = _CAT.get(p.get("category"), ("", p.get("category") or ""))
        out.append(f"{emoji} {p['score']:.0f} {label}")
    if p.get("limiting"):
        out += _wrap(f"Ограничивает: {p['limiting']}", indent="")
    for veto in p.get("vetoes") or []:
        out.append("⛔")
        out += _wrap(veto)
    out.append("")

    deg, spd = p.get("wind_working_alt_dir"), p.get("wind_working_alt_kmh")
    alt = p.get("thermal_ceiling_m")
    head = "Ветер" if alt is None else f"Ветер {alt:.0f} м"
    out.append(_pair(head, "н/д" if deg is None or spd is None
                     else f"{spd:.0f} км/ч {engine.card(deg)}"))
    along, cross = p.get("wind_along_kmh"), p.get("wind_cross_kmh")
    out.append(_pair("  вдоль курса",
                     "н/д" if along is None
                     else f"{abs(along):.0f} км/ч {'→' if along >= 0 else '←'}"))
    out.append(_pair("  поперёк",
                     "н/д" if cross is None
                     else f"{abs(cross):.0f} км/ч {'→' if cross >= 0 else '←'}"))
    if p.get("role") in ("takeoff", "goal"):
        gust = w.get("wind_gusts_10m")
        ground = w.get("wind_speed_10m")
        out.append(_pair("Земля", "н/д" if ground is None else
                         f"{ms_to_kmh(ground):.0f}" +
                         ("" if gust is None else f"/{ms_to_kmh(gust):.0f}") + " км/ч"))
    out.append(_pair("Потоки", _num(p.get("w_star_ms"), "м/с", "{:.1f}")))
    out.append(_pair("Скорость по земле",
                     _num(p.get("effective_ground_speed_kmh"), "км/ч")))
    out.append(_pair("База", _num(p.get("cloud_base_m"), "м")))
    peak = " ▲" if p.get("is_terrain_peak") else ""
    out.append(_pair("Рельеф", _num(p.get("terrain_m"), "м") + peak))
    out.append(_pair("Коридор", _num(p.get("working_band_m"), "м")))
    out.append(_pair("Запас времени", _num(p.get("time_margin_min"), "мин")))
    out.append("")

    out.append(f"CAPE {w.get('cape', 0):.0f} · LI "
               f"{w.get('lifted_index', 0):.1f} · CIN "
               f"{w.get('convective_inhibition', 0):.0f}".replace(".", ","))
    out.append(f"Облачность {w.get('cloud_cover_low', 0):.0f}/"
               f"{w.get('cloud_cover_mid', 0):.0f} · дождь "
               f"{w.get('precipitation', 0):.1f}".replace(".", ","))
    vis = w.get("visibility")
    out.append(_pair("Видимость", "н/д" if vis is None else f"{vis / 1000.0:.0f} км"))

    worst = _worst_subs(p)
    if worst:
        out += ["", "Что тянет вниз:"]
        for label, value in worst:
            out.append(_pair(f"  {label}", f"{value:.0f}"))
    return "\n".join(out)
```

Убедиться, что длинные подписи не выбивают ширину: `_pair` гарантирует минимум один пробел, но не режет — если сумма длин больше 32, строка станет длиннее. Названия параметров из `criteria.PARAMS` длиннее 26 символов не встречаются; тест на ширину это проверяет и упадёт, если такое появится.

В `bot.py` добавить обработчик:

```python
@dp.callback_query(F.data.regexp(r"^rt\|[^|]+\|pt\|"))
async def cb_route_point(cb: CallbackQuery):
    _p, token, _a, km = cb.data.split("|", 3)
    await cb.answer()
    msg = await cb_message(cb)
    if msg is None:
        return
    try:
        profile = await _profile_from_token(cb, token)
    except forecast.ForecastError as e:
        return await msg.answer(str(e))
    if profile is None:
        return
    text = route.render_point_card(profile, float(km))
    await msg.answer(text or "Точка не найдена — посчитай маршрут заново.")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: всё зелёное.

- [ ] **Step 5: Commit**

```bash
git add route.py bot.py tests/test_route_point_card.py tests/test_route_buttons.py
git commit -m "feat(route): карточка отдельной точки маршрута"
```

---

## Task 8: Отрисовка разреза

**Files:**
- Modify: `charts.py`
- Test: `tests/test_route_section_png.py`

**Interfaces:**
- Consumes: словарь профиля (`route`, `points`, `terrain`, `verdict`), `criteria.MIN_WORKING_ALT_AGL`, `charts._canvas`, `charts._save`, `charts._wind_arrow`, `charts.GRADE_RGB`.
- Produces: `charts.route_section_png(profile, out) -> str | None`.

- [ ] **Step 1: Write the failing test**

Создать `tests/test_route_section_png.py`:

```python
"""Разрез маршрута: рисуется, не падает, вырожденные данные переживает."""
import os

import pytest
from PIL import Image

import charts


def profile(n=5, terrain=True, **over):
    pts = []
    for i in range(n):
        pts.append({
            "km": float(i * 20), "eta": f"1{i}:00",
            "role": "takeoff" if i == 0 else ("goal" if i == n - 1 else "enroute"),
            "is_turnpoint": i in (0, n - 1), "is_terrain_peak": i == 2,
            "name": "старт" if i == 0 else None,
            "terrain_m": 2000 + i * 100,
            "cloud_base_m": 3600 - i * 100,
            "thermal_ceiling_m": 3800 - i * 120,
            "wind_working_alt_kmh": 18.0 + i, "wind_working_alt_dir": 230.0 + i,
            "category": ["excellent", "fair", "fair", "marginal", "no_fly"][i % 5],
            "score": 70 - i * 5, "vetoes": [],
        })
    grid_n = n * 20 + 1
    p = {
        "route": {"name": "Гудаури → Пасанаури", "date": "2026-07-28",
                  "departure": "11:00", "total_km": float((n - 1) * 20),
                  "timezone": "Asia/Tbilisi", "sample_step_km": 20.0},
        "points": pts,
        "terrain": ({"km": [float(i) for i in range(grid_n)],
                     "elevations": [2000.0 + (i % 30) * 10 for i in range(grid_n)]}
                    if terrain else None),
        "verdict": {"blocked_at_km": None, "bottleneck": {"km": 40.0, "score": 55}},
    }
    p.update(over)
    return p


def test_a_file_is_produced(tmp_path):
    path = charts.route_section_png(profile(), str(tmp_path))
    assert path and os.path.getsize(path) > 0


def test_the_image_has_the_expected_size(tmp_path):
    path = charts.route_section_png(profile(), str(tmp_path))
    assert Image.open(path).size == (1040, 660)


def test_no_terrain_no_picture(tmp_path):
    """Разрез без рельефа — это пустая рамка, лучше честно ничего не рисовать."""
    assert charts.route_section_png(profile(terrain=False), str(tmp_path)) is None


def test_an_empty_terrain_grid_gives_nothing(tmp_path):
    p = profile()
    p["terrain"] = {"km": [], "elevations": []}
    assert charts.route_section_png(p, str(tmp_path)) is None


def test_two_points_still_draw(tmp_path):
    assert charts.route_section_png(profile(n=2), str(tmp_path))


def test_a_collapsed_corridor_draws(tmp_path):
    """Коридор в минусе — самый важный случай, он обязан рисоваться."""
    p = profile()
    for pt in p["points"]:
        pt["cloud_base_m"] = pt["terrain_m"] - 50
    assert charts.route_section_png(p, str(tmp_path))


def test_missing_base_and_ceiling_do_not_crash(tmp_path):
    p = profile()
    p["points"][2]["cloud_base_m"] = None
    p["points"][2]["thermal_ceiling_m"] = None
    assert charts.route_section_png(p, str(tmp_path))


def test_missing_wind_does_not_crash(tmp_path):
    p = profile()
    for pt in p["points"]:
        pt["wind_working_alt_dir"] = None
        pt["wind_working_alt_kmh"] = None
    assert charts.route_section_png(p, str(tmp_path))


def test_a_blocked_route_draws(tmp_path):
    p = profile()
    p["verdict"] = {"blocked_at_km": 60.0, "bottleneck": {"km": 60.0, "score": 0},
                    "blocked_reason": "база ниже безопасной высоты"}
    assert charts.route_section_png(p, str(tmp_path))


def test_a_nameless_route_draws(tmp_path):
    p = profile()
    p["route"]["name"] = None
    assert charts.route_section_png(p, str(tmp_path))


def test_many_points_thin_the_arrows_instead_of_overlapping(tmp_path):
    """Пятьдесят стрелок в ряд слипаются в кашу — их должно стать не больше 12."""
    p = profile(n=50)
    assert len(charts._arrow_indexes(50)) <= 12
    assert charts.route_section_png(p, str(tmp_path))


def test_points_without_eta_draw(tmp_path):
    p = profile()
    p["points"][-1]["eta"] = None
    assert charts.route_section_png(p, str(tmp_path))
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
set -o pipefail; python -m pytest tests/test_route_section_png.py -x -q 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: module 'charts' has no attribute 'route_section_png'`.

- [ ] **Step 3: Implement**

В `charts.py` к палитре добавить два цвета:

```python
TERRAIN = (150, 142, 128)   # заливка рельефа
BAND    = (110, 170, 210)   # заливка рабочего коридора
```

В конец файла добавить:

```python
# ---------------------------------------------------------------- разрез маршрута
ARROWS_MAX = 12             # больше стрелок в ряд слипаются в кашу


def _arrow_indexes(n):
    """Индексы точек, у которых рисуется стрелка ветра."""
    step = max(1, math.ceil(n / ARROWS_MAX))
    return list(range(0, n, step))


def _runs(xs, ys):
    """Непрерывные куски (x, y), обрывающиеся на None.

    Соединять через пропуск нельзя: это рисование данных, которых нет.
    """
    out, cur = [], []
    for x, y in zip(xs, ys):
        if y is None:
            if len(cur) > 1:
                out.append(cur)
            cur = []
        else:
            cur.append((x, y))
    if len(cur) > 1:
        out.append(cur)
    return out


def route_section_png(profile, out):
    """Разрез вдоль маршрута: рельеф, безопасная высота, рабочий коридор,
    потолок термиков и база, ветер, время прилёта и лента лётности.

    None, если рельефа нет: без него на картинке остаётся пустая рамка.
    """
    terrain = profile.get("terrain") or {}
    tkm, telev = terrain.get("km") or [], terrain.get("elevations") or []
    if not tkm or not telev:
        return None
    pts, r = profile["points"], profile["route"]
    total = r.get("total_km") or tkm[-1] or 1.0

    skm = [p["km"] for p in pts]
    floor = [None if p.get("terrain_m") is None
             else p["terrain_m"] + _criteria.MIN_WORKING_ALT_AGL for p in pts]
    base = [p.get("cloud_base_m") for p in pts]
    ceil = [p.get("thermal_ceiling_m") for p in pts]
    top = [None if b is None and c is None
           else min(v for v in (b, c) if v is not None) for b, c in zip(base, ceil)]

    W, Ht = 1040, 660
    img, d = _canvas(W, Ht)
    L, R = 66, 30
    x0, x1 = S(L), S(W - R)
    y0, y1 = S(118), S(Ht - 176)
    highs = [v for v in list(base) + list(ceil) + list(floor) if v is not None]
    zmn = min(telev) - 100
    zmx = max(highs + [max(telev)]) + 200
    xf = lambda km: x0 + (x1 - x0) * km / max(total, 0.001)
    yf = lambda z: y1 - (y1 - y0) * (z - zmn) / max(zmx - zmn, 1.0)

    title = r.get("name") or "Маршрут"
    d.text((S(40), S(28)), f"{title} — разрез маршрута {r['date']}",
           font=_font(23, True), fill=INK, anchor="lm")
    d.text((S(40), S(56)),
           f"вылет {r.get('departure') or '—'} · {total:.0f} км · "
           f"стрелки — куда дует · {r.get('timezone', '')}",
           font=_font(13), fill=MUTED, anchor="lm")

    for z in range(int((zmn // 500 + 1) * 500), int(zmx), 500):
        yy = yf(z)
        d.line([x0, yy, x1, yy], fill=GRID, width=1)
        d.text((x0 - S(10), yy), f"{z}", font=_font(12), fill=FAINT, anchor="rm")
    d.text((x0 - S(10), y0 - S(4)), "м MSL", font=_font(11), fill=FAINT, anchor="rb")

    # рабочий коридор — по трапеции на каждый участок между расчётными точками
    for i in range(len(pts) - 1):
        f0, f1, t0, t1 = floor[i], floor[i + 1], top[i], top[i + 1]
        if None in (f0, f1, t0, t1):
            continue
        quad = [(xf(skm[i]), yf(f0)), (xf(skm[i + 1]), yf(f1)),
                (xf(skm[i + 1]), yf(t1)), (xf(skm[i]), yf(t0))]
        collapsed = t0 <= f0 or t1 <= f1
        d.polygon(quad, fill=(RAIN if collapsed else BAND) + (56 if collapsed else 40,))
        if collapsed:
            d.text(((xf(skm[i]) + xf(skm[i + 1])) / 2, yf(max(f0, f1)) - S(10)),
                   f"коридора нет · {skm[i]:.0f} км", font=_font(11, True),
                   fill=RAIN, anchor="mm")

    # рельеф — заливка по мелкой сетке
    ground = [(xf(km), yf(z)) for km, z in zip(tkm, telev)]
    d.polygon(ground + [(xf(tkm[-1]), y1), (xf(tkm[0]), y1)], fill=TERRAIN + (210,))

    for run in _runs(skm, floor):
        for a, b in zip(run, run[1:]):
            d.line([xf(a[0]), yf(a[1]), xf(b[0]), yf(b[1])], fill=MUTED, width=S(1))
    d.text((x1, yf(max(v for v in floor if v is not None)) - S(6)),
           f"безопасная высота (+{_criteria.MIN_WORKING_ALT_AGL} м)",
           font=_font(11), fill=MUTED, anchor="rb")

    for run in _runs(skm, ceil):
        d.line([(xf(x), yf(y)) for x, y in run], fill=GUST, width=S(3), joint="curve")
    for run in _runs(skm, base):
        d.line([(xf(x), yf(y)) for x, y in run], fill=WIND, width=S(3), joint="curve")
    if any(v is not None for v in ceil):
        d.text((x0 + S(6), yf(max(v for v in ceil if v is not None)) - S(8)),
               "потолок термиков", font=_font(12, True), fill=GUST, anchor="lb")
    if any(v is not None for v in base):
        d.text((x1 - S(6), yf(max(v for v in base if v is not None)) - S(8)),
               "база облаков", font=_font(12, True), fill=WIND, anchor="rb")

    # отметки: обрыв важнее узкого места, узкое место важнее поворотной точки
    v = profile.get("verdict") or {}
    marked = set()
    for km, colour, label in (
            (v.get("blocked_at_km"), RAIN, "обрыв"),
            ((v.get("bottleneck") or {}).get("km"), WARN, "узкое место")):
        if km is None or round(km, 1) in marked:
            continue
        marked.add(round(km, 1))
        d.line([xf(km), y0, xf(km), y1], fill=colour, width=S(2))
        d.text((xf(km), y0 - S(8)), f"{label}, {km:.0f} км",
               font=_font(11, True), fill=colour, anchor="mb")
    for p in pts:
        if not p.get("is_turnpoint") or round(p["km"], 1) in marked:
            continue
        marked.add(round(p["km"], 1))
        gy = yf(p["terrain_m"]) if p.get("terrain_m") is not None else y1
        d.polygon([(xf(p["km"]), gy - S(9)), (xf(p["km"]) - S(5), gy),
                   (xf(p["km"]) + S(5), gy)], fill=INK)
        if p.get("name"):
            d.text((xf(p["km"]), gy - S(12)), p["name"], font=_font(11),
                   fill=INK, anchor="mb")

    # полосы под панелью: стрелки, километры, время прилёта, лента лётности
    ya = y1 + S(26)
    for i in _arrow_indexes(len(pts)):
        p = pts[i]
        if p.get("wind_working_alt_dir") is None:
            continue
        _wind_arrow(d, xf(p["km"]), ya, p["wind_working_alt_dir"], S(9), WIND)
        d.text((xf(p["km"]), ya + S(20)), f"{p.get('wind_working_alt_kmh') or 0:.0f}",
               font=_font(11), fill=MUTED, anchor="mm")
        d.text((xf(p["km"]), ya + S(40)), f"{p['km']:.0f}",
               font=_font(12), fill=FAINT, anchor="mm")
        d.text((xf(p["km"]), ya + S(58)), p.get("eta") or "—",
               font=_font(11), fill=FAINT, anchor="mm")
    d.text((x0 - S(10), ya), "ветер", font=_font(11), fill=FAINT, anchor="rm")
    d.text((x0 - S(10), ya + S(40)), "км", font=_font(11), fill=FAINT, anchor="rm")
    d.text((x0 - S(10), ya + S(58)), "время", font=_font(11), fill=FAINT, anchor="rm")

    ry0, ry1 = S(Ht - 42), S(Ht - 22)
    for i, p in enumerate(pts):
        lo = skm[i] if i == 0 else (skm[i - 1] + skm[i]) / 2
        hi = skm[i] if i == len(pts) - 1 else (skm[i] + skm[i + 1]) / 2
        d.rectangle([xf(lo), ry0, xf(hi), ry1],
                    fill=GRADE_RGB.get(p.get("category"), MUTED) + (190,))
        if p.get("vetoes"):
            d.text(((xf(lo) + xf(hi)) / 2, (ry0 + ry1) / 2), "×",
                   font=_font(11, True), fill=BG, anchor="mm")
    d.text((x0 - S(10), (ry0 + ry1) / 2), "лётность", font=_font(11), fill=FAINT, anchor="rm")
    return _save(img, out, "06_route_section.png")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: всё зелёное.

- [ ] **Step 5: Commit**

```bash
git add charts.py tests/test_route_section_png.py
git commit -m "feat(charts): PNG-разрез вдоль маршрута"
```

---

## Task 9: Доставка разреза в Telegram

**Files:**
- Modify: `forecast.py`, `bot.py`
- Test: `tests/test_route_buttons.py`

**Interfaces:**
- Consumes: `charts.route_section_png`, `forecast.get_route`, `bot._profile_from_token`.
- Produces: `forecast.get_route_section(points, name, date, departure_h=None) -> bytes`; обработчик `rt|<токен>|sec`.

- [ ] **Step 1: Write the failing test**

Дописать в `tests/test_route_buttons.py`:

```python
async def test_the_section_button_sends_a_photo(bot, session, api):
    from tg import photos
    await botmod.dp.feed_update(bot, text_update(BODY))
    await botmod.dp.feed_update(bot, callback_update(f"rt|{_last_token()}|sec"))
    assert photos(session)


async def test_the_section_costs_no_new_api_calls(bot, session, api):
    """Погода уже в кэше: кнопка не должна ходить в open-meteo заново."""
    await botmod.dp.feed_update(bot, text_update(BODY))
    before = dict(api)
    await botmod.dp.feed_update(bot, callback_update(f"rt|{_last_token()}|sec"))
    assert api == before


async def test_without_terrain_the_button_explains_itself(bot, session, monkeypatch):
    async def fake_weather(url):
        return om_route(_n(url))

    async def no_terrain(coords):
        return None

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", no_terrain)
    await botmod.dp.feed_update(bot, text_update(BODY))
    await botmod.dp.feed_update(bot, callback_update(f"rt|{_last_token()}|sec"))
    assert "рельеф" in texts(session)[-1].lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
set -o pipefail; python -m pytest tests/test_route_buttons.py -x -q 2>&1 | tail -20
```

Expected: FAIL — фотографий нет, кнопка `sec` не обрабатывается.

- [ ] **Step 3: Implement**

В `forecast.py` после `get_route` добавить:

```python
async def get_route_section(points, name, date, departure_h=None) -> bytes:
    """PNG-разрез вдоль маршрута. Профиль пересчитывается поверх тёплого кэша."""
    profile = await get_route(points, name, date, departure_h)
    out = tempfile.mkdtemp(prefix="pgrs_")
    try:
        import charts
        path = charts.route_section_png(profile, out)
        if path is None:
            raise ForecastError("Разрез недоступен: рельеф не загрузился.")
        return pathlib.Path(path).read_bytes()
    finally:
        shutil.rmtree(out, ignore_errors=True)
```

В `bot.py` добавить обработчик:

```python
@dp.callback_query(F.data.regexp(r"^rt\|[^|]+\|sec$"))
async def cb_route_section(cb: CallbackQuery):
    _p, token, _a = cb.data.split("|")
    await cb.answer()
    msg = await cb_message(cb)
    if msg is None:
        return
    entry = _route_cache.get(token)
    if entry is None:
        return await msg.answer("Маршрут устарел, посчитай заново: /route")
    try:
        png = await forecast.get_route_section(
            entry["points"], entry["name"], entry["date"], entry["departure"])
    except forecast.ForecastError as e:
        return await msg.answer(str(e))
    await msg.answer_photo(BufferedInputFile(png, filename="route_section.png"))
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: всё зелёное.

- [ ] **Step 5: Commit**

```bash
git add forecast.py bot.py tests/test_route_buttons.py
git commit -m "feat(bot): кнопка разреза маршрута"
```

---

## Task 10: Кнопка «другое время вылета»

**Files:**
- Modify: `bot.py`
- Test: `tests/test_route_buttons.py`

**Interfaces:**
- Consumes: `profile["departure_scan"]`, `bot._profile_from_token`, `bot._route_keyboard`.
- Produces: обработчики `rt|<токен>|dep` и `rt|<токен>|dep|<ЧЧ:ММ>`.

- [ ] **Step 1: Write the failing test**

Дописать в `tests/test_route_buttons.py`:

```python
async def test_the_departure_button_offers_times(bot, session, api):
    await botmod.dp.feed_update(bot, text_update(BODY))
    token = _last_token()
    await botmod.dp.feed_update(bot, callback_update(f"rt|{token}|dep"))
    labels = [b.text for b in buttons(keyboards(session)[-1])]
    assert any(":" in t for t in labels)


async def test_picking_a_time_recomputes_the_card(bot, session, api):
    await botmod.dp.feed_update(bot, text_update(BODY))
    token = _last_token()
    await botmod.dp.feed_update(bot, callback_update(f"rt|{token}|dep|13:00"))
    card = [t for t in texts(session) if "🗺" in t][-1]
    assert "13:00" in card


async def test_the_recomputed_card_keeps_its_buttons(bot, session, api):
    await botmod.dp.feed_update(bot, text_update(BODY))
    token = _last_token()
    await botmod.dp.feed_update(bot, callback_update(f"rt|{token}|dep|13:00"))
    assert any("Разрез" in b.text for b in buttons(keyboards(session)[-1]))


async def test_the_time_list_is_capped(bot, session, api):
    """Скан даёт два десятка вариантов; клавиатура из двадцати кнопок нечитаема."""
    await botmod.dp.feed_update(bot, text_update(BODY))
    await botmod.dp.feed_update(bot, callback_update(f"rt|{_last_token()}|dep"))
    assert len(buttons(keyboards(session)[-1])) <= botmod._DEPARTURE_BUTTONS


async def test_a_lost_token_on_the_departure_button_says_so(bot, session, api):
    await botmod.dp.feed_update(bot, callback_update("rt|неттакого|dep"))
    assert "устарел" in cb_answers(session)[-1].text
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
set -o pipefail; python -m pytest tests/test_route_buttons.py -x -q 2>&1 | tail -20
```

Expected: FAIL — обработчика `dep` нет.

- [ ] **Step 3: Implement**

В `bot.py` добавить:

```python
_DEPARTURE_BUTTONS = 12     # клавиатура из двух десятков времён нечитаема


def _departure_keyboard(token, scan):
    """Времена вылета из скана. Прореживаются равномерно, оба конца сохраняются."""
    step = max(1, math.ceil(len(scan) / _DEPARTURE_BUTTONS))
    shown = scan[::step][:_DEPARTURE_BUTTONS]
    rows, row = [], []
    for e in shown:
        mark = "🟢" if e["feasibility"] == "completable" else "·"
        btn = _btn(f"{mark} {e['departure']}", f"rt|{token}|dep|{e['departure']}")
        if btn is None:
            continue
        row.append(btn)
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


@dp.callback_query(F.data.regexp(r"^rt\|[^|]+\|dep$"))
async def cb_route_departures(cb: CallbackQuery):
    _p, token, _a = cb.data.split("|")
    entry = _route_cache.get(token)
    if entry is None:
        return await cb.answer("Маршрут устарел, посчитай заново: /route", show_alert=True)
    await cb.answer()
    msg = await cb_message(cb)
    if msg is None:
        return
    try:
        profile = await forecast.get_route(entry["points"], entry["name"],
                                           entry["date"], entry["departure"])
    except forecast.ForecastError as e:
        return await msg.answer(str(e))
    scan = profile.get("departure_scan") or []
    if not scan:
        return await msg.answer("Скан времён вылета пуст — термическое окно не открывается.")
    await msg.answer("Во сколько вылетаем?",
                     reply_markup=_departure_keyboard(token, scan))


@dp.callback_query(F.data.regexp(r"^rt\|[^|]+\|dep\|"))
async def cb_route_departure_pick(cb: CallbackQuery):
    _p, token, _a, hhmm = cb.data.split("|", 3)
    entry = _route_cache.get(token)
    if entry is None:
        return await cb.answer("Маршрут устарел, посчитай заново: /route", show_alert=True)
    await cb.answer()
    msg = await cb_message(cb)
    if msg is None:
        return
    h, m = hhmm.split(":")
    await _send_route(msg, entry["points"], entry["name"], entry["date"],
                      int(h) + int(m) / 60.0)
```

Добавить `import math` в шапку `bot.py`, если его там ещё нет.

Порядок регистрации важен: `dep|` должен быть **после** `dep$`, но так как фильтры взаимоисключающие (`$` против `\|`), порядок значения не имеет — оба варианта проверяются регулярным выражением целиком.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: всё зелёное.

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_route_buttons.py
git commit -m "feat(bot): пересчёт маршрута на другое время вылета"
```

---

## Task 11: Данные для модели

**Files:**
- Modify: `forecast.py`
- Test: `tests/test_route_facts.py`

**Interfaces:**
- Consumes: профиль из `get_route`, `route.key_points`.
- Produces: `forecast.ROUTE_FACTS_MAX_POINTS = 20`, `forecast.route_facts(profile) -> dict`.

- [ ] **Step 1: Write the failing test**

Создать `tests/test_route_facts.py`:

```python
"""Сборка данных для модели: профиль плюс блок computed."""
import forecast


def profile(n=5):
    pts = []
    for i in range(n):
        pts.append({
            "km": float(i * 10), "leg_length_km": 10.0, "eta": f"1{i % 10}:00",
            "role": "takeoff" if i == 0 else ("goal" if i == n - 1 else "enroute"),
            "lat": 42.0 + i / 100.0, "lon": 44.0, "name": None,
            "track_bearing_deg": 148, "is_turnpoint": i in (0, n - 1),
            "is_terrain_peak": False, "storm_ahead": None,
            "wind_along_kmh": -8.4, "wind_cross_kmh": -24.6,
            "wind_working_alt_kmh": 26.0, "wind_working_alt_dir": 268.0,
            "effective_ground_speed_kmh": 16.6,
            "terrain_m": 2510, "cloud_base_m": 3230, "thermal_ceiling_m": 4260,
            "working_band_m": 420, "time_margin_min": 210,
            "score": 61, "category": "fair", "limiting": "рабочий диапазон",
            "vetoes": [], "subs": {"working_band": 38.0}, "groups": {},
            "weather": {"cape": 850.0},
        })
    return {"route": {"name": "Тест", "total_km": float((n - 1) * 10)},
            "points": pts,
            "verdict": {"score": 61, "feasibility": "completable",
                        "bottleneck": {"km": 20.0}, "blocked_at_km": None},
            "departure_scan": [{"departure": "11:00", "score": 61,
                                "feasibility": "completable"}],
            "reverse": {"score": 74, "feasibility": "completable", "better": True}}


def test_route_verdict_scan_and_reverse_are_carried_over():
    f = forecast.route_facts(profile())
    assert set(f) == {"route", "points", "verdict", "departure_scan", "reverse"}


def test_every_point_carries_a_computed_block():
    f = forecast.route_facts(profile())
    assert all("computed" in p for p in f["points"])
    assert f["points"][0]["computed"]["subs"]


def test_the_computed_block_holds_the_scoring_not_the_geometry():
    c = forecast.route_facts(profile())["points"][0]["computed"]
    assert set(c) == {"score", "category", "limiting", "vetoes", "subs"}


def test_a_long_route_is_trimmed():
    """Больше двадцати точек — и ответ модели обрывается на середине."""
    f = forecast.route_facts(profile(n=50))
    assert len(f["points"]) <= forecast.ROUTE_FACTS_MAX_POINTS


def test_trimming_keeps_the_characteristic_points():
    f = forecast.route_facts(profile(n=50))
    kms = [p["km"] for p in f["points"]]
    assert 0.0 in kms and 490.0 in kms and 20.0 in kms


def test_points_stay_sorted_by_kilometre():
    kms = [p["km"] for p in forecast.route_facts(profile(n=50))["points"]]
    assert kms == sorted(kms)


def test_a_short_route_is_not_trimmed():
    assert len(forecast.route_facts(profile(n=5))["points"]) == 5
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
set -o pipefail; python -m pytest tests/test_route_facts.py -x -q 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: module 'forecast' has no attribute 'route_facts'`.

- [ ] **Step 3: Implement**

В `forecast.py` рядом с константами маршрута добавить:

```python
ROUTE_FACTS_MAX_POINTS = 20   # длиннее — ответ модели обрывается на середине
```

и после `get_route_section`:

```python
_FACT_KEYS = ("km", "eta", "role", "leg_length_km", "lat", "lon",
              "track_bearing_deg", "wind_along_kmh", "wind_cross_kmh",
              "wind_working_alt_kmh", "wind_working_alt_dir",
              "effective_ground_speed_kmh", "terrain_m", "cloud_base_m",
              "thermal_ceiling_m", "working_band_m", "time_margin_min",
              "is_terrain_peak", "storm_ahead", "weather")


def route_facts(profile):
    """Данные для модели: профиль плюс блок computed с результатом скоринга.

    Не больше ROUTE_FACTS_MAX_POINTS точек. Сначала характерные (старт, финиш,
    узкое место, обрыв, поворотные, вершины), потом равномерная добивка: на
    длинном списке ответ модели обрывается на середине.
    """
    pts = profile["points"]
    keep = {k["km"] for k in route.key_points(profile)}
    rest = [p["km"] for p in pts if p["km"] not in keep]
    free = ROUTE_FACTS_MAX_POINTS - len(keep)
    if free > 0 and rest:
        step = max(1, math.ceil(len(rest) / free))
        keep |= set(rest[::step][:free])
    chosen = [p for p in pts if p["km"] in keep][:ROUTE_FACTS_MAX_POINTS]
    return {
        "route": profile["route"],
        "verdict": profile.get("verdict"),
        "departure_scan": profile.get("departure_scan"),
        "reverse": profile.get("reverse"),
        "points": [{**{k: p.get(k) for k in _FACT_KEYS},
                    "computed": {"score": p.get("score"), "category": p.get("category"),
                                 "limiting": p.get("limiting"),
                                 "vetoes": p.get("vetoes") or [],
                                 "subs": p.get("subs") or {}}}
                   for p in chosen],
    }
```

Добавить `import math` в шапку `forecast.py`, если его там нет.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: всё зелёное.

- [ ] **Step 5: Commit**

```bash
git add forecast.py tests/test_route_facts.py
git commit -m "feat(forecast): сборка маршрутных данных для модели"
```

---

## Task 12: Промпт и запрос к модели

**Files:**
- Modify: `analysis.py`
- Test: `tests/test_route_prompt.py`

**Interfaces:**
- Consumes: `criteria.reference_text(criteria.ENROUTE)`, `analysis._model_chain`, `analysis._get_client`.
- Produces: `analysis._ROUTE_PROMPT`, `analysis._ROUTE_SCHEMA`, `analysis.analyze_route(facts) -> dict`.

- [ ] **Step 1: Write the failing test**

Создать `tests/test_route_prompt.py`:

```python
"""Маршрутный промпт: пороги генерируются, а не переписываются руками."""
import criteria


def test_thresholds_come_from_the_tables_not_from_the_prompt():
    """Написанный руками блок порогов уже разъезжался с расчётом молча —
    поэтому он генерируется из criteria."""
    import analysis
    assert criteria.reference_text(criteria.ENROUTE) in analysis._ROUTE_PROMPT


def test_the_prompt_states_the_sign_conventions():
    import analysis
    for token in ("wind_along", "попутн", "встречн", "wind_cross", "time_margin"):
        assert token in analysis._ROUTE_PROMPT


def test_the_prompt_forbids_recomputing():
    import analysis
    assert "computed" in analysis._ROUTE_PROMPT
    assert "пересчит" in analysis._ROUTE_PROMPT.lower()


def test_the_prompt_names_all_three_roles():
    import analysis
    for role in ("takeoff", "enroute", "goal"):
        assert role in analysis._ROUTE_PROMPT


def test_the_schema_asks_only_for_text():
    """Числа модель не присылает — портить нечего."""
    import analysis
    props = analysis._ROUTE_SCHEMA["properties"]
    assert set(props) == {"points", "summary"}
    assert set(props["points"]["items"]["properties"]) == {"km", "comment"}
    assert set(props["summary"]["properties"]) == {
        "verdict", "bottleneck_note", "tactical_note"}


def test_the_schema_has_no_score_or_feasibility():
    import analysis
    text = str(analysis._ROUTE_SCHEMA)
    for forbidden in ("score", "feasibility", "eta", "veto"):
        assert forbidden not in text


def test_answer_json_survives_a_code_fence():
    """Часть моделей всё равно оборачивает JSON в ```json, несмотря на схему."""
    import analysis
    assert analysis._loads('```json\n{"points": []}\n```') == {"points": []}


def test_a_non_object_answer_is_an_error():
    import analysis
    import pytest
    with pytest.raises(ValueError):
        analysis._loads("[1, 2, 3]")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
set -o pipefail; python -m pytest tests/test_route_prompt.py -x -q 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: module 'analysis' has no attribute '_ROUTE_PROMPT'`.

- [ ] **Step 3: Implement**

В `analysis.py` в конец файла добавить:

```python
# ---------------------------------------------------------------- маршрут
# Режим интерпретации: скоринг уже сделан кодом, модель пишет ТОЛЬКО текст.
# Числа у неё не запрашиваются вовсе — значит их нельзя ни переврать, ни
# «поправить», и половина проверок ответа отпадает вместе с полями.
_ROUTE_PREAMBLE = """Ты — экспертный метео-ассистент для парапланерного кросс-кантри в горах.
Оцениваешь ЗАПЛАНИРОВАННЫЙ МАРШРУТ: набор точек, у каждой своё время прилёта и свой
погодный срез на этот момент.

Всё, что можно вычислить, УЖЕ ВЫЧИСЛЕНО кодом: пеленги, проекции ветра на трек,
расстояния, время прилёта, интерполяция погоды, баллы. Не пересчитывай ничего.
Ты пишешь только текст.

Знаки величин заданы так:
  wind_along_kmh  > 0 попутный, < 0 встречный
  wind_cross_kmh  > 0 сносит вправо от трека, < 0 влево
  time_margin_min > 0 запас до закрытия термического окна в этой точке
  working_band_m  = база облаков − (рельеф + 300 м безопасной высоты)

Роли точек:
  takeoff — старт: важен наземный ветер, порывы и направление склона.
  enroute — в воздухе: наземный ветер и направление склона не применяются.
  goal    — финиш: наземный ветер снова важен (посадка), плюс запас времени.

В блоке computed у каждой точки лежит результат детерминированного скоринга: score,
category, limiting (лимитирующий фактор), vetoes и subs (субоценки 0–100 по каждому
параметру). Это ИСТИНА. Не спорь с ней и не пересчитывай её.
"""

_ROUTE_TASK = """
Верни JSON: comment у точек и три поля summary. Больше ничего — балл, категория,
статус выполнимости и время прилёта уже посчитаны и берутся не от тебя.

comment (1–2 предложения) объясняет, ПОЧЕМУ у точки такой балл, опираясь на limiting
и subs. Не пересказывай числа, которые пилот и так видит в таблице.
Плохо: «Ветер 26 км/ч, база 3230 м, рельеф 2510 м».
Хорошо: «Оценку держит перевал: 420 м рабочего диапазона — это одна попытка на
проход, второй набор сделать негде».

summary.verdict (2–3 предложения) — долечу ли я вообще и почему.
summary.bottleneck_note — где именно рвётся и чем. Нечего сказать — пустая строка.
summary.tactical_note — что делать: сдвинуть вылет, перекроить маршрут, лететь в
обратную сторону. Опирайся на departure_scan и reverse, а не на догадки. Если ни одно
время вылета не даёт completable — скажи это прямо, не предлагай «вылететь раньше».
Данных на совет нет — пустая строка, а не выдумка.

Если в точке заполнено storm_ahead — это предупреждение НА ПОДЛЁТЕ, назови километр и
час, даже если сама точка чистая.

Не выдумывай числа: только те, что есть во входных данных. Не привлекай знания о
регионе, репутации маршрута и сезоне. Без дисклеймеров про «решение за пилотом» — это
делает интерфейс. По-русски, конкретно.
"""

_ROUTE_PROMPT = (_ROUTE_PREAMBLE + criteria.reference_text(criteria.ENROUTE)
                 + _ROUTE_TASK)

# Пустая строка вместо null: часть моделей на типе ["string", "null"] в схеме
# спотыкается, а «пусто» проверяющая сторона всё равно приводит к None.
_ROUTE_SCHEMA = {
    "type": "object",
    "required": ["points", "summary"],
    "properties": {
        "points": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["km", "comment"],
                "properties": {"km": {"type": "number"},
                               "comment": {"type": "string"}},
            },
        },
        "summary": {
            "type": "object",
            "required": ["verdict", "bottleneck_note", "tactical_note"],
            "properties": {"verdict": {"type": "string"},
                           "bottleneck_note": {"type": "string"},
                           "tactical_note": {"type": "string"}},
        },
    },
}


def _loads(text):
    """JSON из ответа модели. Обрамление ```json снимается: часть моделей ставит
    его даже при заданном response_mime_type."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1].rsplit("```", 1)[0]
    data = json.loads(s)
    if not isinstance(data, dict):
        raise ValueError("ответ модели — не объект")
    return data


def analyze_route(facts: dict) -> dict:
    """Разбор маршрута от Gemini: разобранный JSON. Бросает, если все модели отказали."""
    prompt = (f"{_ROUTE_PROMPT}\n\nДанные (JSON):\n"
              f"{json.dumps(facts, ensure_ascii=False)}")
    client = _get_client()
    config = types.GenerateContentConfig(
        temperature=0.3, response_mime_type="application/json",
        response_schema=_ROUTE_SCHEMA)
    errors = []
    for model in _model_chain():
        try:
            resp = client.models.generate_content(model=model, contents=prompt,
                                                  config=config)
            answer = _loads(resp.text)
            log.info("gemini route ok: %s", model)
            return answer
        except Exception as e:  # noqa: BLE001 — любой отказ → следующая модель
            log.warning("gemini route model %s failed: %s", model, e)
            errors.append(f"{model}: {e}")
    raise RuntimeError("все модели Gemini недоступны: " + " | ".join(errors))
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: всё зелёное.

- [ ] **Step 5: Commit**

```bash
git add analysis.py tests/test_route_prompt.py
git commit -m "feat(analysis): промпт и схема ответа для разбора маршрута"
```

---

## Task 13: Проверка ответа модели

**Files:**
- Modify: `analysis.py`
- Test: `tests/test_route_analysis.py`

**Interfaces:**
- Consumes: профиль маршрута (ключ `points` с `km` и `wind_along_kmh`).
- Produces: `analysis.check_route_answer(answer, profile) -> (dict, list[str])`.

- [ ] **Step 1: Write the failing test**

Создать `tests/test_route_analysis.py`:

```python
"""Проверки ответа модели перед показом пилоту."""
import analysis


def profile():
    return {"points": [
        {"km": 0.0, "wind_along_kmh": 5.2},      # попутный
        {"km": 40.0, "wind_along_kmh": -8.4},    # встречный
        {"km": 78.0, "wind_along_kmh": None},    # неизвестно
    ]}


def answer(points, **summary):
    base = {"verdict": "вердикт", "bottleneck_note": "", "tactical_note": ""}
    base.update(summary)
    return {"points": points, "summary": base}


def check(points, **summary):
    return analysis.check_route_answer(answer(points, **summary), profile())


def test_a_clean_answer_passes_through():
    clean, flags = check([{"km": 40.0, "comment": "перевал держит оценку"}])
    assert clean["points"] == [{"km": 40.0, "comment": "перевал держит оценку"}]
    assert flags == []


def test_an_unknown_kilometre_is_dropped():
    """Модель схлопывает соседние точки или добавляет промежуточную."""
    clean, flags = check([{"km": 55.0, "comment": "откуда-то взялась"}])
    assert clean["points"] == []
    assert "llm_unknown_km" in flags


def test_a_non_numeric_kilometre_is_dropped():
    clean, flags = check([{"km": "сорок", "comment": "текст"}])
    assert clean["points"] == []
    assert "llm_unknown_km" in flags


def test_a_tailwind_claim_on_a_headwind_point_is_dropped():
    """Совет, противоположный правильному, опаснее отсутствия совета."""
    clean, flags = check([{"km": 40.0, "comment": "попутный поможет добить плечо"}])
    assert clean["points"] == []
    assert "llm_wind_sign_error" in flags


def test_a_headwind_claim_on_a_tailwind_point_is_dropped():
    clean, flags = check([{"km": 0.0, "comment": "встречный съест скорость"}])
    assert clean["points"] == []
    assert "llm_wind_sign_error" in flags


def test_the_right_sign_survives():
    clean, flags = check([{"km": 40.0, "comment": "встречный съест скорость"},
                          {"km": 0.0, "comment": "попутный помогает"}])
    assert len(clean["points"]) == 2
    assert flags == []


def test_a_point_without_wind_data_is_not_judged():
    """Знак неизвестен — проверять нечем, и выбрасывать текст не за что."""
    clean, flags = check([{"km": 78.0, "comment": "попутный и встречный сразу"}])
    assert len(clean["points"]) == 1
    assert flags == []


def test_one_bad_comment_does_not_take_the_good_ones_with_it():
    clean, _flags = check([{"km": 40.0, "comment": "попутный поможет"},
                           {"km": 0.0, "comment": "старт чистый"}])
    assert [c["km"] for c in clean["points"]] == [0.0]


def test_comments_come_out_sorted_by_kilometre():
    clean, _flags = check([{"km": 40.0, "comment": "второй"},
                           {"km": 0.0, "comment": "первый"}])
    assert [c["km"] for c in clean["points"]] == [0.0, 40.0]


def test_an_empty_comment_is_dropped_quietly():
    clean, flags = check([{"km": 40.0, "comment": "   "}])
    assert clean["points"] == []
    assert flags == []


def test_empty_summary_fields_become_none():
    clean, _flags = check([], bottleneck_note="", tactical_note="  ")
    assert clean["summary"]["bottleneck_note"] is None
    assert clean["summary"]["tactical_note"] is None
    assert clean["summary"]["verdict"] == "вердикт"


def test_a_missing_summary_does_not_crash():
    clean, _flags = analysis.check_route_answer({"points": []}, profile())
    assert clean["summary"]["verdict"] is None


def test_a_missing_points_key_does_not_crash():
    clean, _flags = analysis.check_route_answer({"summary": {}}, profile())
    assert clean["points"] == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
set -o pipefail; python -m pytest tests/test_route_analysis.py -x -q 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: module 'analysis' has no attribute 'check_route_answer'`.

- [ ] **Step 3: Implement**

В `analysis.py` добавить `import re` в шапку и в конец файла:

```python
_TAILWIND = re.compile(r"попутн", re.I)
_HEADWIND = re.compile(r"встречн", re.I)
_KM_EPS = 0.05


def check_route_answer(answer, profile):
    """Отсеять то, что модель не имела права прислать → (чистый ответ, коды проблем).

    Чистая функция без сети: её можно и нужно гонять на подложных ответах.

    Из шести проверок §6 промпт-документа здесь живут две. Остальные четыре
    (число точек, bottleneck.km, согласованность feasibility с вето, пересчёт
    route_score) отпали вместе с полями: модель их не присылает.

    Знаковую ошибку ТЗ предлагает только залогировать. Здесь комментарий
    выбрасывается: «попутный поможет добить последнее плечо» при встречном
    ветре — это совет, прямо противоположный правильному, в тексте, который
    выглядит абсолютно уверенно.

    Чего проверки не ловят: сводка не привязана к точке, и перевёрнутый знак в
    verdict или tactical_note поймать нечем — «встречный на второй половине»
    бывает верно при попутном на первой.
    """
    by_km = {round(p["km"], 1): p for p in profile.get("points") or []}
    flags, clean = [], []
    for item in (answer or {}).get("points") or []:
        try:
            km = round(float(item.get("km")), 1)
        except (TypeError, ValueError):
            flags.append("llm_unknown_km")
            continue
        point = next((p for k, p in by_km.items() if abs(k - km) < _KM_EPS), None)
        if point is None:
            flags.append("llm_unknown_km")
            continue
        text = (item.get("comment") or "").strip()
        if not text:
            continue
        along = point.get("wind_along_kmh")
        if along is not None and ((along < 0 and _TAILWIND.search(text))
                                  or (along > 0 and _HEADWIND.search(text))):
            flags.append("llm_wind_sign_error")
            continue
        clean.append({"km": km, "comment": text})
    clean.sort(key=lambda c: c["km"])
    summary = (answer or {}).get("summary") or {}
    return ({"points": clean,
             "summary": {k: ((summary.get(k) or "").strip() or None)
                         for k in ("verdict", "bottleneck_note", "tactical_note")}},
            flags)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: всё зелёное.

- [ ] **Step 5: Commit**

```bash
git add analysis.py tests/test_route_analysis.py
git commit -m "feat(analysis): проверки ответа модели по маршруту"
```

---

## Task 14: Кнопка ИИ-разбора

**Files:**
- Modify: `route.py`, `forecast.py`, `bot.py`
- Test: `tests/test_route_analysis_dialog.py`

**Interfaces:**
- Consumes: `analysis.analyze_route`, `analysis.check_route_answer`, `forecast.route_facts`, `forecast.get_route`.
- Produces: `route.render_analysis(answer) -> str`, `forecast.get_route_analysis(points, name, date, departure_h=None) -> str`, обработчик `rt|<токен>|ai`.

- [ ] **Step 1: Write the failing test**

Создать `tests/test_route_analysis_dialog.py`:

```python
"""Показ ИИ-разбора маршрута."""
import datetime as dt

import pytest

import analysis
import bot as botmod
import forecast
import route
from fixtures import om_route
from tg import callback_update, text_update, texts

BODY = ("/route\n"
        "42.4776, 44.4787, старт\n"
        "42.1176, 44.4787, финиш")

ANSWER = {"points": [{"km": 0.0, "comment": "старт чистый, день открывается"}],
          "summary": {"verdict": "Маршрут проходится.",
                      "bottleneck_note": "Перевал на 20 км.",
                      "tactical_note": ""}}


def _n(url):
    return url.split("latitude=")[1].split("&")[0].count(",") + 1


@pytest.fixture()
def api(monkeypatch):
    async def fake_weather(url):
        return om_route(_n(url))

    async def fake_terrain(coords):
        return [1000.0] * len(coords)

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)
    monkeypatch.setattr(analysis, "available", lambda: True)


def _last_token():
    return next(reversed(botmod._route_cache))


def test_render_puts_the_verdict_first():
    text = route.render_analysis(ANSWER)
    assert text.index("Маршрут проходится") < text.index("Перевал")


def test_render_skips_empty_summary_fields():
    text = route.render_analysis(ANSWER)
    assert "Тактика" not in text


def test_render_lists_point_comments_with_kilometres():
    assert "0 км · старт чистый" in route.render_analysis(ANSWER)


def test_render_of_an_empty_answer_does_not_crash():
    assert route.render_analysis({"points": [], "summary": {}})


async def test_the_button_shows_the_analysis(bot, session, api, monkeypatch):
    monkeypatch.setattr(analysis, "analyze_route", lambda facts: ANSWER)
    await botmod.dp.feed_update(bot, text_update(BODY))
    await botmod.dp.feed_update(bot, callback_update(f"rt|{_last_token()}|ai"))
    assert any("🤖" in t for t in texts(session))


async def test_a_gemini_failure_leaves_the_card_alone(bot, session, api, monkeypatch):
    def boom(facts):
        raise RuntimeError("все модели Gemini недоступны")

    monkeypatch.setattr(analysis, "analyze_route", boom)
    await botmod.dp.feed_update(bot, text_update(BODY))
    await botmod.dp.feed_update(bot, callback_update(f"rt|{_last_token()}|ai"))
    assert "не получился" in texts(session)[-1]
    assert any("🗺" in t for t in texts(session))


async def test_a_broken_answer_is_reported_not_shown(bot, session, api, monkeypatch):
    monkeypatch.setattr(analysis, "analyze_route", lambda facts: "не json")
    await botmod.dp.feed_update(bot, text_update(BODY))
    await botmod.dp.feed_update(bot, callback_update(f"rt|{_last_token()}|ai"))
    assert "не получился" in texts(session)[-1]


async def test_without_a_key_the_button_says_so(bot, session, monkeypatch):
    async def fake_weather(url):
        return om_route(_n(url))

    async def fake_terrain(coords):
        return [1000.0] * len(coords)

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)
    await botmod.dp.feed_update(bot, text_update(BODY))
    token = _last_token()
    monkeypatch.setattr(analysis, "available", lambda: False)
    await botmod.dp.feed_update(bot, callback_update(f"rt|{token}|ai"))
    assert "GEMINI_API_KEY" in texts(session)[-1]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
set -o pipefail; python -m pytest tests/test_route_analysis_dialog.py -x -q 2>&1 | tail -20
```

Expected: FAIL — `AttributeError: module 'route' has no attribute 'render_analysis'`.

- [ ] **Step 3: Implement**

В `route.py` после `render_point_card` добавить:

```python
def render_analysis(answer):
    """Текст ИИ-разбора маршрута для Telegram.

    Пустые поля сводки строк не занимают: «Тактика: —» читается как совет,
    которого нет, а не как его отсутствие.
    """
    s = answer.get("summary") or {}
    out = ["🤖 Разбор маршрута", ""]
    if s.get("verdict"):
        out += [s["verdict"], ""]
    if s.get("bottleneck_note"):
        out += [f"Узкое место: {s['bottleneck_note']}", ""]
    if s.get("tactical_note"):
        out += [f"Тактика: {s['tactical_note']}", ""]
    for c in answer.get("points") or []:
        out.append(f"{c['km']:.0f} км · {c['comment']}")
    return "\n".join(out).strip()
```

В `forecast.py` после `route_facts` добавить:

```python
async def get_route_analysis(points, name, date, departure_h=None) -> str:
    """ИИ-разбор маршрута. ForecastError, если разбора не будет.

    Карточка маршрута к этому моменту уже показана и остаётся в силе — поэтому
    отказ здесь это сообщение, а не откат на другой текст.
    """
    if not analysis.available():
        raise ForecastError("ИИ-разбор недоступен: не задан GEMINI_API_KEY.")
    profile = await get_route(points, name, date, departure_h)
    facts = route_facts(profile)
    t0 = time.monotonic()
    try:
        raw = await asyncio.to_thread(analysis.analyze_route, facts)
        answer, flags = analysis.check_route_answer(raw, profile)
    except Exception as e:  # noqa: BLE001 — отказ модели или неразбираемый ответ
        log.warning("route analysis failed: %s", e)
        raise ForecastError("ИИ-разбор не получился — карточка выше остаётся в силе.")
    if flags:
        log.warning("route analysis checks tripped: %s", ",".join(sorted(set(flags))))
    log.info("route analysis ok (%.1fs, %d комментариев)",
             time.monotonic() - t0, len(answer["points"]))
    return route.render_analysis(answer)
```

В `bot.py` добавить обработчик:

```python
@dp.callback_query(F.data.regexp(r"^rt\|[^|]+\|ai$"))
async def cb_route_analysis(cb: CallbackQuery):
    _p, token, _a = cb.data.split("|")
    await cb.answer()
    msg = await cb_message(cb)
    if msg is None:
        return
    entry = _route_cache.get(token)
    if entry is None:
        return await msg.answer("Маршрут устарел, посчитай заново: /route")
    try:
        text = await forecast.get_route_analysis(
            entry["points"], entry["name"], entry["date"], entry["departure"])
    except forecast.ForecastError as e:
        return await msg.answer(str(e))
    for chunk in _chunks(text):
        await msg.answer(chunk)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: всё зелёное.

- [ ] **Step 5: Commit**

```bash
git add route.py forecast.py bot.py tests/test_route_analysis_dialog.py
git commit -m "feat(bot): кнопка ИИ-разбора маршрута"
```

---

## Task 15: Документация и сквозная проверка

**Files:**
- Modify: `README.md`
- Test: весь набор

- [ ] **Step 1: Прогнать весь набор тестов**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: всё зелёное. Записать итоговое число тестов.

- [ ] **Step 2: Сквозная проверка на подложных данных**

Написать во временный файл `/tmp/smoke_route_visuals.py` и запустить: он строит профиль через `forecast.get_route` с подменёнными сетевыми вызовами, печатает карточку маршрута, карточку каждой характерной точки и сохраняет разрез в PNG.

```python
import asyncio, datetime as dt, sys
sys.path.insert(0, "."); sys.path.insert(0, "tests")
import forecast, route, charts
from fixtures import om_route


def _n(url):
    return url.split("latitude=")[1].split("&")[0].count(",") + 1


async def main():
    forecast._fetch_route_weather = lambda url: _weather(url)
    forecast.fetch_terrain = lambda coords: _terrain(coords)
    pts = [route.Point(42.4776, 44.4787, "старт"),
           route.Point(42.3428, 44.5513, "перевал"),
           route.Point(42.2104, 44.6890, "финиш")]
    p = await forecast.get_route(pts, "Гудаури → Пасанаури",
                                 dt.date.today().isoformat(), 11.0)
    card = route.render_card(p)
    print(card)
    print("ШИРИНА:", max(len(ln) for ln in card.splitlines()))
    for k in route.key_points(p):
        pc = route.render_point_card(p, k["km"])
        print("-" * 40, k["mark"], k["km"])
        print(pc)
        print("ШИРИНА:", max(len(ln) for ln in pc.splitlines()))
    print("PNG:", charts.route_section_png(p, "/tmp"))


async def _weather(url):
    return om_route(_n(url))


async def _terrain(coords):
    return [2000.0 + (i % 17) * 40 for i in range(len(coords))]


asyncio.run(main())
```

```bash
python /tmp/smoke_route_visuals.py
```

Проверить глазами: ширина всех карточек не больше 32, PNG открывается, на нём видны рельеф, коридор, потолок, база, стрелки, время и лента лётности. Найденные расхождения исправить и покрыть тестом.

- [ ] **Step 3: Дополнить README**

В раздел «Погода по маршруту» добавить описание кнопок и новых команд:

```markdown
Под карточкой маршрута — кнопки:

- **характерные точки** (старт, поворотные, вершины рельефа, узкое место, обрыв,
  финиш) — подробности по одной точке: ветер вдоль и поперёк курса, база, рельеф,
  рабочий коридор, запас времени и три субоценки, которые тянут балл вниз;
- **📈 Разрез** — картинка вдоль маршрута: рельеф, безопасная высота, рабочий
  коридор, потолок термиков и база облаков, стрелки ветра, время прилёта и лента
  лётности;
- **🤖 Разбор** — интерпретация от Gemini. Модель получает уже посчитанные числа и
  пишет только текст: баллы, статус и время прилёта у неё не запрашиваются, поэтому
  переврать их она не может. Комментарий, в котором знак ветра перевёрнут, до пилота
  не доходит;
- **🕐 Другое время** — пересчёт на любое время вылета из скана, без новых запросов
  к open-meteo.

Маршруты можно сохранять:

- `/saveroute <имя>` — сохранить последний посчитанный маршрут (только координаты,
  погода всегда считается заново);
- `/routes` — список сохранённых;
- `/delroute <имя>` — удалить;
- `/route <имя> завтра 11:30` — посчитать сохранённый маршрут.

Форматы входа: список координат текстом, файл GPX и файл KML. В KML координаты
записаны как «долгота,широта» — бот это учитывает.
```

- [ ] **Step 4: Финальный прогон**

```bash
set -o pipefail; python -m pytest tests/ -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: разрез, карточка точки, сохранённые маршруты и ИИ-разбор в README"
```

---

## Самопроверка плана

**Покрытие спеки:**

| Раздел спеки | Задача |
|---|---|
| §1 границы модулей | распределено по всем |
| §2 состояние между кнопками | 4 |
| §3.1 сетка рельефа | 1 |
| §3.2 потолок термиков | 1 |
| §3.3 `is_turnpoint` | 1 |
| §3.4 `subs` и `groups` | 1 |
| §4 разрез PNG | 8 |
| §4.5 доставка | 9 |
| §5 карточка точки | 7 |
| §5.1 характерные точки | 3 |
| §6 сохранённые маршруты | 2, 5 |
| §7 KML | 6 |
| §8.1 данные для модели | 11 |
| §8.2 промпт | 12 |
| §8.3 схема ответа | 12 |
| §8.4 проверки | 13 |
| §8.5 показ | 14 |
| §9 кнопки | 4, 7, 9, 10, 14 |
| §10 ошибки и деградация | покрыто тестами задач 4, 7, 9, 13, 14, 2, 6 |
| §11 тесты | все |

**Отступления от спеки, зафиксированные явно:**

1. Порядок задач: токен-кэш идёт перед командами маршрутов, потому что `/saveroute` читает этот кэш. Спека в §12 ставила команды раньше.
2. Тест-файл `tests/test_route_total_km.py` в §11 спеки не назван — маленький помощник `route.total_km` понадобился списку `/routes`.
3. Тест-файл `tests/test_route_prompt.py` в §11 спеки не назван отдельно: §11 упоминает проверки ответа модели, но промпт и схему тоже нужно закрепить тестом, иначе генерация порогов из `criteria` может тихо отвалиться.
4. `route._plural` становится публичным `route.plural`: он нужен в `bot.py` для списка маршрутов, а лазить в приватное имя из другого модуля — хуже, чем переименовать.
5. В карточке точки добавлена строка «Скорость по земле»: она уже посчитана, а без неё вето `route_no_progress` невозможно объяснить.

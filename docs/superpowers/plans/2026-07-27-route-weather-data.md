# Маршрутная сводка погоды, спека 1 — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Команда `/route` принимает маршрут текстом или GPX-файлом и отдаёт фактическую таблицу «километр · время прибытия · погода», плюс команда `/settings` со средней маршрутной скоростью.

**Architecture:** Новый модуль `route.py` держит всю геометрию, разбор ввода, интерполяцию и рендер карточки — без сети и без aiogram, поэтому тестируется офлайн целиком. `settings.py` хранит глобальные настройки в JSON рядом с `sites.json`. `engine.py` получает две функции: сборку мульти-точечного URL и векторное осреднение ветра по слою. `forecast.py` оркеструет два HTTP-запроса (рельеф и погода) и кэширует их. `bot.py` добавляет два хендлера.

**Tech Stack:** Python 3.10, aiogram 3, httpx, pytest (`asyncio_mode = auto`). Новых зависимостей нет: GPX разбирается штатным `xml.etree.ElementTree`.

**Спека:** `docs/superpowers/specs/2026-07-27-route-weather-data-design.md`

## Global Constraints

- Скоринг, вердикт, баллы, вето, скан времени вылета, PNG и ИИ-разбор в эту спеку **не входят** — они в спеках 2 и 3. Ничего из этого не реализовывать даже «на будущее».
- Знаки ветра фиксированы: `wind_along = −V·cos(θ − φ)`, `wind_cross = −V·sin(θ − φ)`, где θ — направление ОТКУДА дует, φ — пеленг курса. Положительный `wind_along` — попутный, положительный `wind_cross` — снос вправо.
- Коэффициент базы облаков берётся из `criteria.LCL_M_PER_C`, второй копии числа 122 в репозитории быть не должно.
- Высоты (рабочий диапазон, база, рельеф) считаются и лежат в профиле, но **в карточку не выводятся**.
- Молчаливая деградация запрещена: недоступный рельеф даёт `None` и явную строку в `notes`, а не подстановку высоты грид-ячейки.
- Все константы — именованные, на верхнем уровне `route.py`, с комментарием, откуда взялось число.
- Тесты запускаются `.venv/bin/python -m pytest -q`, весь набор должен оставаться зелёным (сейчас 290 тестов).
- Коммит после каждой задачи, ветка `feature/route-weather`.

## File Structure

| Файл | Ответственность |
|---|---|
| `route.py` (создать) | разбор текста и GPX, геометрия, ресэмплинг, рельеф на сэмплах, проекции ветра, интерполяция по времени, термическое окно, марш времени прибытия, рендер карточки. Чистый: ни сети, ни aiogram, ни глобального состояния |
| `settings.py` (создать) | глобальные настройки маршрута в `settings.json` |
| `engine.py` (менять) | `route_weather_url()`, `mean_wind_vector()`, `_levels_with_dir()` |
| `forecast.py` (менять) | `fetch_terrain()`, `get_route()`, кэши рельефа и погоды маршрута |
| `bot.py` (менять) | хендлеры `/route` и `/settings` |
| `tests/fixtures.py` (менять) | `om_route()` — ответ на мульти-точечный запрос |
| `tests/conftest.py` (менять) | сброс `settings.json` между тестами |
| `tests/test_route_*.py` (создать) | по файлу на группу задач |

Рендер карточки живёт в `route.py`, а не в отдельном модуле: это чистое форматирование строки, и в репозитории уже принято держать расчёт и его отчёт рядом (`engine.report_1day` соседствует с `engine.derive_hour`).

---

### Task 1: Разбор маршрута текстом

**Files:**
- Create: `route.py`
- Test: `tests/test_route_parse.py`

**Interfaces:**
- Consumes: ничего
- Produces: `Point(lat: float, lon: float, name: str | None)`; `parse_text(text: str, first_line_no: int = 1) -> list[Point]`; `RouteError(Exception)`; константы `MIN_POINTS = 2`, `MAX_POINTS = 50`

`first_line_no` нужен вызывающему из `bot.py`: тело маршрута начинается со второй
строки сообщения, а номер в ошибке пользователь сверяет со своим сообщением целиком.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_route_parse.py
"""Разбор маршрута, присланного текстом."""
import pytest

import route


def names(pts):
    return [p.name for p in pts]


def test_plain_lines():
    pts = route.parse_text("42.4776, 44.4787, Гудаури старт\n42.2104, 44.6890, Пасанаури")
    assert [(p.lat, p.lon) for p in pts] == [(42.4776, 44.4787), (42.2104, 44.6890)]
    assert names(pts) == ["Гудаури старт", "Пасанаури"]


def test_decimal_comma():
    pts = route.parse_text("42,4776, 44,4787\n42,2104, 44,6890")
    assert (pts[0].lat, pts[0].lon) == (42.4776, 44.4787)


def test_google_maps_paste():
    pts = route.parse_text("42.4776,44.4787\n42.2104,44.6890")
    assert len(pts) == 2


def test_one_line_compact():
    pts = route.parse_text("42.4776,44.4787 42.3891,44.5512 42.2104,44.6890")
    assert len(pts) == 3
    assert (pts[1].lat, pts[1].lon) == (42.3891, 44.5512)


def test_name_with_digits_does_not_shift_coordinates():
    pts = route.parse_text("42.4776, 44.4787, Точка 3\n42.2104, 44.6890, Финиш")
    assert (pts[0].lat, pts[0].lon) == (42.4776, 44.4787)
    assert pts[0].name == "Точка 3"


def test_dms():
    pts = route.parse_text('42°28\'39"N 44°28\'43"E\n42°12\'37"N 44°41\'20"E')
    assert pts[0].lat == pytest.approx(42.4775, abs=1e-3)
    assert pts[0].lon == pytest.approx(44.4786, abs=1e-3)


def test_comments_and_blank_lines_skipped():
    pts = route.parse_text("# маршрут на завтра\n\n42.4776, 44.4787\n\n42.2104, 44.6890\n")
    assert len(pts) == 2


def test_single_point_rejected():
    with pytest.raises(route.RouteError) as e:
        route.parse_text("42.4776, 44.4787")
    assert "2" in str(e.value)


def test_too_many_points_rejected():
    body = "\n".join(f"42.{i:04d}, 44.4787" for i in range(51))
    with pytest.raises(route.RouteError):
        route.parse_text(body)


def test_bad_line_names_itself():
    with pytest.raises(route.RouteError) as e:
        route.parse_text("42.4776, 44.4787\nтут была координата")
    assert "тут была координата" in str(e.value)
    assert "2" in str(e.value)  # номер строки


def test_out_of_range_rejected():
    with pytest.raises(route.RouteError):
        route.parse_text("142.4776, 44.4787\n42.2104, 44.6890")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_route_parse.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'route'`

- [ ] **Step 3: Write minimal implementation**

```python
# route.py
"""Маршрут: разбор ввода, геометрия, время прибытия, маршрутные величины.

Модуль намеренно чистый — ни сети, ни aiogram, ни глобального состояния.
Всё, что здесь считается, проверяемо офлайн: геометрия и знаки ветра — ровно то
место, где ошибка выглядит правдоподобно и не ловится глазами.
"""
import math
import re

MIN_POINTS = 2
MAX_POINTS = 50           # потолок числа точек на входе


class RouteError(Exception):
    """Ошибка разбора маршрута, показываемая пользователю как есть."""


class Point:
    __slots__ = ("lat", "lon", "name")

    def __init__(self, lat, lon, name=None):
        self.lat, self.lon, self.name = float(lat), float(lon), name or None

    def __repr__(self):
        return f"Point({self.lat}, {self.lon}, {self.name!r})"

    def __eq__(self, other):
        return (isinstance(other, Point) and self.lat == other.lat
                and self.lon == other.lon and self.name == other.name)


# Запятая допускается как дробный разделитель прямо в шаблоне числа: тогда
# «42,4776, 44,4787» разбирается как два числа, а не как четыре, и отдельное
# правило склейки не нужно.
_NUM = re.compile(r"[-+]?\d{1,3}(?:[.,]\d+)?")
_DMS = re.compile(r"(\d{1,3})\s*°\s*(\d{1,2})\s*['′]\s*(\d{1,2}(?:[.,]\d+)?)\s*[\"″]?\s*([NSEWСЮВЗ])",
                  re.IGNORECASE)


def _num(text):
    return float(text.replace(",", "."))


def _dms_value(deg, minutes, seconds, hemi):
    v = int(deg) + int(minutes) / 60.0 + _num(seconds) / 3600.0
    return -v if hemi.upper() in ("S", "W", "Ю", "З") else v


def _parse_line(line):
    """Строка → Point, либо None для пустых и комментариев. RouteError на мусоре."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    dms = _DMS.findall(line)
    if len(dms) >= 2:
        lat = _dms_value(*dms[0])
        lon = _dms_value(*dms[1])
        return _checked(lat, lon, None, line)

    nums = list(_NUM.finditer(line))
    if len(nums) < 2:
        raise RouteError(f"не похоже на координаты: «{line}»")
    lat, lon = _num(nums[0].group()), _num(nums[1].group())
    name = line[nums[1].end():].strip(" ,;\t") or None
    return _checked(lat, lon, name, line)


def _checked(lat, lon, name, line):
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise RouteError(f"координаты вне допустимых пределов: «{line}»")
    return Point(lat, lon, name)


def parse_text(text, first_line_no=1):
    """Многострочный или однострочный список координат → точки маршрута.

    `first_line_no` — номер, под которым идёт первая строка `text` в исходном
    сообщении: бот отрезает строку с командой, а пользователь считает строки
    у себя целиком, и номер в ошибке должен совпадать с тем, что он видит.
    """
    lines = list(enumerate(text.splitlines(), first_line_no))
    meaningful = [(n, ln) for n, ln in lines
                  if ln.strip() and not ln.strip().startswith("#")]
    # Однострочный компактный вид: «lat,lon lat,lon lat,lon».
    if len(meaningful) == 1:
        n, only = meaningful[0]
        chunks = only.split()
        if len(chunks) >= MIN_POINTS and all("," in c or "." in c for c in chunks):
            lines = [(n, c) for c in chunks]

    points = []
    for n, line in lines:
        try:
            p = _parse_line(line)
        except RouteError as e:
            raise RouteError(f"строка {n}: {e}") from None
        if p is not None:
            points.append(p)
    return _checked_count(points)


def _checked_count(points):
    if len(points) < MIN_POINTS:
        raise RouteError(f"нужно минимум {MIN_POINTS} точки, прислана {len(points)}")
    if len(points) > MAX_POINTS:
        raise RouteError(f"слишком много точек: {len(points)}, максимум {MAX_POINTS}")
    return points
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_route_parse.py -q`
Expected: PASS, 11 passed

- [ ] **Step 5: Commit**

```bash
git add route.py tests/test_route_parse.py
git commit -m "feat(route): разбор маршрута, присланного текстом"
```

---

### Task 2: Разбор GPX

**Files:**
- Modify: `route.py`
- Test: `tests/test_route_gpx.py`

**Interfaces:**
- Consumes: `Point`, `RouteError`, `MAX_POINTS`, `_checked_count` из задачи 1
- Produces: `parse_gpx(data: bytes) -> tuple[list[Point], str | None]`; константа `MAX_GPX_BYTES = 1_048_576`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_route_gpx.py
"""Разбор GPX: приоритет rte → trk → wpt, прореживание трека, битые файлы."""
import pytest

import route

RTE = """<?xml version="1.0"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1"><name>Гудаури — Пасанаури</name>
<wpt lat="1.0" lon="1.0"><name>левая</name></wpt>
<rte><name>Основной</name>
<rtept lat="42.4776" lon="44.4787"><name>старт</name></rtept>
<rtept lat="42.2104" lon="44.6890"><name>финиш</name></rtept>
</rte></gpx>"""

TRK = """<?xml version="1.0"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Трек</name><trkseg>
{pts}
</trkseg></trk></gpx>"""

WPT_ONLY = """<?xml version="1.0"?>
<gpx><wpt lat="42.4776" lon="44.4787"><name>A</name></wpt>
<wpt lat="42.2104" lon="44.6890"><name>B</name></wpt></gpx>"""


def test_rte_wins_over_wpt():
    pts, name = route.parse_gpx(RTE.encode())
    assert [(p.lat, p.lon) for p in pts] == [(42.4776, 44.4787), (42.2104, 44.6890)]
    assert [p.name for p in pts] == ["старт", "финиш"]
    assert name == "Гудаури — Пасанаури"


def test_track_is_thinned_to_max_points():
    body = "\n".join(f'<trkpt lat="42.{i:04d}" lon="44.4787"/>' for i in range(2000))
    pts, _ = route.parse_gpx(TRK.format(pts=body).encode())
    assert len(pts) <= route.MAX_POINTS
    assert pts[0].lat == pytest.approx(42.0)
    assert pts[-1].lat == pytest.approx(42.1999)  # концы трека сохранены


def test_wpt_only():
    pts, _ = route.parse_gpx(WPT_ONLY.encode())
    assert len(pts) == 2


def test_no_namespace_parsed():
    xml = RTE.replace(' xmlns="http://www.topografix.com/GPX/1/1"', "")
    pts, _ = route.parse_gpx(xml.encode())
    assert len(pts) == 2


def test_broken_xml():
    with pytest.raises(route.RouteError):
        route.parse_gpx(b"<gpx><rte>")


def test_empty_gpx():
    with pytest.raises(route.RouteError) as e:
        route.parse_gpx(b'<?xml version="1.0"?><gpx></gpx>')
    assert "маршрут" in str(e.value).lower() or "точ" in str(e.value).lower()


def test_too_large_file():
    with pytest.raises(route.RouteError):
        route.parse_gpx(b"x" * (route.MAX_GPX_BYTES + 1))


def test_entity_bomb_rejected_before_parsing():
    """«Billion laughs»: килобайт разворачивается в гигабайты при разборе.
    xml.etree раскрывает внутренние сущности, поэтому объявления режутся до него."""
    bomb = (b'<?xml version="1.0"?><!DOCTYPE gpx ['
            b'<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
            b']><gpx><rte><rtept lat="42.0" lon="44.0"><name>&b;</name></rtept>'
            b'<rtept lat="42.1" lon="44.1"/></rte></gpx>')
    with pytest.raises(route.RouteError) as e:
        route.parse_gpx(bomb)
    assert "doctype" in str(e.value).lower() or "сущност" in str(e.value).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_route_gpx.py -q`
Expected: FAIL — `AttributeError: module 'route' has no attribute 'parse_gpx'`

- [ ] **Step 3: Write minimal implementation**

Добавить в `route.py` (импорт `xml.etree.ElementTree as ET` к остальным вверху файла):

```python
MAX_GPX_BYTES = 1_048_576     # 1 МБ: чужой трек на сотни тысяч точек не должен класть бота


def _tag(el):
    """Локальное имя тега без пространства имён — они у экспортёров разные."""
    return el.tag.rsplit("}", 1)[-1].lower()


def _find_all(root, name):
    return [el for el in root.iter() if _tag(el) == name]


def _child_name(el):
    for ch in el:
        if _tag(ch) == "name" and ch.text:
            return ch.text.strip()
    return None


def _points_from(elements):
    out = []
    for el in elements:
        try:
            out.append(Point(float(el.get("lat")), float(el.get("lon")), _child_name(el)))
        except (TypeError, ValueError):
            continue
    return out


def _thin(points, limit):
    """Равномерное прореживание с сохранением обоих концов."""
    if len(points) <= limit:
        return points
    step = (len(points) - 1) / (limit - 1)
    idx = sorted({round(i * step) for i in range(limit)} | {0, len(points) - 1})
    return [points[i] for i in idx][:limit]


def parse_gpx(data):
    """GPX → (точки, имя маршрута). Приоритет: <rte> → <trk> → <wpt>."""
    if len(data) > MAX_GPX_BYTES:
        raise RouteError(f"файл больше {MAX_GPX_BYTES // 1024} КБ — пришли маршрут покороче")
    # xml.etree раскрывает внутренние сущности, поэтому килобайтный файл с
    # вложенными <!ENTITY> разворачивается в гигабайты и съедает память бота
    # («billion laughs»). В настоящих GPX объявлений DTD не бывает — режем их
    # до разбора. Так обходимся без зависимости defusedxml.
    head = data[:4096].lstrip()
    if b"<!DOCTYPE" in head.upper() or b"<!ENTITY" in data.upper():
        raise RouteError("в файле есть объявления DOCTYPE или сущностей — "
                         "такой GPX не разбираю")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise RouteError(f"не удалось разобрать GPX: {e}") from None

    name = _child_name(root)
    for tag in ("rtept", "trkpt", "wpt"):
        points = _points_from(_find_all(root, tag))
        if points:
            return _checked_count(_thin(points, MAX_POINTS)), name
    raise RouteError("в GPX нет ни маршрута, ни трека, ни путевых точек")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_route_gpx.py -q`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add route.py tests/test_route_gpx.py
git commit -m "feat(route): разбор GPX с прореживанием трека"
```

---

### Task 3: Геометрия и ресэмплинг

**Files:**
- Modify: `route.py`
- Test: `tests/test_route_geometry.py`

**Interfaces:**
- Consumes: `Point` из задачи 1
- Produces: `haversine(a, b) -> (metres, bearing_deg)`; `Sample` (мутабельный dataclass со всеми полями профиля); `resample(points, step_km=SAMPLE_STEP_KM, max_samples=MAX_SAMPLES) -> (list[Sample], float)` — второй элемент фактический шаг; константы `SAMPLE_STEP_KM = 10.0`, `MAX_SAMPLES = 50`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_route_geometry.py
"""Геометрия маршрута: расстояние, пеленг, ресэмплинг."""
import pytest

import route

A = route.Point(42.4776, 44.4787, "старт")
B = route.Point(42.2104, 44.6890, "финиш")


def test_haversine_distance_and_bearing():
    d, brg = route.haversine(A, B)
    assert d / 1000.0 == pytest.approx(35.0, abs=1.5)
    assert brg == pytest.approx(150.0, abs=3.0)


def test_bearing_cardinal_directions():
    o = route.Point(0.0, 0.0)
    assert route.haversine(o, route.Point(1.0, 0.0))[1] == pytest.approx(0.0, abs=0.1)
    assert route.haversine(o, route.Point(0.0, 1.0))[1] == pytest.approx(90.0, abs=0.1)
    assert route.haversine(o, route.Point(-1.0, 0.0))[1] == pytest.approx(180.0, abs=0.1)
    assert route.haversine(o, route.Point(0.0, -1.0))[1] == pytest.approx(270.0, abs=0.1)


def test_bearing_across_antimeridian():
    d, brg = route.haversine(route.Point(0.0, 179.9), route.Point(0.0, -179.9))
    assert d / 1000.0 == pytest.approx(22.2, abs=1.0)
    assert brg == pytest.approx(90.0, abs=0.5)


def _straight_80km():
    """Две точки, разнесённые ровно на ~80 км по меридиану."""
    return [route.Point(42.0, 44.0, "A"), route.Point(42.0 + 80.0 / 111.195, 44.0, "B")]


def test_two_points_over_80km_give_nine_samples():
    samples, step = route.resample(_straight_80km(), step_km=10.0)
    assert len(samples) == 9
    assert step == pytest.approx(10.0)
    assert [round(s.km) for s in samples] == [0, 10, 20, 30, 40, 50, 60, 70, 80]


def test_turnpoints_are_kept_and_flagged():
    samples, _ = route.resample(_straight_80km(), step_km=10.0)
    assert [s.is_turnpoint for s in samples][0] is True
    assert [s.is_turnpoint for s in samples][-1] is True
    assert sum(s.is_turnpoint for s in samples) == 2
    assert samples[0].name == "A" and samples[-1].name == "B"


def test_roles_assigned():
    samples, _ = route.resample(_straight_80km(), step_km=10.0)
    assert samples[0].role == "takeoff"
    assert samples[-1].role == "goal"
    assert {s.role for s in samples[1:-1]} == {"enroute"}


def test_leg_lengths_sum_to_total():
    samples, _ = route.resample(_straight_80km(), step_km=10.0)
    assert sum(s.leg_length_km for s in samples) == pytest.approx(samples[-1].km, rel=1e-6)


def test_long_track_capped_at_max_samples():
    pts = [route.Point(42.0 + i * 0.05, 44.0) for i in range(50)]
    samples, step = route.resample(pts, step_km=10.0, max_samples=50)
    assert len(samples) <= 50
    assert step >= 10.0


def test_turnpoints_alone_may_fill_the_cap():
    pts = [route.Point(42.0 + i * 0.5, 44.0) for i in range(50)]
    samples, _ = route.resample(pts, step_km=10.0, max_samples=50)
    assert len(samples) == 50
    assert all(s.is_turnpoint for s in samples)


def test_track_bearing_of_last_sample_comes_from_previous():
    samples, _ = route.resample(_straight_80km(), step_km=10.0)
    assert samples[-1].track_bearing_deg == pytest.approx(samples[-2].track_bearing_deg, abs=0.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_route_geometry.py -q`
Expected: FAIL — `AttributeError: module 'route' has no attribute 'haversine'`

- [ ] **Step 3: Write minimal implementation**

Добавить в `route.py` (`from dataclasses import dataclass, field` вверху):

```python
EARTH_R_M = 6371008.8          # средний радиус Земли (IUGG)
SAMPLE_STEP_KM = 10.0          # разрешение глобальных моделей open-meteo — 9–11 км;
                               # точки чаще сетки дают ложную детализацию
MAX_SAMPLES = 50               # потолок числа погодных сэмплов


def haversine(a, b):
    """(расстояние в метрах, начальный пеленг в градусах) между двумя точками."""
    f1, f2 = math.radians(a.lat), math.radians(b.lat)
    df = f2 - f1
    dl = math.radians(b.lon - a.lon)
    h = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    dist = 2 * EARTH_R_M * math.asin(min(1.0, math.sqrt(h)))
    y = math.sin(dl) * math.cos(f2)
    x = math.cos(f1) * math.sin(f2) - math.sin(f1) * math.cos(f2) * math.cos(dl)
    return dist, (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


@dataclass
class Sample:
    """Точка, в которой запрашивается погода. Поля после `track_bearing_deg`
    дозаполняются последующими шагами конвейера."""
    km: float
    lat: float
    lon: float
    name: str | None = None
    role: str = "enroute"              # takeoff | enroute | goal
    is_turnpoint: bool = False
    leg_length_km: float = 0.0         # доля маршрута, которую представляет сэмпл
    track_bearing_deg: float = 0.0
    terrain_m: float | None = None
    terrain_point_m: float | None = None
    is_terrain_peak: bool = False
    cloud_base_m: float | None = None
    working_band_m: float | None = None
    wind_kmh: float | None = None
    wind_dir_deg: float | None = None
    wind_along_kmh: float | None = None
    wind_cross_kmh: float | None = None
    eta_h: float | None = None
    eta_fixed_h: float | None = None
    gs_kmh: float | None = None
    crab_limited: bool = False
    window: dict | None = None
    time_margin_min: float | None = None
    w_star_ms: float | None = None
    site_match: str | None = None
    weather: dict = field(default_factory=dict)


def _lerp_point(a, b, f):
    """Точка на доле f отрезка. Линейно по широте и долготе: на плече до 100 км
    отклонение от дуги большого круга меньше 100 м, то есть на порядок меньше
    шага погодной сетки."""
    return Point(a.lat + (b.lat - a.lat) * f, a.lon + (b.lon - a.lon) * f)


def resample(points, step_km=SAMPLE_STEP_KM, max_samples=MAX_SAMPLES):
    """Точки маршрута → погодные сэмплы. Возвращает (сэмплы, фактический шаг).

    Поворотные точки включаются всегда, даже если их одних уже `max_samples`;
    промежуточные добираются только до потолка. Шаг считается один раз, а не
    подбирается циклом, — так результат детерминирован.
    """
    legs = []
    for a, b in zip(points, points[1:]):
        d, brg = haversine(a, b)
        legs.append((a, b, d / 1000.0, brg))
    total_km = sum(leg[2] for leg in legs)
    free = max_samples - len(points)
    step = step_km if free <= 0 else max(step_km, total_km / (free + 1))

    samples, km = [], 0.0
    for i, (a, b, length, brg) in enumerate(legs):
        samples.append(Sample(km=km, lat=a.lat, lon=a.lon, name=a.name,
                              is_turnpoint=True, track_bearing_deg=brg))
        n_inner = max(0, math.ceil(length / step) - 1)
        for k in range(1, n_inner + 1):
            f = k / (n_inner + 1)
            p = _lerp_point(a, b, f)
            samples.append(Sample(km=km + length * f, lat=p.lat, lon=p.lon,
                                  track_bearing_deg=brg))
        km += length
    last = points[-1]
    samples.append(Sample(km=km, lat=last.lat, lon=last.lon, name=last.name,
                          is_turnpoint=True,
                          track_bearing_deg=legs[-1][3] if legs else 0.0))

    samples[0].role = "takeoff"
    samples[-1].role = "goal"
    _set_leg_lengths(samples)
    return samples, step


def _set_leg_lengths(samples):
    """Каждому сэмплу — половина расстояния до соседа слева и справа; концам
    только их половина. Сумма при этом ровно равна длине маршрута, и её можно
    использовать как вес при усреднении по маршруту (спека 2)."""
    for i, s in enumerate(samples):
        left = (s.km - samples[i - 1].km) / 2 if i > 0 else 0.0
        right = (samples[i + 1].km - s.km) / 2 if i < len(samples) - 1 else 0.0
        s.leg_length_km = left + right
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_route_geometry.py -q`
Expected: PASS, 10 passed

- [ ] **Step 5: Commit**

```bash
git add route.py tests/test_route_geometry.py
git commit -m "feat(route): haversine, пеленг и ресэмплинг маршрута"
```

---

### Task 4: Рельефная сетка и высоты на сэмплах

**Files:**
- Modify: `route.py`
- Test: `tests/test_route_terrain.py`

**Interfaces:**
- Consumes: `Sample`, `haversine`, `_lerp_point` из задачи 3
- Produces: `terrain_grid(points, total_km) -> list[tuple[float, float, float]]` (км, широта, долгота); `attach_terrain(samples, grid, elevations, step_km) -> None`; константы `TERRAIN_STEP_KM = 1.0`, `TERRAIN_STEP_SHORT_KM = 0.5`, `TERRAIN_SHORT_KM = 50.0`, `PEAK_WINDOW_KM = 5.0`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_route_terrain.py
"""Рельеф: своя сетка, максимум по участку сэмпла, отметка вершины."""
import pytest

import route

PTS = [route.Point(42.0, 44.0), route.Point(42.0 + 40.0 / 111.195, 44.0)]


def test_grid_step_depends_on_route_length():
    grid_short = route.terrain_grid(PTS, total_km=40.0)
    assert grid_short[1][0] - grid_short[0][0] == pytest.approx(0.5, abs=0.05)
    grid_long = route.terrain_grid(PTS, total_km=120.0)
    assert grid_long[1][0] - grid_long[0][0] == pytest.approx(1.0, abs=0.05)


def test_grid_covers_whole_route():
    grid = route.terrain_grid(PTS, total_km=120.0)
    assert grid[0][0] == pytest.approx(0.0)
    assert grid[-1][0] == pytest.approx(40.0, abs=1.0)


def test_sample_terrain_is_max_over_its_segment():
    samples, step = route.resample(PTS, step_km=10.0)
    grid = route.terrain_grid(PTS, total_km=40.0)
    # ровное плато 1000 м, но на 21-м километре гребень 2500 м
    elev = [2500.0 if 20.5 <= km <= 21.5 else 1000.0 for km, _, _ in grid]
    route.attach_terrain(samples, grid, elev, step_km=step)
    at20 = next(s for s in samples if round(s.km) == 20)
    assert at20.terrain_m == 2500.0        # гребень попал в участок сэмпла
    assert at20.terrain_point_m == 1000.0  # под самой точкой — плато
    at0 = samples[0]
    assert at0.terrain_m == 1000.0


def test_terrain_peak_flag():
    samples, step = route.resample(PTS, step_km=10.0)
    grid = route.terrain_grid(PTS, total_km=40.0)
    elev = [2500.0 if 19.0 <= km <= 21.0 else 1000.0 for km, _, _ in grid]
    route.attach_terrain(samples, grid, elev, step_km=step)
    assert next(s for s in samples if round(s.km) == 20).is_terrain_peak is True
    assert samples[0].is_terrain_peak is False


def test_missing_elevations_leave_none():
    samples, step = route.resample(PTS, step_km=10.0)
    route.attach_terrain(samples, [], None, step_km=step)
    assert all(s.terrain_m is None for s in samples)
    assert all(s.is_terrain_peak is False for s in samples)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_route_terrain.py -q`
Expected: FAIL — `AttributeError: module 'route' has no attribute 'terrain_grid'`

- [ ] **Step 3: Write minimal implementation**

```python
TERRAIN_STEP_KM = 1.0          # шаг рельефной сетки для маршрутов от 50 км
TERRAIN_STEP_SHORT_KM = 0.5    # для маршрутов короче — вдвое чаще
TERRAIN_SHORT_KM = 50.0
PEAK_WINDOW_KM = 5.0           # окно поиска локального максимума рельефа


def terrain_step_for(total_km):
    return TERRAIN_STEP_SHORT_KM if total_km < TERRAIN_SHORT_KM else TERRAIN_STEP_KM


def terrain_grid(points, total_km):
    """Отдельная, более частая сетка для рельефа: [(км, широта, долгота), ...].

    Она гуще погодной намеренно: погоду частить бессмысленно (сетка модели 9–11 км),
    а рельеф между погодными точками меняется на километр и решает вопрос перехода.
    """
    step = terrain_step_for(total_km)
    legs = []
    for a, b in zip(points, points[1:]):
        legs.append((a, b, haversine(a, b)[0] / 1000.0))
    out, km = [], 0.0
    for a, b, length in legs:
        n = max(1, int(round(length / step)))
        for k in range(n):
            p = _lerp_point(a, b, k / n)
            out.append((km + length * k / n, p.lat, p.lon))
        km += length
    out.append((km, points[-1].lat, points[-1].lon))
    return out


def attach_terrain(samples, grid, elevations, step_km):
    """Проставить сэмплам высоты. `elevations` — None, если рельеф не получен.

    `terrain_m` — МАКСИМУМ по участку сэмпла, а не высота под точкой: вопрос
    пилота на переходе решает гребень, а не долина, случайно оказавшаяся под
    точкой сетки. Высота под точкой остаётся справочной в `terrain_point_m`.
    """
    if not elevations or not grid:
        return
    half = step_km / 2.0
    for s in samples:
        near = [e for (km, _, _), e in zip(grid, elevations) if abs(km - s.km) <= half]
        s.terrain_m = max(near) if near else None
        closest = min(range(len(grid)), key=lambda i: abs(grid[i][0] - s.km))
        s.terrain_point_m = elevations[closest]
        window = [e for (km, _, _), e in zip(grid, elevations)
                  if abs(km - s.km) <= PEAK_WINDOW_KM]
        s.is_terrain_peak = bool(window) and s.terrain_point_m >= max(window)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_route_terrain.py -q`
Expected: PASS, 5 passed

Примечание: `test_terrain_peak_flag` требует, чтобы у сэмпла на 0 км флаг был снят — плато 1000 м не является максимумом в окне ±5 км, потому что в него не попадает гребень. Если тест падает, проверь знак сравнения: вершина — это `>=` максимума окна, а не `>`.

- [ ] **Step 5: Commit**

```bash
git add route.py tests/test_route_terrain.py
git commit -m "feat(route): рельефная сетка и высоты на сэмплах"
```

---

### Task 5: Проекции ветра, база облаков, рабочий диапазон

**Files:**
- Modify: `route.py`
- Test: `tests/test_route_wind.py`

**Interfaces:**
- Consumes: `criteria.LCL_M_PER_C`
- Produces: `wind_components(speed, dir_from_deg, track_bearing_deg) -> (along, cross)`; `cloud_base_m(terrain_m, t2m, dew2m) -> float | None`; `working_band_m(cloud_base, terrain_m) -> float | None`; `ms_to_kmh(v)`; константа `MIN_WORKING_ALT_AGL = 300`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_route_wind.py
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
    (0, 90, 0, -1),      # север при курсе на восток — сносит влево
    (180, 90, 0, +1),    # юг при курсе на восток — сносит вправо
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_route_wind.py -q`
Expected: FAIL — `AttributeError: module 'route' has no attribute 'wind_components'`

- [ ] **Step 3: Write minimal implementation**

Добавить `import criteria` вверху `route.py`:

```python
MIN_WORKING_ALT_AGL = 300      # ниже пилот не идёт на переход, а ищет площадку
MS_TO_KMH = 3.6


def ms_to_kmh(v):
    return None if v is None else v * MS_TO_KMH


def wind_components(speed, dir_from_deg, track_bearing_deg):
    """Составляющие ветра вдоль и поперёк курса.

    θ — направление, ОТКУДА дует; φ — пеленг курса, КУДА летим.
        wind_along = −V·cos(θ − φ)   > 0 попутный,   < 0 встречный
        wind_cross = −V·sin(θ − φ)   > 0 сносит вправо от трека
    Проверка: ветер с запада (θ=270), курс на восток (φ=90) → θ−φ=180,
    cos=−1, along=+V, то есть попутный.
    """
    if speed is None or dir_from_deg is None:
        return None, None
    d = math.radians(dir_from_deg - track_bearing_deg)
    return -speed * math.cos(d), -speed * math.sin(d)


def cloud_base_m(terrain_m, t2m, dew2m):
    """База термических кучевых над уровнем моря.

    Коэффициент — `criteria.LCL_M_PER_C`, второй копии числа в репозитории нет.
    Формула неприменима при слоистой облачности; на маршруте это встречается
    чаще, чем над одним стартом, потому что маршрут пересекает разные массы.
    """
    if terrain_m is None or t2m is None or dew2m is None:
        return None
    return terrain_m + criteria.LCL_M_PER_C * (t2m - dew2m)


def working_band_m(cloud_base, terrain_m):
    """Высота между безопасной высотой над рельефом и базой облаков."""
    if cloud_base is None or terrain_m is None:
        return None
    return cloud_base - (terrain_m + MIN_WORKING_ALT_AGL)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_route_wind.py -q`
Expected: PASS, 15 passed

- [ ] **Step 5: Commit**

```bash
git add route.py tests/test_route_wind.py
git commit -m "feat(route): проекции ветра, база облаков, рабочий диапазон"
```

---

### Task 6: Интерполяция по времени

**Files:**
- Modify: `route.py`
- Test: `tests/test_route_interp.py`

**Interfaces:**
- Consumes: ничего
- Produces: `interp(series, hour) -> float | None`; `interp_wind(speeds, dirs, hour) -> (speed, dir)`; `worst_of_hours(series, hour) -> float | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_route_interp.py
"""Интерполяция почасовых рядов на дробный час прибытия."""
import pytest

import route


def const(v):
    return [v] * 24


def test_linear_between_hours():
    s = const(0.0)
    s[12], s[13] = 10.0, 20.0
    assert route.interp(s, 12.0) == pytest.approx(10.0)
    assert route.interp(s, 12.5) == pytest.approx(15.0)
    assert route.interp(s, 13.0) == pytest.approx(20.0)


def test_none_in_series_gives_none():
    s = const(1.0)
    s[12] = None
    assert route.interp(s, 12.4) is None


def test_out_of_range_gives_none():
    assert route.interp(const(1.0), 24.5) is None
    assert route.interp(const(1.0), -1.0) is None


def test_wind_direction_across_north_does_not_flip():
    speeds, dirs = const(10.0), const(0.0)
    dirs[12], dirs[13] = 350.0, 10.0
    speed, deg = route.interp_wind(speeds, dirs, 12.5)
    assert deg == pytest.approx(0.0, abs=0.5) or deg == pytest.approx(360.0, abs=0.5)
    assert speed == pytest.approx(9.85, abs=0.1)


def test_wind_direction_plain_case():
    speeds, dirs = const(10.0), const(0.0)
    dirs[12], dirs[13] = 180.0, 200.0
    _, deg = route.interp_wind(speeds, dirs, 12.5)
    assert deg == pytest.approx(190.0, abs=0.5)


def test_precipitation_takes_worst_of_two_hours():
    s = const(0.0)
    s[12], s[13] = 0.0, 2.0
    assert route.worst_of_hours(s, 12.5) == pytest.approx(2.0)
    assert route.worst_of_hours(s, 12.0) == pytest.approx(2.0)


def test_worst_of_hours_ignores_none():
    s = const(0.0)
    s[12], s[13] = None, 2.0
    assert route.worst_of_hours(s, 12.5) == pytest.approx(2.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_route_interp.py -q`
Expected: FAIL — `AttributeError: module 'route' has no attribute 'interp'`

- [ ] **Step 3: Write minimal implementation**

Добавить `import engine` вверху `route.py` (нужен `engine._uv`):

```python
def _bracket(series, hour):
    """(значение часа, значение следующего часа, доля) либо None вне ряда."""
    if series is None or hour is None or hour < 0:
        return None
    i = int(math.floor(hour))
    if i >= len(series):
        return None
    nxt = series[i + 1] if i + 1 < len(series) else series[i]
    return series[i], nxt, hour - i


def interp(series, hour):
    """Линейная интерполяция непрерывной величины между целыми часами."""
    br = _bracket(series, hour)
    if br is None:
        return None
    a, b, f = br
    if a is None:
        return None
    if b is None or f == 0:
        return a
    return a + f * (b - a)


def interp_wind(speeds, dirs, hour):
    """Ветер на дробный час — ТОЛЬКО через u/v.

    Линейная интерполяция самих углов на переходе через 0°/360° даёт ошибку в
    сотни градусов: между 350° и 10° она выдаёт 180°, то есть ровно
    противоположное направление.
    """
    bs, bd = _bracket(speeds, hour), _bracket(dirs, hour)
    if bs is None or bd is None:
        return None, None
    (s1, s2, f), (d1, d2, _) = bs, bd
    if None in (s1, d1):
        return None, None
    if s2 is None or d2 is None:
        s2, d2 = s1, d1
    u1, v1 = engine._uv(s1, d1)
    u2, v2 = engine._uv(s2, d2)
    u, v = u1 + f * (u2 - u1), v1 + f * (v2 - v1)
    speed = math.hypot(u, v)
    deg = (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0
    return speed, deg


def worst_of_hours(series, hour):
    """Худшее из двух соседних часов, без интерполяции.

    Осадки за час — накопление, а не мгновенное значение; интерполяция
    размазывает ливень в морось ровно там, где это опаснее всего.
    """
    br = _bracket(series, hour)
    if br is None:
        return None
    vals = [v for v in br[:2] if v is not None]
    return max(vals) if vals else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_route_interp.py -q`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add route.py tests/test_route_interp.py
git commit -m "feat(route): интерполяция погоды на дробный час прибытия"
```

---

### Task 7: Термическое окно в точке маршрута

**Files:**
- Modify: `route.py`
- Test: `tests/test_route_window.py`

**Interfaces:**
- Consumes: `engine.sun_hours`, `engine.hour_of`
- Produces: `thermal_window(date_iso, lat, sunrise, sunset, blh, radiation) -> dict | None`; `time_margin_min(window, eta_h) -> float | None`; константы `BLH_WORKING_M = 500`, `RADIATION_WORKING_WM2 = 150`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_route_window.py
"""Термическое окно в точке маршрута — пересечение солнечной рамки и порогов."""
import pytest

import route

DATE, SR, SS = "2026-07-25", "2026-07-25T05:00", "2026-07-25T20:00"


def series(value, hours=None, other=0.0):
    """24 часа `other`, а в перечисленных часах — `value`."""
    out = [other] * 24
    for h in (hours or range(24)):
        out[h] = value
    return out


def test_thresholds_narrow_the_solar_frame():
    blh = series(1500.0, range(11, 16))       # конвекция работает только 11–15
    rad = series(700.0, range(11, 16))
    w = route.thermal_window(DATE, 42.0, SR, SS, blh, rad)
    assert w == {"open_hour": 11, "close_hour": 15}


def test_solar_frame_narrows_the_thresholds():
    blh, rad = series(1500.0), series(700.0)  # пороги открыты все сутки
    w = route.thermal_window(DATE, 42.0, SR, SS, blh, rad)
    assert w["open_hour"] >= 7                # солнце не даёт открыть окно ночью
    assert w["close_hour"] <= 19


def test_no_working_hours_gives_none():
    blh, rad = series(100.0), series(10.0)
    assert route.thermal_window(DATE, 42.0, SR, SS, blh, rad) is None


def test_missing_series_gives_none():
    assert route.thermal_window(DATE, 42.0, SR, SS, None, None) is None


def test_time_margin_measured_to_end_of_last_working_hour():
    w = {"open_hour": 11, "close_hour": 15}
    assert route.time_margin_min(w, 14.0) == pytest.approx(120.0)   # до 16:00
    assert route.time_margin_min(w, 16.5) == pytest.approx(-30.0)


def test_time_margin_none_without_window():
    assert route.time_margin_min(None, 14.0) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_route_window.py -q`
Expected: FAIL — `AttributeError: module 'route' has no attribute 'thermal_window'`

- [ ] **Step 3: Write minimal implementation**

```python
BLH_WORKING_M = 500            # ниже пограничного слоя термичка не рабочая
RADIATION_WORKING_WM2 = 150    # ниже радиации склон не успевает греть


def thermal_window(date_iso, lat, sunrise, sunset, blh, radiation):
    """Окно термической активности в точке маршрута — ПЕРЕСЕЧЕНИЕ двух определений.

    Геометрия солнца даёт астрономическую рамку (экспозиция не передаётся: в
    воздухе склона нет, и `sun_hours` в этом случае опирается на высоту солнца).
    Пороги пограничного слоя и радиации внутри рамки отрезают часы, когда
    конвекция фактически не работает. По отдельности каждое определение врёт в
    свою сторону: солнечное растягивает окно на весь световой день, пороговое
    способно открыть окно в шесть утра.
    """
    if not blh or not radiation:
        return None
    lo, hi = engine.hour_of(sunrise), engine.hour_of(sunset)
    _rows, sun = engine.sun_hours(date_iso, lat, sunrise, sunset,
                                  list(range(lo, hi + 1)), None)
    if not sun:
        return None
    working = [h for h in range(sun["start_hour"], sun["end_hour"] + 1)
               if h < len(blh) and h < len(radiation)
               and (blh[h] or 0) > BLH_WORKING_M
               and (radiation[h] or 0) > RADIATION_WORKING_WM2]
    if not working:
        return None
    return {"open_hour": working[0], "close_hour": working[-1]}


def time_margin_min(window, eta_h):
    """Минуты до конца окна. Конец — граница последнего рабочего часа."""
    if not window or eta_h is None:
        return None
    return (window["close_hour"] + 1 - eta_h) * 60.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_route_window.py -q`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add route.py tests/test_route_window.py
git commit -m "feat(route): термическое окно в точке как пересечение солнца и порогов"
```

---

### Task 8: Время прибытия — марш вперёд с учётом ветра

**Files:**
- Modify: `route.py`
- Test: `tests/test_route_eta.py`

**Interfaces:**
- Consumes: `Sample` из задачи 3
- Produces: `ground_speed(va_kmh, along_kmh, cross_kmh) -> (gs, crab_limited)`; `march(samples, speed_kmh, wind_for_segment, departure_h) -> None`; `fixed_eta(samples, speed_kmh, departure_h) -> None`; константы `MIN_GROUND_SPEED_KMH = 8.0`, `ETA_WARN_MIN = 20`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_route_eta.py
"""Время прибытия: путевая скорость с крабингом и марш вперёд по сегментам."""
import pytest

import route

PTS = [route.Point(42.0, 44.0), route.Point(42.0 + 80.0 / 111.195, 44.0)]


def samples():
    s, _ = route.resample(PTS, step_km=20.0)
    return s


def test_ground_speed_pure_tailwind():
    gs, limited = route.ground_speed(25.0, 10.0, 0.0)
    assert gs == pytest.approx(35.0)
    assert limited is False


def test_ground_speed_crab_costs_speed():
    gs, _ = route.ground_speed(25.0, 0.0, 15.0)
    assert gs == pytest.approx(20.0, abs=0.1)   # 25·cos(asin(0.6)) = 20


def test_ground_speed_floor():
    gs, _ = route.ground_speed(25.0, -30.0, 0.0)
    assert gs == pytest.approx(route.MIN_GROUND_SPEED_KMH)


def test_crab_limited_when_cross_exceeds_airspeed():
    gs, limited = route.ground_speed(25.0, 0.0, 26.0)
    assert limited is True
    assert gs == pytest.approx(route.MIN_GROUND_SPEED_KMH)


def test_fixed_eta_is_plain_division():
    s = samples()
    route.fixed_eta(s, 25.0, 11.5)
    assert s[0].eta_fixed_h == pytest.approx(11.5)
    assert s[-1].eta_fixed_h == pytest.approx(11.5 + 80.0 / 25.0, abs=0.01)


def test_headwind_arrival_is_later_than_fixed():
    s = samples()
    route.fixed_eta(s, 25.0, 11.5)
    route.march(s, 25.0, lambda i, hour: (-10.0, 0.0), 11.5)
    assert s[-1].eta_h > s[-1].eta_fixed_h
    assert s[-1].eta_h == pytest.approx(11.5 + 80.0 / 15.0, abs=0.01)


def test_tailwind_arrival_is_earlier_than_fixed():
    s = samples()
    route.fixed_eta(s, 25.0, 11.5)
    route.march(s, 25.0, lambda i, hour: (10.0, 0.0), 11.5)
    assert s[-1].eta_h < s[-1].eta_fixed_h


def test_wind_is_sampled_at_the_time_already_computed():
    seen = []

    def wind(i, hour):
        seen.append((i, round(hour, 3)))
        return (0.0, 0.0)

    s = samples()
    route.march(s, 25.0, wind, 11.5)
    assert seen[0] == (0, 11.5)
    # второй сегмент опрашивается уже на времени прибытия в первую точку
    assert seen[1][1] == pytest.approx(11.5 + 20.0 / 25.0, abs=0.01)


def test_crab_limit_is_recorded_on_the_sample():
    s = samples()
    route.march(s, 25.0, lambda i, hour: (0.0, 30.0), 11.5)
    assert any(x.crab_limited for x in s)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_route_eta.py -q`
Expected: FAIL — `AttributeError: module 'route' has no attribute 'ground_speed'`

- [ ] **Step 3: Write minimal implementation**

```python
MIN_GROUND_SPEED_KMH = 8.0     # ниже этого маршрут практически не идётся
ETA_WARN_MIN = 20              # расхождение времён прилёта, с которого предупреждаем


def ground_speed(va_kmh, along_kmh, cross_kmh):
    """Путевая скорость вдоль трека с учётом крабинга → (скорость, упёрлись ли).

    Боковой ветер съедает скорость дважды: часть воздушной скорости уходит на
    компенсацию сноса (угол WCA), и только косинус этого угла работает вперёд.
    """
    along = along_kmh or 0.0
    cross = cross_kmh or 0.0
    ratio = cross / va_kmh if va_kmh else 0.0
    limited = abs(ratio) >= 1.0
    wca = math.asin(max(-1.0, min(1.0, ratio)))
    gs = va_kmh * math.cos(wca) + along
    return max(gs, MIN_GROUND_SPEED_KMH), limited


def fixed_eta(samples, speed_kmh, departure_h):
    """Время прибытия по фиксированной скорости — справочное."""
    for s in samples:
        s.eta_fixed_h = departure_h + s.km / speed_kmh


def march(samples, speed_kmh, wind_for_segment, departure_h):
    """Время прибытия с учётом ветра — одним проходом вперёд.

    `wind_for_segment(i, hour)` возвращает (вдоль, поперёк) в км/ч для сегмента
    между сэмплами i и i+1, оценённые на переданный час. Круговой зависимости
    нет: время каждой точки опирается только на уже посчитанные, итерация до
    сходимости не нужна. Побочный эффект: при резком усилении ветра ВНУТРИ
    сегмента время слегка занижается.
    """
    samples[0].eta_h = departure_h
    samples[0].gs_kmh = speed_kmh
    for i in range(len(samples) - 1):
        along, cross = wind_for_segment(i, samples[i].eta_h)
        gs, limited = ground_speed(speed_kmh, along, cross)
        leg = samples[i + 1].km - samples[i].km
        samples[i + 1].eta_h = samples[i].eta_h + leg / gs
        samples[i + 1].gs_kmh = gs
        samples[i + 1].crab_limited = limited
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_route_eta.py -q`
Expected: PASS, 9 passed

- [ ] **Step 5: Commit**

```bash
git add route.py tests/test_route_eta.py
git commit -m "feat(route): время прибытия маршем вперёд с учётом крабинга"
```

---

### Task 9: Глобальные настройки маршрута

**Files:**
- Create: `settings.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `engine.SITES`
- Produces: `settings.get() -> dict`; `settings.set_speed(v)`; `settings.set_wind_correction(on)`; `settings.SETTINGS_FILE`; `settings.SPEED_MIN = 10.0`, `settings.SPEED_MAX = 45.0`, `settings.DEFAULTS`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings.py
"""Глобальные настройки маршрута: дефолты, валидация, устойчивость к порче файла."""
import json
import os

import pytest

import settings


def test_defaults_when_file_absent():
    assert settings.get() == settings.DEFAULTS
    assert settings.DEFAULTS["avg_route_speed_kmh"] == 25.0
    assert settings.DEFAULTS["wind_correction_enabled"] is True


def test_speed_round_trip():
    settings.set_speed(30.0)
    assert settings.get()["avg_route_speed_kmh"] == 30.0


def test_wind_correction_round_trip():
    settings.set_wind_correction(False)
    assert settings.get()["wind_correction_enabled"] is False
    assert settings.get()["avg_route_speed_kmh"] == 25.0   # соседнее поле не потеряно


@pytest.mark.parametrize("bad", [9.9, 45.1, 0.0, -5.0])
def test_speed_out_of_range_rejected(bad):
    with pytest.raises(ValueError) as e:
        settings.set_speed(bad)
    assert "средняя" in str(e.value).lower()


def test_corrupt_file_falls_back_to_defaults():
    with open(settings.SETTINGS_FILE, "w", encoding="utf-8") as f:
        f.write("{не json")
    assert settings.get() == settings.DEFAULTS


def test_unknown_keys_ignored():
    with open(settings.SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump({"avg_route_speed_kmh": 28.0, "мусор": 1}, f)
    got = settings.get()
    assert got["avg_route_speed_kmh"] == 28.0
    assert "мусор" not in got


def test_settings_file_lives_next_to_sites():
    import engine
    assert os.path.dirname(settings.SETTINGS_FILE) == os.path.dirname(engine.SITES)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'settings'`

- [ ] **Step 3: Write minimal implementation**

```python
# settings.py
"""Глобальные настройки маршрута — один файл на бота, как выбор метеомодели.

Настройка метеомодели живёт в engine.py и сюда не переезжает: там она оправдана
тем, что build_url использует её напрямую. У маршрутных настроек такой привязки
нет, поэтому им отдельный файл.
"""
import json
import os

import engine

SETTINGS_FILE = (os.environ.get("SETTINGS_FILE")
                 or os.path.join(os.path.dirname(engine.SITES) or ".", "settings.json"))

# 25 км/ч — разумный дефолт для уверенного XC-пилота на B+. Реальный разброс:
# 18–22 в слабый день, 25–30 в рабочий, 30–35 у сильных пилотов на коротком маршруте.
DEFAULTS = {"avg_route_speed_kmh": 25.0, "wind_correction_enabled": True}
SPEED_MIN, SPEED_MAX = 10.0, 45.0


def get():
    """Текущие настройки; дефолты при отсутствии, порче или чужих ключах."""
    out = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return out
    if not isinstance(raw, dict):
        return out
    for key in DEFAULTS:
        if key in raw:
            out[key] = raw[key]
    return out


def _save(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def set_speed(value):
    """Средняя маршрутная скорость в км/ч. ValueError вне допустимого диапазона."""
    value = float(value)
    if not SPEED_MIN <= value <= SPEED_MAX:
        raise ValueError(
            f"средняя маршрутная скорость должна быть от {SPEED_MIN:.0f} до {SPEED_MAX:.0f} км/ч. "
            "Это средняя по маршруту с учётом наборов в термиках, а не скорость крыла.")
    data = get()
    data["avg_route_speed_kmh"] = value
    _save(data)


def set_wind_correction(on):
    data = get()
    data["wind_correction_enabled"] = bool(on)
    _save(data)
```

В `tests/conftest.py` добавить сброс — рядом с уже существующим удалением `engine.MODEL_FILE` в фикстуре `fresh_state`:

```python
import settings  # noqa: E402  — к остальным импортам сверху

    # ... внутри fresh_state, сразу после удаления MODEL_FILE:
    if os.path.exists(settings.SETTINGS_FILE):  # каждый тест стартует с дефолтов
        os.remove(settings.SETTINGS_FILE)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_settings.py -q && .venv/bin/python -m pytest -q`
Expected: PASS, 10 passed в файле; весь набор зелёный

- [ ] **Step 5: Commit**

```bash
git add settings.py tests/test_settings.py tests/conftest.py
git commit -m "feat(settings): глобальные настройки маршрута"
```

---

### Task 10: Мульти-точечный запрос и осреднение ветра по слою

**Files:**
- Modify: `engine.py`
- Test: `tests/test_engine_route.py`

**Interfaces:**
- Consumes: `engine.H_1D`, `engine.D_1D`, `engine._at`, `engine._uv`, `engine.model_id`, `engine.get_model_key`
- Produces: `engine.route_weather_url(coords, date, tz) -> str` (coords — список пар `(lat, lon)`); `engine.mean_wind_vector(H, i, elev, lo_msl, hi_msl) -> (speed_ms, dir_from_deg)`; `engine._levels_with_dir(H, i, elev)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine_route.py
"""Мульти-точечный URL и векторное осреднение ветра по рабочему слою."""
import pytest

import engine
from fixtures import om_1day

COORDS = [(42.4776, 44.4787), (42.3891, 44.5512), (42.2104, 44.6890)]


def test_url_lists_all_coordinates():
    url = engine.route_weather_url(COORDS, "2026-07-28", "Asia/Tbilisi")
    assert "latitude=42.4776,42.3891,42.2104" in url
    assert "longitude=44.4787,44.5512,44.6890" in url


def test_url_pins_timezone_explicitly():
    url = engine.route_weather_url(COORDS, "2026-07-28", "Asia/Tbilisi")
    assert "timezone=Asia%2FTbilisi" in url or "timezone=Asia/Tbilisi" in url
    assert "timezone=auto" not in url


def test_url_asks_one_day_with_the_full_variable_set():
    url = engine.route_weather_url(COORDS, "2026-07-28", "Asia/Tbilisi")
    assert "start_date=2026-07-28&end_date=2026-07-28" in url
    assert engine.H_1D in url


def test_mean_wind_vector_averages_levels_in_the_layer():
    data = om_1day(wind_speed_925hPa=6.0, wind_direction_925hPa=180.0,
                   wind_speed_850hPa=10.0, wind_direction_850hPa=180.0,
                   geopotential_height_925hPa=1500.0, geopotential_height_850hPa=2000.0)
    speed, deg = engine.mean_wind_vector(data["hourly"], 12, 1000.0, 1400.0, 2100.0)
    assert speed == pytest.approx(8.0, abs=0.1)
    assert deg == pytest.approx(180.0, abs=0.5)


def test_opposite_directions_cancel_vectorially():
    """Осреднение модулей дало бы 10 м/с; векторное — почти ноль. Именно в этом
    смысл требования осреднять u/v, а не скорости."""
    data = om_1day(wind_speed_925hPa=10.0, wind_direction_925hPa=0.0,
                   wind_speed_850hPa=10.0, wind_direction_850hPa=180.0,
                   geopotential_height_925hPa=1500.0, geopotential_height_850hPa=2000.0)
    speed, _ = engine.mean_wind_vector(data["hourly"], 12, 1000.0, 1400.0, 2100.0)
    assert speed == pytest.approx(0.0, abs=0.2)


def test_levels_below_the_layer_are_dropped():
    data = om_1day(wind_speed_10m=20.0, wind_direction_10m=90.0,
                   wind_speed_925hPa=5.0, wind_direction_925hPa=180.0,
                   geopotential_height_925hPa=1500.0,
                   geopotential_height_850hPa=2000.0, wind_speed_850hPa=5.0,
                   wind_direction_850hPa=180.0)
    speed, deg = engine.mean_wind_vector(data["hourly"], 12, 1000.0, 1400.0, 2100.0)
    assert deg == pytest.approx(180.0, abs=1.0)   # приземный ветер не участвует
    assert speed == pytest.approx(5.0, abs=0.2)


def test_empty_layer_falls_back_to_nearest_level():
    data = om_1day(geopotential_height_925hPa=1500.0, geopotential_height_850hPa=3000.0)
    speed, deg = engine.mean_wind_vector(data["hourly"], 12, 1000.0, 1900.0, 2000.0)
    assert speed is not None and deg is not None


def test_no_levels_at_all_gives_none():
    data = om_1day(wind_speed_10m=None, wind_speed_80m=None, wind_speed_120m=None,
                   wind_speed_925hPa=None, wind_speed_850hPa=None, wind_speed_700hPa=None)
    assert engine.mean_wind_vector(data["hourly"], 12, 1000.0, 1400.0, 2100.0) == (None, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_engine_route.py -q`
Expected: FAIL — `AttributeError: module 'engine' has no attribute 'route_weather_url'`

- [ ] **Step 3: Write minimal implementation**

В `engine.py`, рядом с `build_url`, добавить (и `from urllib.parse import quote` к импортам):

```python
def route_weather_url(coords, date, tz):
    """Мульти-точечный запрос погоды на один день.

    Часовой пояс задаётся ЯВНО, а не timezone=auto: при auto каждая локация
    получает свой пояс, и маршрут через границу поясов даёт точки с разными
    часами в одной таблице.
    """
    lats = ",".join(f"{lat:.4f}" for lat, _ in coords)
    lons = ",".join(f"{lon:.4f}" for _, lon in coords)
    return (f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}"
            f"&wind_speed_unit=ms&timezone={quote(tz)}"
            f"&models={model_id(get_model_key())}"
            f"&hourly={H_1D}&daily={D_1D}&start_date={date}&end_date={date}")
```

Рядом с `_bl_levels` добавить:

```python
def _levels_with_dir(H, i, elev):
    """[(высота MSL, скорость, направление ОТКУДА), ...] по всем уровням с данными."""
    out = []
    for agl, skey, dkey in ((10, "wind_speed_10m", "wind_direction_10m"),
                            (80, "wind_speed_80m", "wind_direction_80m"),
                            (120, "wind_speed_120m", "wind_direction_120m")):
        s, d = _at(H, skey, i), _at(H, dkey, i)
        if s is not None and d is not None:
            out.append((elev + agl, s, d))
    for hpa in (925, 850, 700):
        alt = _at(H, f"geopotential_height_{hpa}hPa", i)
        s = _at(H, f"wind_speed_{hpa}hPa", i)
        d = _at(H, f"wind_direction_{hpa}hPa", i)
        if alt is not None and s is not None and d is not None:
            out.append((alt, s, d))
    return sorted(out)


def mean_wind_vector(H, i, elev, lo_msl, hi_msl):
    """Средний ветер в слое [lo_msl, hi_msl] → (скорость м/с, направление ОТКУДА).

    Осреднение ВЕКТОРНОЕ (u/v): осреднение модулей завышает ветер там, где
    направление разворачивается с высотой, — а это ровно те дни, когда разворот
    и есть главная новость.
    """
    levels = _levels_with_dir(H, i, elev)
    if not levels:
        return None, None
    inside = [lv for lv in levels if lo_msl <= lv[0] <= hi_msl]
    if not inside:  # слой тоньше сетки уровней — берём ближайший к его середине
        mid = (lo_msl + hi_msl) / 2.0
        inside = [min(levels, key=lambda lv: abs(lv[0] - mid))]
    u = sum(_uv(s, d)[0] for _, s, d in inside) / len(inside)
    v = sum(_uv(s, d)[1] for _, s, d in inside) / len(inside)
    return round(math.hypot(u, v), 1), round((math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0, 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_engine_route.py -q`
Expected: PASS, 8 passed

- [ ] **Step 5: Commit**

```bash
git add engine.py tests/test_engine_route.py
git commit -m "feat(engine): мульти-точечный URL и векторный ветер по слою"
```

---

### Task 11: Сборка профиля маршрута

**Files:**
- Modify: `forecast.py`, `tests/fixtures.py`
- Test: `tests/test_route_profile.py`

**Interfaces:**
- Consumes: всё из задач 1–10
- Produces: `forecast.fetch_terrain(coords) -> list[float] | None`; `forecast.get_route(points, name, date, departure_h=None) -> dict`; `fixtures.om_route(n, elevations=None, **overrides) -> list[dict]`; `forecast.ELEVATION_CHUNK = 100`

- [ ] **Step 1: Write the failing test**

Сначала добавить в `tests/fixtures.py`:

```python
def om_route(n, elevations=None, **overrides):
    """Ответ open-meteo на мульти-точечный запрос: список из n однодневных тел.

    `elevations` — высота грид-ячейки каждой локации (open-meteo кладёт её в
    поле `elevation` каждого элемента списка).
    """
    out = []
    for k in range(n):
        body = om_1day(**overrides)
        body["elevation"] = (elevations or [1000.0] * n)[k]
        out.append(body)
    return out
```

```python
# tests/test_route_profile.py
"""Сборка профиля маршрута: два запроса, кэш, форма результата, деградация."""
import datetime as dt

import pytest

import forecast
import route
from fixtures import om_route

PTS = [route.Point(42.0, 44.0, "старт"), route.Point(42.0 + 40.0 / 111.195, 44.0, "финиш")]
# Дата вычисляется, а не задаётся константой: get_route проверяет горизонт прогноза,
# и зафиксированная дата протухла бы через две недели после написания теста.
DATE = dt.date.today().isoformat()

REQUIRED_POINT_FIELDS = {
    "km", "leg_length_km", "role", "lat", "lon", "name", "track_bearing_deg",
    "eta", "eta_fixed", "terrain_m", "terrain_point_m", "is_terrain_peak",
    "cloud_base_m", "working_band_m", "wind_along_kmh", "wind_cross_kmh",
    "wind_working_alt_kmh", "wind_working_alt_dir", "effective_ground_speed_kmh",
    "crab_limited", "window", "time_margin_min", "w_star_ms", "site_match", "weather",
}


@pytest.fixture()
def api(monkeypatch):
    """Подменяет оба сетевых вызова; возвращает счётчики обращений."""
    calls = {"weather": 0, "terrain": 0}

    def _n(url):
        """Сколько локаций запрошено — ответ обязан совпасть по длине."""
        return url.split("latitude=")[1].split("&")[0].count(",") + 1

    async def fake_weather(url):
        calls["weather"] += 1
        return om_route(_n(url))

    async def fake_terrain(coords):
        calls["terrain"] += 1
        return [1000.0] * len(coords)

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)
    return calls


async def test_profile_shape(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5)
    assert p["route"]["total_km"] == pytest.approx(40.0, abs=0.5)
    assert p["route"]["date"] == DATE
    assert p["route"]["sample_step_km"] == pytest.approx(10.0)
    assert p["route"]["avg_route_speed_kmh"] == 25.0
    assert len(p["points"]) == 5
    assert REQUIRED_POINT_FIELDS <= set(p["points"][0])


async def test_roles_and_site_match(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5)
    assert p["points"][0]["role"] == "takeoff"
    assert p["points"][-1]["role"] == "goal"


async def test_second_call_is_served_from_cache(api):
    await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5)
    await forecast.get_route(PTS, "Тест", DATE, departure_h=12.5)
    assert api["weather"] == 1
    assert api["terrain"] == 1


async def test_departure_defaults_to_window_start(api):
    p = await forecast.get_route(PTS, "Тест", DATE)
    assert p["route"]["departure"] is not None
    assert p["points"][0]["eta"] == p["route"]["departure"]


async def test_terrain_failure_degrades_loudly(monkeypatch):
    async def fake_weather(url):
        return om_route(url.split("latitude=")[1].split("&")[0].count(",") + 1)

    async def failing_terrain(coords):
        return None

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", failing_terrain)
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5)
    assert all(pt["working_band_m"] is None for pt in p["points"])
    assert any("рельеф" in n.lower() for n in p["notes"])


async def test_no_thermal_window_at_start_is_reported(monkeypatch):
    async def fake_weather(url):
        n = url.split("latitude=")[1].split("&")[0].count(",") + 1
        return om_route(n, boundary_layer_height=100.0, shortwave_radiation=10.0)

    async def fake_terrain(coords):
        return [1000.0] * len(coords)

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)
    with pytest.raises(forecast.ForecastError) as e:
        await forecast.get_route(PTS, "Тест", DATE)
    assert "время" in str(e.value).lower()


async def test_date_beyond_forecast_horizon_rejected(api):
    far = (dt.date.today() + dt.timedelta(days=40)).isoformat()
    with pytest.raises(forecast.ForecastError) as e:
        await forecast.get_route(PTS, "Тест", far, departure_h=11.5)
    assert "прогноз" in str(e.value).lower()


async def test_past_date_rejected(api):
    past = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    with pytest.raises(forecast.ForecastError):
        await forecast.get_route(PTS, "Тест", past, departure_h=11.5)


async def test_arrival_past_midnight_is_truncated_and_reported(api):
    import settings
    settings.set_speed(10.0)                       # 40 км от 22:00 уходят за полночь
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=22.0)
    assert any("сутк" in n.lower() for n in p["notes"])
    assert p["points"][-1]["eta"] is None
    assert p["points"][0]["eta"] == "22:00"
```

Тест на горизонт даты использует фикстуру `DATE = "2026-07-25"`, которая может
оказаться в прошлом относительно дня прогона. Поэтому в остальных тестах этого
файла дату надо брать как `dt.date.today().isoformat()`, а не константой —
поправь `DATE` на вычисляемое значение при написании файла.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_route_profile.py -q`
Expected: FAIL — `AttributeError: module 'forecast' has no attribute 'get_route'`

- [ ] **Step 3: Write minimal implementation**

В `forecast.py` добавить (`import route`, `import settings` к импортам):

```python
ELEVATION_CHUNK = 100          # документированный потолок Elevation API
_terrain_cache: dict[tuple, list] = {}      # рельеф не меняется — без срока
_TERRAIN_CACHE_MAX = 64
_rcache: dict[tuple, tuple] = {}            # (expires, weather_bodies)


def _route_key(coords):
    return tuple((round(lat, 4), round(lon, 4)) for lat, lon in coords)


async def fetch_terrain(coords):
    """Высоты рельефа по списку координат порциями по 100. None при отказе.

    Copernicus DEM GLO-90, разрешение 90 м. Узкий перевал шириной 500 м может
    быть пропущен, острая вершина рядом с трассой — наоборот, дать ложное
    срабатывание ограничения по высоте.
    """
    out = []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for i in range(0, len(coords), ELEVATION_CHUNK):
                chunk = coords[i:i + ELEVATION_CHUNK]
                lats = ",".join(f"{lat:.4f}" for lat, _ in chunk)
                lons = ",".join(f"{lon:.4f}" for _, lon in chunk)
                r = await client.get("https://api.open-meteo.com/v1/elevation"
                                     f"?latitude={lats}&longitude={lons}")
                r.raise_for_status()
                out.extend(r.json()["elevation"])
    except Exception as e:  # noqa: BLE001 — рельеф best-effort, но молча не деградируем
        log.warning("route: elevation failed: %s", e)
        return None
    return out


async def _fetch_route_weather(url):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    return data if isinstance(data, list) else [data]


async def _ensure_terrain(grid):
    coords = [(lat, lon) for _km, lat, lon in grid]
    key = _route_key(coords)
    if key in _terrain_cache:
        return _terrain_cache[key]
    elev = await fetch_terrain(coords)
    if elev is not None:
        if len(_terrain_cache) >= _TERRAIN_CACHE_MAX:
            _terrain_cache.pop(next(iter(_terrain_cache)))
        _terrain_cache[key] = elev
    return elev


async def _ensure_route_weather(samples, date):
    coords = [(s.lat, s.lon) for s in samples]
    key = (_route_key(coords), date, engine.get_model_key())
    now = time.monotonic()
    _purge(now)
    if key in _rcache:
        return _rcache[key][1]
    tz = os.environ.get("TZ") or "Asia/Tbilisi"
    url = engine.route_weather_url(coords, date, tz)
    try:
        bodies = await _fetch_route_weather(url)
    except httpx.HTTPError as e:
        raise ForecastError(f"Не удалось получить прогноз от open-meteo: {e}")
    if len(bodies) != len(samples):
        raise ForecastError("open-meteo вернул другое число точек, чем запрошено")
    _rcache[key] = (now + _TTL, bodies)
    return bodies


def _hourly_facts(H, hour):
    """Срез почасовых переменных на дробный час прибытия."""
    out = {}
    for key in H:
        if key == "time":
            continue
        if key.startswith("precipitation"):
            out[key] = route.worst_of_hours(H[key], hour)
        else:
            out[key] = route.interp(H[key], hour)
    return out


ROUTE_HORIZON_DAYS = 15        # open-meteo отдаёт прогноз примерно на 16 суток вперёд


def _check_date(date):
    today = dt.date.today()
    last = today + dt.timedelta(days=ROUTE_HORIZON_DAYS)
    try:
        want = dt.date.fromisoformat(date)
    except ValueError:
        raise ForecastError(f"Не понимаю дату: {date}") from None
    if not today <= want <= last:
        raise ForecastError(
            f"Прогноз доступен с {today.isoformat()} по {last.isoformat()}, "
            f"а запрошено {date}")


async def get_route(points, name, date, departure_h=None):
    """Профиль маршрута: два запроса, кэш, все маршрутные величины. Без скоринга."""
    _check_date(date)
    cfg = settings.get()
    speed = cfg["avg_route_speed_kmh"]
    samples, step = route.resample(points)
    total_km = samples[-1].km
    notes = []
    if step > route.SAMPLE_STEP_KM + 0.01:
        notes.append(f"Маршрут длинный: шаг увеличен до {step:.0f} км")

    grid = route.terrain_grid(points, total_km)
    elev = await _ensure_terrain(grid)
    if elev is None:
        notes.append("Рельеф недоступен — рабочий диапазон не посчитан")
    route.attach_terrain(samples, grid, elev, step_km=step)

    bodies = await _ensure_route_weather(samples, date)
    sites = {s["name"]: s for s in engine.load_sites()}

    # окно термической активности в каждой точке — нужно до расчёта времени,
    # потому что вылет по умолчанию берётся из окна первой точки
    for s, body in zip(samples, bodies):
        H, D = body["hourly"], body["daily"]
        s.window = route.thermal_window(date, s.lat, D["sunrise"][0], D["sunset"][0],
                                        H.get("boundary_layer_height"),
                                        H.get("shortwave_radiation"))
    if departure_h is None:
        if not samples[0].window:
            raise ForecastError(
                "В первой точке термическое окно не открывается — задай время вылета "
                "вручную: /route <дата> ЧЧ:ММ")
        departure_h = float(samples[0].window["open_hour"])

    def wind_for_segment(i, hour):
        a = _wind_along_cross(samples[i], bodies[i], hour)
        b = _wind_along_cross(samples[i + 1], bodies[i + 1], hour)
        pairs = [v for v in (a, b) if v[0] is not None]
        if not pairs:
            return 0.0, 0.0
        return (sum(p[0] for p in pairs) / len(pairs),
                sum(p[1] for p in pairs) / len(pairs))

    route.fixed_eta(samples, speed, departure_h)
    if cfg["wind_correction_enabled"]:
        route.march(samples, speed, wind_for_segment, departure_h)
    else:
        for s in samples:
            s.eta_h, s.gs_kmh = s.eta_fixed_h, speed

    # Данные запрошены на ОДИН день. Если прилёт уходит за полночь, дальше считать
    # нечем, и молчать об этом нельзя: пустая строка в таблице читалась бы как
    # «погода там неизвестна», а не как «расчёт оборвался».
    over = [s for s in samples if s.eta_h is not None and s.eta_h >= 24.0]
    if over:
        notes.append(f"С {over[0].km:.0f} км прилёт выходит за сутки — "
                     "дальше не считаю, данные запрошены на один день")
        for s in over:
            s.eta_h = None

    for s, body in zip(samples, bodies):
        if s.eta_h is None:
            continue
        H = body["hourly"]
        elev_m = s.terrain_m if s.terrain_m is not None else body.get("elevation", 0.0)
        s.weather = _hourly_facts(H, s.eta_h)
        s.cloud_base_m = route.cloud_base_m(s.terrain_m, s.weather.get("temperature_2m"),
                                            s.weather.get("dew_point_2m"))
        s.working_band_m = route.working_band_m(s.cloud_base_m, s.terrain_m)
        top = s.cloud_base_m if s.cloud_base_m is not None else (
            elev_m + (s.weather.get("boundary_layer_height") or 1500.0))
        ms, deg = engine.mean_wind_vector(H, int(s.eta_h), elev_m, elev_m + 500.0, top)
        s.wind_kmh, s.wind_dir_deg = route.ms_to_kmh(ms), deg
        s.wind_along_kmh, s.wind_cross_kmh = route.wind_components(
            s.wind_kmh, s.wind_dir_deg, s.track_bearing_deg)
        s.time_margin_min = route.time_margin_min(s.window, s.eta_h)
        s.w_star_ms = engine.w_star(s.weather.get("boundary_layer_height"),
                                    s.weather.get("shortwave_radiation"),
                                    s.weather.get("temperature_2m"), elev_m)
        s.site_match = _nearest_site(s, sites)

    return {
        "route": {
            "name": name, "date": date, "departure": _hhmm(departure_h),
            "timezone": os.environ.get("TZ") or "Asia/Tbilisi",
            "total_km": round(total_km, 1),
            "avg_route_speed_kmh": speed,
            "wind_correction_enabled": cfg["wind_correction_enabled"],
            "sample_step_km": round(step, 1), "sample_count": len(samples),
            "model": engine.model_label(engine.get_model_key()),
        },
        "points": [_point_dict(s) for s in samples],
        "notes": notes,
    }


def _wind_along_cross(sample, body, hour):
    H = body["hourly"]
    elev_m = sample.terrain_m if sample.terrain_m is not None else body.get("elevation", 0.0)
    top = elev_m + (route.interp(H.get("boundary_layer_height"), hour) or 1500.0)
    ms, deg = engine.mean_wind_vector(H, int(hour), elev_m, elev_m + 500.0, top)
    return route.wind_components(route.ms_to_kmh(ms), deg, sample.track_bearing_deg)


def _nearest_site(sample, sites):
    for name, site in sites.items():
        d, _ = route.haversine(route.Point(sample.lat, sample.lon),
                               route.Point(site["lat"], site["lon"]))
        if d / 1000.0 <= route.SITE_MATCH_KM:
            return name
    return None


def _hhmm(hour):
    if hour is None:
        return None
    h, m = divmod(int(round(hour * 60)), 60)
    return f"{h % 24:02d}:{m:02d}"


def _point_dict(s):
    return {
        "km": round(s.km, 1), "leg_length_km": round(s.leg_length_km, 1), "role": s.role,
        "lat": s.lat, "lon": s.lon, "name": s.name,
        "track_bearing_deg": round(s.track_bearing_deg),
        "eta": _hhmm(s.eta_h), "eta_fixed": _hhmm(s.eta_fixed_h),
        "terrain_m": None if s.terrain_m is None else round(s.terrain_m),
        "terrain_point_m": None if s.terrain_point_m is None else round(s.terrain_point_m),
        "is_terrain_peak": s.is_terrain_peak,
        "cloud_base_m": None if s.cloud_base_m is None else round(s.cloud_base_m),
        "working_band_m": None if s.working_band_m is None else round(s.working_band_m),
        "wind_along_kmh": None if s.wind_along_kmh is None else round(s.wind_along_kmh, 1),
        "wind_cross_kmh": None if s.wind_cross_kmh is None else round(s.wind_cross_kmh, 1),
        "wind_working_alt_kmh": None if s.wind_kmh is None else round(s.wind_kmh, 1),
        "wind_working_alt_dir": s.wind_dir_deg,
        "effective_ground_speed_kmh": None if s.gs_kmh is None else round(s.gs_kmh, 1),
        "crab_limited": s.crab_limited,
        "window": s.window,
        "time_margin_min": None if s.time_margin_min is None else round(s.time_margin_min),
        "w_star_ms": s.w_star_ms, "site_match": s.site_match, "weather": s.weather,
    }
```

Ещё три правки, без которых задача не сходится:

1. Добавить `SITE_MATCH_KM = 2.0` к константам `route.py` — радиус сопоставления точки с сохранённым стартом.
2. В `forecast._purge` добавить `_rcache` к перебираемым кэшам: сейчас там только `(_fcache, _acache)`, и маршрутный кэш рос бы без ограничения.
3. В фикстуре `fresh_state` (`tests/conftest.py`) очищать `forecast._terrain_cache` и `forecast._rcache` рядом с существующим `forecast._fcache.clear()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_route_profile.py -q && .venv/bin/python -m pytest -q`
Expected: PASS, 6 passed в файле; весь набор зелёный

- [ ] **Step 5: Commit**

```bash
git add forecast.py route.py tests/fixtures.py tests/conftest.py tests/test_route_profile.py
git commit -m "feat(forecast): сборка профиля маршрута из рельефа и погоды"
```

---

### Task 12: Карточка маршрута

**Files:**
- Modify: `route.py`
- Test: `tests/test_route_card.py`

**Interfaces:**
- Consumes: профиль из задачи 11
- Produces: `route.render_card(profile) -> str`; константа `CARD_WIDTH = 32`

Функция называется `render_card`, а не `card`: в `engine` уже есть `card(deg)` —
румб по градусам, и два разных `card` в одном конвейере читались бы как одно.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_route_card.py
"""Карточка маршрута: только погода и время, ширина под мобильный экран."""
import pytest

import route


def profile(**over):
    pts = []
    for i, km in enumerate([0, 20, 40]):
        pts.append({
            "km": km, "eta": f"1{i + 1}:00", "eta_fixed": f"1{i + 1}:00",
            "role": "takeoff" if i == 0 else ("goal" if i == 2 else "enroute"),
            "wind_along_kmh": [10.0, 0.0, -14.0][i],
            "wind_working_alt_kmh": [10.0, 14.0, 20.0][i],
            "wind_working_alt_dir": [330.0, 240.0, 180.0][i],
            "w_star_ms": [1.8, 2.7, 0.9][i],
            "working_band_m": [1430, 720, 380][i],
            "terrain_m": 2000, "is_terrain_peak": False,
            "time_margin_min": [330, 150, -25][i],
            "weather": {"precipitation": 0.0, "cape": 100.0, "lifted_index": 2.0},
        })
    p = {"route": {"name": "Гудаури → Пасанаури", "date": "2026-07-28",
                   "departure": "11:00", "total_km": 40.0, "sample_step_km": 20.0,
                   "sample_count": 3, "model": "Auto (best_match)",
                   "avg_route_speed_kmh": 25.0, "wind_correction_enabled": True},
         "points": pts, "notes": []}
    p.update(over)
    return p


def test_every_line_fits_the_mobile_width():
    text = route.render_card(profile())
    assert max(len(ln) for ln in text.splitlines()) <= route.CARD_WIDTH


def test_table_has_a_row_per_point():
    text = route.render_card(profile())
    assert " 0 " in text and " 20 " in text and " 40 " in text


def test_tailwind_and_headwind_arrows_differ():
    text = route.render_card(profile())
    assert "→" in text and "←" in text


def test_heights_are_not_shown():
    """Прямое требование: рабочий диапазон считается, но в карточку не идёт."""
    text = route.render_card(profile())
    for forbidden in ("1430", "720", "380", "2000"):
        assert forbidden not in text


def test_time_margin_is_a_single_line_with_both_ends():
    text = route.render_card(profile())
    assert "+330" in text
    assert "−25" in text


def test_missing_wind_direction_does_not_crash():
    p = profile()
    p["points"][1]["wind_working_alt_dir"] = None
    assert "н/д" in route.render_card(p)


def test_point_beyond_midnight_renders_without_crashing():
    p = profile()
    p["points"][-1]["eta"] = None
    text = route.render_card(p)
    assert "сутк" in text.lower()


def test_fixed_eta_warning_only_when_divergence_is_large():
    p = profile()
    p["points"][-1]["eta"], p["points"][-1]["eta_fixed"] = "16:36", "14:37"
    assert "14:37" in route.render_card(p)
    p["points"][-1]["eta"], p["points"][-1]["eta_fixed"] = "14:40", "14:37"
    assert "14:37" not in route.render_card(p)


def test_precipitation_line_names_the_kilometre():
    p = profile()
    p["points"][1]["weather"]["precipitation"] = 0.4
    text = route.render_card(p)
    assert "20" in text and "0,4" in text


def test_storm_line_names_the_kilometre():
    p = profile()
    p["points"][1]["weather"].update({"cape": 1150.0, "lifted_index": -3.6})
    assert "CAPE" in route.render_card(p)


def test_notes_are_shown():
    assert "рельеф" in route.render_card(profile(notes=["Рельеф недоступен"])).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_route_card.py -q`
Expected: FAIL — `AttributeError: module 'route' has no attribute 'card'`

- [ ] **Step 3: Write minimal implementation**

```python
CARD_WIDTH = 32                # шире Telegram переносит моноширинный блок на телефоне
CAPE_WATCH = 800.0             # с этого значения гроза стоит отдельной строки
LI_WATCH = -2.0


def _signed(v):
    """Число со знаком минус-тире, без выравнивания: «+330», «−25»."""
    return "н/д" if v is None else f"{'−' if v < 0 else '+'}{abs(v):.0f}"


def _rows(points):
    """Колонки: километр, время, МОДУЛЬ составляющей вдоль курса (знак несёт
    стрелка), абсолютный ветер на рабочей высоте, оценка силы потоков."""
    out = [" км  время  вдоль  ветер  поток"]
    for p in points:
        along = p.get("wind_along_kmh")
        arrow = " " if along is None else ("→" if along >= 0 else "←")
        along_txt = " н/д" if along is None else f"{abs(along):3.0f}"
        deg, spd = p.get("wind_working_alt_dir"), p.get("wind_working_alt_kmh")
        wind = "   н/д" if deg is None or spd is None else f"{engine.card(deg):>3} {spd:2.0f}"
        w = "  —" if p.get("w_star_ms") is None else f"{p['w_star_ms']:3.1f}"
        eta = p["eta"] or "  —  "      # None = расчёт оборвался на границе суток
        out.append(f"{p['km']:3.0f}  {eta}  {arrow}{along_txt}  {wind}  {w}")
    return out


def render_card(profile):
    """Текстовая карточка маршрута. Только погода и время — высот здесь нет."""
    r, pts = profile["route"], profile["points"]
    arrival = pts[-1]["eta"] if pts and pts[-1]["eta"] else "за пределами суток"
    head = [f"🗺 {r['name']}",
            f"{r['total_km']:.0f} км · {len(pts)} точек · {engine.fmt_date(r['date'])}",
            "",
            f"⏱ Вылет {r['departure']} → прилёт ~{arrival}",
            ""]
    body = _rows(pts)
    tail = [""]

    margins = [p.get("time_margin_min") for p in pts if p.get("time_margin_min") is not None]
    if margins:
        tail.append("⏳ Запас до закрытия окна:")
        tail.append(f"   {_signed(margins[0])} мин на старте, "
                    f"{_signed(margins[-1])} на финише")

    wet = [p for p in pts if (p["weather"].get("precipitation") or 0) > 0]
    if wet:
        mm = max(p["weather"]["precipitation"] for p in wet)
        tail.append(f"🌧 {wet[0]['km']:.0f}–{wet[-1]['km']:.0f} км: осадки "
                    f"{mm:.1f} мм".replace(".", ","))

    storm = [p for p in pts
             if (p["weather"].get("cape") or 0) >= CAPE_WATCH
             or (p["weather"].get("lifted_index") is not None
                 and p["weather"]["lifted_index"] <= LI_WATCH)]
    if storm:
        p = storm[0]
        tail.append(f"⚡ {p['km']:.0f} км: CAPE {p['weather']['cape']:.0f}, "
                    f"LI {p['weather']['lifted_index']:.1f}".replace(".", ","))

    if _eta_gap_min(pts) > ETA_WARN_MIN:
        tail.append("⚠️ Без учёта ветра прилёт был бы")
        tail.append(f"   в {pts[-1]['eta_fixed']} — раньше на "
                    f"{_eta_gap_min(pts):.0f} мин")

    tail.extend(profile.get("notes") or [])
    tail.append(f"📊 {r['sample_count']} точек, шаг {r['sample_step_km']:.0f} км, "
                f"модель {r['model'].split(' ')[0]}")
    return "\n".join(head + body + tail)


def _eta_gap_min(points):
    """Расхождение времён прилёта в минутах; 0, если сравнивать не с чем."""
    last = points[-1] if points else {}
    if not last.get("eta") or not last.get("eta_fixed"):
        return 0

    def mins(hhmm):
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    return abs(mins(last["eta"]) - mins(last["eta_fixed"]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_route_card.py -q`
Expected: PASS, 9 passed

Если строка вылезает за `CARD_WIDTH`, подрезай **заголовок таблицы и отступы**, а не колонку «поток»: без силы потоков таблица перестаёт отвечать на вопрос «а набирать-то там есть на чём».

- [ ] **Step 5: Commit**

```bash
git add route.py tests/test_route_card.py
git commit -m "feat(route): карточка маршрута"
```

---

### Task 13: Команда /settings

**Files:**
- Modify: `bot.py`
- Test: `tests/test_settings_dialog.py`

**Interfaces:**
- Consumes: `settings.get/set_speed/set_wind_correction`
- Produces: хендлеры `cmd_settings`, `cb_set_speed` (`data="sp|<v>"`), `cb_toggle_wind` (`data="sw|<0|1>"`), состояние `SettingsSpeed.value`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings_dialog.py
"""Команда /settings: показ, кнопки, ввод своего значения, валидация."""
import settings
from tg import callback_update, text_update, texts


async def test_settings_shows_current_values(feed, session):
    await feed(text_update("/settings"))
    assert "25" in texts(session)[-1]
    assert "км/ч" in texts(session)[-1]


async def test_button_sets_speed(feed, session):
    await feed(text_update("/settings"))
    await feed(callback_update("sp|30"))
    assert settings.get()["avg_route_speed_kmh"] == 30.0


async def test_toggle_switches_wind_correction(feed, session):
    await feed(callback_update("sw|0"))
    assert settings.get()["wind_correction_enabled"] is False
    await feed(callback_update("sw|1"))
    assert settings.get()["wind_correction_enabled"] is True


async def test_custom_value_via_dialog(feed, session):
    await feed(text_update("/settings"))
    await feed(callback_update("sp|custom"))
    await feed(text_update("28"))
    assert settings.get()["avg_route_speed_kmh"] == 28.0


async def test_custom_value_out_of_range_explains_itself(feed, session):
    await feed(text_update("/settings"))
    await feed(callback_update("sp|custom"))
    await feed(text_update("99"))
    assert settings.get()["avg_route_speed_kmh"] == 25.0
    assert "скорость крыла" in texts(session)[-1]


async def test_custom_value_not_a_number(feed, session):
    await feed(text_update("/settings"))
    await feed(callback_update("sp|custom"))
    await feed(text_update("быстро"))
    assert settings.get()["avg_route_speed_kmh"] == 25.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings_dialog.py -q`
Expected: FAIL — бот отвечает обработчиком `unhandled`, значения настроек не меняются

- [ ] **Step 3: Write minimal implementation**

В `bot.py` (`import settings` к импортам, `SettingsSpeed` рядом с другими `StatesGroup`):

```python
class SettingsSpeed(StatesGroup):
    value = State()


def _settings_text() -> str:
    cfg = settings.get()
    wind = "включён" if cfg["wind_correction_enabled"] else "выключен"
    return ("⚙️ Настройки\n\n"
            f"Средняя маршрутная скорость: {cfg['avg_route_speed_kmh']:.0f} км/ч\n"
            f"Учёт ветра во времени прилёта: {wind}")


def _settings_keyboard() -> InlineKeyboardMarkup:
    cfg = settings.get()
    speeds = [InlineKeyboardButton(text=f"{v}", callback_data=f"sp|{v}") for v in (20, 25, 30)]
    speeds.append(InlineKeyboardButton(text="Ввести свою", callback_data="sp|custom"))
    toggle = InlineKeyboardButton(
        text="Выключить учёт ветра" if cfg["wind_correction_enabled"] else "Включить учёт ветра",
        callback_data=f"sw|{0 if cfg['wind_correction_enabled'] else 1}")
    return InlineKeyboardMarkup(inline_keyboard=[speeds, [toggle]])


@dp.message(Command("settings"))
async def cmd_settings(message: Message):
    await message.answer(_settings_text(), reply_markup=_settings_keyboard())


@dp.callback_query(F.data.startswith("sp|"))
async def cb_set_speed(cb: CallbackQuery, state: FSMContext):
    value = cb.data.split("|", 1)[1]
    if value == "custom":
        await state.set_state(SettingsSpeed.value)
        await cb.message.answer("Введи среднюю маршрутную скорость в км/ч "
                                f"({settings.SPEED_MIN:.0f}–{settings.SPEED_MAX:.0f}):")
        return await cb.answer()
    settings.set_speed(float(value))
    await cb.message.answer(_settings_text(), reply_markup=_settings_keyboard())
    await cb.answer()


@dp.callback_query(F.data.startswith("sw|"))
async def cb_toggle_wind(cb: CallbackQuery):
    settings.set_wind_correction(cb.data.split("|", 1)[1] == "1")
    await cb.message.answer(_settings_text(), reply_markup=_settings_keyboard())
    await cb.answer()


@dp.message(SettingsSpeed.value)
async def settings_speed_value(message: Message, state: FSMContext):
    try:
        settings.set_speed(float((message.text or "").replace(",", ".").strip()))
    except ValueError as e:
        detail = str(e) if str(e).startswith("средняя") else (
            "Нужно число, например 25. Это средняя по маршруту с учётом наборов "
            "в термиках, а не скорость крыла.")
        return await message.answer(detail)
    await state.clear()
    await message.answer(_settings_text(), reply_markup=_settings_keyboard())
```

Добавить в `BOT_COMMANDS`: `BotCommand(command="settings", description="Настройки маршрута")`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_settings_dialog.py -q`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_settings_dialog.py
git commit -m "feat(bot): команда /settings со средней маршрутной скоростью"
```

---

### Task 14: Команда /route и документация

**Files:**
- Modify: `bot.py`, `README.md`
- Test: `tests/test_route_dialog.py`

**Interfaces:**
- Consumes: `route.parse_text`, `route.parse_gpx`, `route.card`, `forecast.get_route`
- Produces: хендлеры `cmd_route`, `route_gpx_document`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_route_dialog.py
"""Команда /route: текстовый ввод, GPX-документ, разбор даты и времени, ошибки."""
import pytest

import datetime as dt

import forecast
from tg import text_update, texts


@pytest.fixture()
def route_calls(monkeypatch):
    calls = []

    async def fake(points, name, date, departure_h=None):
        calls.append((len(points), name, date, departure_h))
        return {"route": {"name": name or "Маршрут", "date": date, "departure": "11:00",
                          "total_km": 40.0, "sample_step_km": 10.0, "sample_count": 5,
                          "model": "Auto", "avg_route_speed_kmh": 25.0,
                          "wind_correction_enabled": True},
                "points": [], "notes": []}

    monkeypatch.setattr(forecast, "get_route", fake)
    monkeypatch.setattr("route.render_card", lambda p: "КАРТОЧКА МАРШРУТА")
    return calls


async def test_text_route_is_parsed_and_sent(feed, session, route_calls):
    await feed(text_update("/route\n42.4776, 44.4787\n42.2104, 44.6890"))
    assert route_calls[0][0] == 2
    assert "КАРТОЧКА МАРШРУТА" in texts(session)[-1]


async def test_tomorrow_keyword(feed, route_calls):
    await feed(text_update("/route завтра\n42.4776, 44.4787\n42.2104, 44.6890"))
    assert route_calls[0][2] == (dt.date.today() + dt.timedelta(days=1)).isoformat()


async def test_explicit_date_and_time(feed, route_calls):
    await feed(text_update("/route 2026-07-28 11:30\n42.4776, 44.4787\n42.2104, 44.6890"))
    assert route_calls[0][2] == "2026-07-28"
    assert route_calls[0][3] == pytest.approx(11.5)


async def test_bad_line_is_reported_with_its_number(feed, session, route_calls):
    await feed(text_update("/route\n42.4776, 44.4787\nсюда попал текст"))
    assert not route_calls
    assert "строка 3" in texts(session)[-1]


async def test_route_without_points_explains_the_format(feed, session, route_calls):
    await feed(text_update("/route"))
    assert not route_calls
    assert "42." in texts(session)[-1]     # в подсказке есть пример
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_route_dialog.py -q`
Expected: FAIL — обработчик `/route` не зарегистрирован

- [ ] **Step 3: Write minimal implementation**

В `bot.py` (`import route` к импортам):

```python
ROUTE_HELP = ("Пришли маршрут списком координат — по точке на строку:\n\n"
              "/route завтра 11:30\n"
              "42.4776, 44.4787, старт\n"
              "42.2104, 44.6890, финиш\n\n"
              "Дата и время вылета необязательны: без времени берётся начало "
              "термического окна в первой точке. GPX-файл тоже подойдёт.")


def _parse_when(args: str) -> tuple[str, float | None, str]:
    """«завтра 11:30» → (дата, час вылета, остаток строки)."""
    date, departure, rest = dt.date.today().isoformat(), None, []
    for token in (args or "").split():
        low = token.lower()
        if low == "сегодня":
            date = dt.date.today().isoformat()
        elif low == "завтра":
            date = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", token):
            date = token
        elif re.fullmatch(r"\d{1,2}:\d{2}", token):
            h, m = token.split(":")
            departure = int(h) + int(m) / 60.0
        else:
            rest.append(token)
    return date, departure, " ".join(rest)


async def _send_route(message: Message, points, name, date, departure):
    try:
        profile = await forecast.get_route(points, name, date, departure)
    except forecast.ForecastError as e:
        return await message.answer(str(e))
    for chunk in _chunks(route.card(profile)):
        await message.answer(chunk)


@dp.message(Command("route"), flags={"forecast": True})
async def cmd_route(message: Message, command: CommandObject):
    body = "\n".join((message.text or "").splitlines()[1:])
    if not body.strip():
        return await message.answer(ROUTE_HELP)
    date, departure, _rest = _parse_when(command.args or "")
    try:
        points = route.parse_text(body, first_line_no=2)  # первая строка — сама команда
    except route.RouteError as e:
        return await message.answer(f"❌ {e}")
    await _send_route(message, points, None, date, departure)


@dp.message(F.document, flags={"forecast": True})
async def route_gpx_document(message: Message):
    doc = message.document
    if not (doc.file_name or "").lower().endswith(".gpx"):
        return await message.answer("Я понимаю только GPX-файлы маршрутов.")
    if (doc.file_size or 0) > route.MAX_GPX_BYTES:
        return await message.answer(
            f"❌ файл больше {route.MAX_GPX_BYTES // 1024} КБ — пришли маршрут покороче")
    buf = io.BytesIO()
    await message.bot.download(doc, destination=buf)
    try:
        points, name = route.parse_gpx(buf.getvalue())
    except route.RouteError as e:
        return await message.answer(f"❌ {e}")
    date, departure, _rest = _parse_when(message.caption or "")
    await _send_route(message, points, name, date, departure)
```

Добавить `import io` и `BotCommand(command="route", description="Погода по маршруту")` в `BOT_COMMANDS`, а также строки про `/route` и `/settings` в `HELP`.

Хендлер документа регистрируется **до** `unhandled`, иначе тот перехватит сообщение.

В `README.md`: строки `/route` и `/settings` в таблицу команд и абзац про маршрутную сводку — форматы ввода, что считается, и оговорка, что балл и вердикт появятся следующей частью.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_route_dialog.py -q && .venv/bin/python -m pytest -q`
Expected: PASS, 5 passed в файле; весь набор зелёный, регрессий нет

- [ ] **Step 5: Commit**

```bash
git add bot.py README.md tests/test_route_dialog.py
git commit -m "feat(bot): команда /route для маршрутной сводки погоды"
```

---

## Проверка перед сдачей

- [ ] `.venv/bin/python -m pytest -q` — весь набор зелёный, число тестов выросло примерно на 100
- [ ] `grep -rn "122" route.py` — числа 122 в модуле нет, коэффициент берётся из `criteria.LCL_M_PER_C`
- [ ] `grep -rn "score\|категор\|вето" route.py settings.py` — пусто: скоринга в этой спеке нет
- [ ] В `route.py` присутствуют комментарии-оговорки: сетка 9–11 км не разрешает долинные ветры; конвергенции невидимы; маршрут считается по прямой, реальный путь на 10–25 % длиннее; средняя скорость сама зависит от условий; DEM 90 м может пропустить узкий перевал; формула базы неприменима при слоистой облачности; марш вперёд занижает время при усилении ветра внутри сегмента

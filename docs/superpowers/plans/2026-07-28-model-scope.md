# Область действия выбора метеомодели — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Потолок термиков всегда считается по GFS, а кнопка модели под прогнозом выбирает модель разово, не меняя глобальную настройку.

**Architecture:** Потолок — узкий побочный запрос к open-meteo за одной серией `boundary_layer_height` с `models=gfs_seamless`, запускается конкурентно с основным и подставляется в ответ по индексу. Разовая модель — необязательный параметр `model`, проходящий от обработчика кнопки до ключа кэша и URL, плюс однобуквенный код в `callback_data` кнопок пересчитанного сообщения.

**Tech Stack:** Python 3.10+, aiogram 3, httpx, pytest (`pytest-asyncio` в `asyncio_mode=auto`), open-meteo.

Спека: [`docs/superpowers/specs/2026-07-28-model-scope-design.md`](../specs/2026-07-28-model-scope-design.md).

## Global Constraints

- Модель, из которой всегда берётся потолок: `gfs` (`gfs_seamless`). Переменная — ровно одна: `boundary_layer_height`. Остальные пробелы ECMWF и ICON не заполняются.
- Побочный запрос за потолком не имеет права уронить прогноз: любая неудача → `log.warning` и работа на серии выбранной модели.
- Подстановка только при полном совпадении массивов `time`. На маршруте — либо все точки, либо ни одной.
- Глобальную модель меняют только `/model` и его кнопки `md|`. Кнопка `mf|` не пишет `model.json` никогда.
- Лимит `callback_data` — 64 байта. Код модели дописывается **только** при наличии разового выбора, чтобы обычный путь остался байт-в-байт как сейчас.
- Комментарии и текст для пользователя — на русском, как во всём проекте. Комментарий объясняет «почему», а не «что».
- Базовая линия: 714 тестов зелёные. Запуск — `.venv/bin/python -m pytest -q`.

## Структура файлов

| Файл | Ответственность в этой задаче |
|---|---|
| `engine.py` | реестр кодов моделей, URL побочного запроса за потолком, `model` в `build_url` / `route_weather_url`, подпись модели на данных |
| `forecast.py` | побочный запрос и подстановка серии, проброс `model` до ключа кэша |
| `bot.py` | разовый выбор в `mf|`, код модели в `callback_data` соседних кнопок |
| `tests/test_engine_model.py` | коды моделей, URL с моделью и URL потолка |
| `tests/test_engine_degrade.py` | подпись модели на данных |
| `tests/test_ceiling_model.py` | **новый** — подстановка серии и её отказы |
| `tests/test_dialogs.py` | разовый выбор в диалоге, коды в кнопках |
| `tests/conftest.py` | фикстуры `fc_calls` / `an_calls` принимают `model` |
| `README.md` | описание обеих новых оговорок |

---

### Task 1: engine — коды моделей и URL побочного запроса за потолком

**Files:**
- Modify: `engine.py:36-49` (блок реестра моделей), `engine.py:196-218` (после `route_weather_url`)
- Test: `tests/test_engine_model.py`

**Interfaces:**
- Consumes: существующие `MODELS`, `model_id`, `model_label`, `RANGE_DAYS`, `quote`
- Produces: `MODEL_CODES: dict[str, str]`, `model_code(key) -> str`, `model_for_code(code) -> str | None`, `CEILING_MODEL_KEY = "gfs"`, `CEILING_VAR = "boundary_layer_height"`, `ceiling_url(site, rng, date=None) -> str`, `route_ceiling_url(coords, date, tz) -> str`

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_engine_model.py`:

```python
# ---------------------------------------------------------------- коды моделей


def test_model_codes_cover_every_model_and_are_unique():
    """Код едет в callback_data, где каждый байт на счету. Таблица явная, а не
    «первая буква ключа»: пятая модель с конфликтующей буквой должна падать
    здесь, а не молча переключать пользователя на чужую модель."""
    assert set(engine.MODEL_CODES) == set(engine.MODELS)
    codes = list(engine.MODEL_CODES.values())
    assert len(set(codes)) == len(codes)
    assert all(len(c) == 1 and c.isascii() for c in codes)


def test_model_code_roundtrip():
    for key in engine.MODELS:
        assert engine.model_for_code(engine.model_code(key)) == key


def test_model_for_unknown_code_is_none():
    """Устаревшая кнопка с кодом исчезнувшей модели → «разового выбора нет»."""
    assert engine.model_for_code("z") is None
    assert engine.model_for_code("") is None


# ---------------------------------------------------------------- URL потолка


def test_ceiling_url_always_gfs_and_one_variable():
    _clear()
    engine.set_model_key("ecmwf")
    url = engine.ceiling_url(_site(), "1d", "2026-07-29")
    assert "models=gfs_seamless" in url          # не выбранная модель
    assert "hourly=boundary_layer_height" in url  # ровно одна серия
    assert "daily=" not in url
    assert "start_date=2026-07-29&end_date=2026-07-29" in url


def test_ceiling_url_overview_uses_forecast_days():
    _clear()
    url = engine.ceiling_url(_site(), "week")
    assert "forecast_days=7" in url and "models=gfs_seamless" in url


def test_route_ceiling_url_keeps_explicit_timezone():
    """Явный пояс, как и в route_weather_url: под timezone=auto точки по разные
    стороны границы поясов получили бы разные часы в одной таблице."""
    url = engine.route_ceiling_url([(42.0, 44.0), (42.5, 44.5)], "2026-07-29", "Asia/Tbilisi")
    assert "timezone=Asia%2FTbilisi" in url
    assert "models=gfs_seamless" in url
    assert "hourly=boundary_layer_height" in url
    assert "latitude=42.0000,42.5000" in url
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_engine_model.py -q`
Expected: FAIL — `AttributeError: module 'engine' has no attribute 'MODEL_CODES'`

- [ ] **Step 3: Реализовать**

В `engine.py` после `DEFAULT_MODEL_KEY = "auto"` (строка 49) добавить:

```python
# Однобуквенный код модели для callback_data: разовый выбор едет с кнопкой, а
# лимит там 64 байта. Таблица явная, а не «первая буква ключа», — иначе новая
# модель с занятой буквой молча увела бы пользователя на чужую.
MODEL_CODES = {"auto": "a", "ecmwf": "e", "gfs": "g", "icon": "i"}
_CODE_TO_MODEL = {v: k for k, v in MODEL_CODES.items()}

# Потолок термиков всегда считается по одной модели, независимо от выбранной.
# Причин две: у ECMWF и ICON серии пограничного слоя нет вовсе, а под best_match
# её отдаёт неизвестно какая подложка — число несравнимо между стартами и днями.
CEILING_MODEL_KEY = "gfs"
CEILING_VAR = "boundary_layer_height"


def model_code(key):
    return MODEL_CODES[key]


def model_for_code(code):
    """Ключ модели по коду; None для неизвестного — устаревшая кнопка из старого
    сообщения не должна ронять обработчик."""
    return _CODE_TO_MODEL.get(code)
```

После `route_weather_url` (строка 218) добавить:

```python
def ceiling_url(site, rng, date=None):
    """Узкий побочный запрос за одной серией — глубиной пограничного слоя из GFS.

    Ходит отдельно от основного, потому что open-meteo не умеет брать разные
    переменные из разных моделей в одном запросе: `models=a,b` размножает ВСЕ
    переменные с суффиксом модели.
    """
    base = (f"https://api.open-meteo.com/v1/forecast?latitude={site['lat']}&longitude={site['lon']}"
            f"&wind_speed_unit=ms&timezone=auto&models={model_id(CEILING_MODEL_KEY)}"
            f"&hourly={CEILING_VAR}")
    if rng == "1d":
        if not date:
            raise SystemExit("для --range 1d нужен --date YYYY-MM-DD")
        return f"{base}&start_date={date}&end_date={date}"
    return f"{base}&forecast_days={RANGE_DAYS[rng]}"


def route_ceiling_url(coords, date, tz):
    """Мульти-точечный аналог ceiling_url. Пояс явный — по той же причине,
    что и в route_weather_url."""
    lats = ",".join(f"{lat:.4f}" for lat, _ in coords)
    lons = ",".join(f"{lon:.4f}" for _, lon in coords)
    return (f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}"
            f"&wind_speed_unit=ms&timezone={quote(tz)}"
            f"&models={model_id(CEILING_MODEL_KEY)}"
            f"&hourly={CEILING_VAR}&start_date={date}&end_date={date}")
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/bin/python -m pytest tests/test_engine_model.py -q`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add engine.py tests/test_engine_model.py
git commit -m "feat(engine): коды моделей и URL побочного запроса за потолком"
```

---

### Task 2: engine — `build_url` и `route_weather_url` принимают модель

**Files:**
- Modify: `engine.py:196-218`
- Test: `tests/test_engine_model.py`

**Interfaces:**
- Consumes: `model_id`, `get_model_key` из Task 1 не нужны сверх существующих
- Produces: `build_url(site, rng, date=None, model=None)`, `route_weather_url(coords, date, tz, model=None)` — при `model=None` поведение прежнее (глобальная модель)

- [ ] **Step 1: Написать падающие тесты**

Добавить в `tests/test_engine_model.py`:

```python
def test_build_url_model_argument_overrides_global():
    """Разовый выбор не трогает model.json — он едет параметром."""
    _clear()
    engine.set_model_key("auto")
    assert "models=ecmwf_ifs025" in engine.build_url(_site(), "week", model="ecmwf")
    assert engine.get_model_key() == "auto"  # глобальная не изменилась


def test_build_url_without_model_uses_global():
    _clear()
    engine.set_model_key("icon")
    assert "models=icon_seamless" in engine.build_url(_site(), "1d", "2026-07-29")


def test_route_weather_url_model_argument_overrides_global():
    _clear()
    engine.set_model_key("auto")
    url = engine.route_weather_url([(42.0, 44.0)], "2026-07-29", "Asia/Tbilisi", model="gfs")
    assert "models=gfs_seamless" in url
    assert engine.get_model_key() == "auto"
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_engine_model.py -q`
Expected: FAIL — `TypeError: build_url() got an unexpected keyword argument 'model'`

- [ ] **Step 3: Реализовать**

Заменить сигнатуры и первые строки в `engine.py`:

```python
def build_url(site, rng, date=None, model=None):
    """`model` — разовый выбор для одного запроса; None означает глобальную настройку."""
    base = (f"https://api.open-meteo.com/v1/forecast?latitude={site['lat']}&longitude={site['lon']}"
            f"&wind_speed_unit=ms&timezone=auto&models={model_id(model or get_model_key())}")
```

```python
def route_weather_url(coords, date, tz, model=None):
    """Мульти-точечный запрос погоды на один день. `coords` — список пар (lat, lon).

    Часовой пояс задаётся ЯВНО, а не timezone=auto: при auto каждая локация
    получает свой пояс, и маршрут через границу поясов даёт точки с разными
    часами в одной таблице.
    """
    lats = ",".join(f"{lat:.4f}" for lat, _ in coords)
    lons = ",".join(f"{lon:.4f}" for _, lon in coords)
    return (f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}"
            f"&wind_speed_unit=ms&timezone={quote(tz)}"
            f"&models={model_id(model or get_model_key())}"
            f"&hourly={H_1D}&daily={D_1D}&start_date={date}&end_date={date}")
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/bin/python -m pytest tests/test_engine_model.py -q`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add engine.py tests/test_engine_model.py
git commit -m "feat(engine): build_url и route_weather_url принимают разовую модель"
```

---

### Task 3: engine — подпись модели берётся с данных

**Files:**
- Modify: `engine.py:343-347` (рядом с `_series_available`), `engine.py:759`, `engine.py:968`
- Test: `tests/test_engine_degrade.py`

**Interfaces:**
- Consumes: `model_label`, `get_model_key`
- Produces: `_model_note(data) -> str` — читает штампы `data["_model_key"]` и `data["_ceiling_model"]`, которые проставит Task 4

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_engine_degrade.py`:

```python
# ---------------------------------------------------------------- подпись модели


def test_model_note_reports_borrowed_ceiling():
    """Подпись должна признаваться, что потолок не от выбранной модели: иначе
    ИИ-разбор припишет число ECMWF, который его вообще не считает."""
    data = {"_model_key": "ecmwf", "_ceiling_model": "gfs"}
    assert engine._model_note(data) == "ECMWF (потолок GFS)"


def test_model_note_plain_when_ceiling_is_own():
    assert engine._model_note({"_model_key": "gfs", "_ceiling_model": "gfs"}) == "GFS"


def test_model_note_plain_without_splice():
    """Побочный запрос не удался — штампа нет, оговорки тоже."""
    assert engine._model_note({"_model_key": "ecmwf"}) == "ECMWF"


def test_model_note_falls_back_to_global(monkeypatch):
    """Прямой вызов из CLI и старых тестов: данных без штампа быть не должно,
    но падать на них нельзя."""
    monkeypatch.setattr(engine, "get_model_key", lambda: "icon")
    assert engine._model_note({}) == "ICON"
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_engine_degrade.py -q`
Expected: FAIL — `AttributeError: module 'engine' has no attribute '_model_note'`

- [ ] **Step 3: Реализовать**

В `engine.py` после `_series_available` (строка 347) добавить:

```python
def _model_note(data):
    """Подпись модели для карточки и фактов.

    Потолок берётся из отдельной модели, и об этом надо сказать прямо: без
    оговорки читатель (и LLM) припишет число выбранной модели, у которой его нет.
    Штампы кладёт слой forecast; их отсутствие означает прямой вызов мимо него.
    """
    key = data.get("_model_key") or get_model_key()
    label = model_label(key)
    ceiling = data.get("_ceiling_model")
    if ceiling and ceiling != key:
        return f"{label} (потолок {model_label(ceiling)})"
    return label
```

В `report_1day` (строка 759) заменить `{model_label(get_model_key())}` на `{_model_note(data)}`:

```python
        f"📍 {site['lat']:.3f}, {site['lon']:.3f} · {elev} м · {data.get('timezone','')} · {_model_note(data)}",
```

В `facts_1day` (строка 968) заменить `"model": model_label(get_model_key())` на `"model": _model_note(data)`:

```python
        "site": {"name": site["name"], "aspect": card(aspect) if aspect is not None else None, "aspect_deg": aspect,
                 "elevation_m": elev, "timezone": data.get("timezone"), "model": _model_note(data)},
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/bin/python -m pytest tests/test_engine_degrade.py tests/test_engine_facts.py -q`
Expected: PASS

- [ ] **Step 5: Полный прогон — подпись читают старые тесты карточки**

Run: `.venv/bin/python -m pytest -q`
Expected: 714 + новые, все зелёные

- [ ] **Step 6: Коммит**

```bash
git add engine.py tests/test_engine_degrade.py
git commit -m "feat(engine): подпись модели читается с данных и признаёт чужой потолок"
```

---

### Task 4: forecast — подстановка GFS-потолка в карточку и обзор

**Files:**
- Modify: `forecast.py:206-237` (`_fetch_build`)
- Create: `tests/test_ceiling_model.py`

**Interfaces:**
- Consumes: `engine.CEILING_VAR`, `engine.CEILING_MODEL_KEY`, `engine.ceiling_url` (Task 1)
- Produces: `_ceiling_series(body, gfs_body) -> list | None`, `_splice_ceiling(body, gfs_body) -> bool`, `_splice_ceiling_all(bodies, gfs_bodies) -> bool`, `_fetch_main(url) -> dict`, `_fetch_ceiling(url) -> dict | None`; `_fetch_build(site, rng, date, model=None)` штампует `data["_model_key"]` и, при удачной подстановке, `data["_ceiling_model"]`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_ceiling_model.py`:

```python
"""Потолок термиков всегда считается по GFS.

У ECMWF и ICON серии пограничного слоя нет вовсе, а под best_match её отдаёт
неизвестно какая подложка. Узкий побочный запрос к GFS подставляется в ответ
выбранной модели по индексу — но только если сетка часов совпала.
"""
import forecast
from fixtures import om_1day


def _gfs(times, values=1400.0):
    """Ответ побочного запроса: одна серия и массив времён."""
    return {"hourly": {"time": list(times),
                       "boundary_layer_height": [values] * len(times)}}


def test_splice_replaces_the_series():
    body = om_1day(boundary_layer_height=None)
    times = body["hourly"]["time"]
    assert forecast._splice_ceiling(body, _gfs(times)) is True
    assert body["hourly"]["boundary_layer_height"] == [1400.0] * len(times)


def test_splice_overrides_even_a_present_series():
    """Под auto серия есть, но неизвестно от какой подложки — всё равно заменяем."""
    body = om_1day(boundary_layer_height=900.0)
    times = body["hourly"]["time"]
    assert forecast._splice_ceiling(body, _gfs(times)) is True
    assert body["hourly"]["boundary_layer_height"][0] == 1400.0


def test_splice_refuses_on_time_mismatch():
    """Разъехавшаяся сетка часов дала бы потолок не от того часа."""
    body = om_1day(boundary_layer_height=None)
    shifted = [t.replace("T0", "T1") for t in body["hourly"]["time"]]
    assert forecast._splice_ceiling(body, _gfs(shifted)) is False
    assert all(v is None for v in body["hourly"]["boundary_layer_height"])


def test_splice_refuses_on_empty_or_broken_response():
    body = om_1day(boundary_layer_height=None)
    times = body["hourly"]["time"]
    assert forecast._splice_ceiling(body, {"hourly": {"time": list(times)}}) is False
    assert forecast._splice_ceiling(body, {}) is False
    assert forecast._splice_ceiling(body, None) is False


def test_route_splice_is_all_or_nothing():
    """Частичная подстановка смешала бы модели по участкам маршрута, и разрыв в
    профиле потолка читался бы как метеорология, а не как артефакт запроса."""
    a, b = om_1day(boundary_layer_height=None), om_1day(boundary_layer_height=None)
    times = a["hourly"]["time"]
    good, bad = _gfs(times), _gfs([t.replace("T0", "T1") for t in times])
    assert forecast._splice_ceiling_all([a, b], [good, bad]) is False
    assert all(v is None for v in a["hourly"]["boundary_layer_height"])  # и первая не тронута


def test_route_splice_refuses_on_point_count_mismatch():
    a, b = om_1day(boundary_layer_height=None), om_1day(boundary_layer_height=None)
    assert forecast._splice_ceiling_all([a, b], [_gfs(a["hourly"]["time"])]) is False
    assert forecast._splice_ceiling_all([a, b], None) is False


def test_route_splice_applies_to_every_point():
    a, b = om_1day(boundary_layer_height=None), om_1day(boundary_layer_height=None)
    times = a["hourly"]["time"]
    assert forecast._splice_ceiling_all([a, b], [_gfs(times), _gfs(times)]) is True
    assert a["hourly"]["boundary_layer_height"][0] == 1400.0
    assert b["hourly"]["boundary_layer_height"][0] == 1400.0
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_ceiling_model.py -q`
Expected: FAIL — `AttributeError: module 'forecast' has no attribute '_splice_ceiling'`

- [ ] **Step 3: Реализовать помощники подстановки**

В `forecast.py` перед `_fetch_build` (строка 206) добавить:

```python
def _ceiling_series(body, gfs_body):
    """GFS-серия пограничного слоя, пригодная для подстановки в body. Иначе None.

    Серии кладутся индекс в индекс: массивы time обязаны совпасть целиком.
    Проверено, что при одинаковых координатах и диапазоне open-meteo отдаёт
    одну и ту же сетку часов независимо от модели.
    """
    try:
        H, G = body["hourly"], gfs_body["hourly"]
    except (TypeError, KeyError):
        return None
    series = G.get(engine.CEILING_VAR)
    if not series or H.get("time") != G.get("time"):
        return None
    return series


def _splice_ceiling(body, gfs_body):
    """Подставить потолок из GFS в один ответ. True, если подстановка прошла."""
    series = _ceiling_series(body, gfs_body)
    if series is None:
        return False
    body["hourly"][engine.CEILING_VAR] = series
    return True


def _splice_ceiling_all(bodies, gfs_bodies):
    """Подставить потолок во ВСЕ точки маршрута или ни в одну.

    Частичная подстановка молча смешала бы модели по участкам: у одной точки
    потолок GFS, у соседней — выбранной модели, и разрыв в профиле читался бы
    как метеорология, а не как артефакт запроса.
    """
    if gfs_bodies is None or len(gfs_bodies) != len(bodies):
        return False
    series = [_ceiling_series(b, g) for b, g in zip(bodies, gfs_bodies)]
    if any(s is None for s in series):
        return False
    for b, s in zip(bodies, series):
        b["hourly"][engine.CEILING_VAR] = s
    return True


async def _fetch_ceiling(url):
    """Побочный запрос за потолком. None при любой неудаче: потолок приятен,
    но не стоит того, чтобы из-за него не вышел весь прогноз."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:  # noqa: BLE001 — потолок best-effort
        log.warning("ceiling fetch failed: %s", e)
        return None
    if isinstance(data, dict) and data.get("error"):
        log.warning("ceiling fetch: open-meteo %s", data.get("reason"))
        return None
    return data
```

- [ ] **Step 4: Убедиться, что тесты подстановки проходят**

Run: `.venv/bin/python -m pytest tests/test_ceiling_model.py -q`
Expected: PASS

- [ ] **Step 5: Встроить в `_fetch_build`**

Заменить `forecast.py:206-218` (заголовок `_fetch_build` и блок загрузки) на:

```python
async def _fetch_main(url):
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise ForecastError(f"Не удалось получить прогноз от open-meteo: {e}")
    if data.get("error"):
        raise ForecastError(f"open-meteo: {data.get('reason', 'ошибка запроса')}")
    return data


async def _fetch_build(site: dict, rng: str, date: str | None, model: str | None = None):
    """Fetch open-meteo once and build (card, png_bytes, facts, fallback_text, rows, grid).

    Потолок всегда берётся из GFS отдельным узким запросом — конкурентно с
    основным, поэтому задержка не растёт. Когда выбрана сама GFS, запроса нет.
    """
    key = model or engine.get_model_key()
    main = _fetch_main(engine.build_url(site, rng, date, model=key))
    if key == engine.CEILING_MODEL_KEY:
        data, gfs = await main, None
    else:
        data, gfs = await asyncio.gather(main, _fetch_ceiling(engine.ceiling_url(site, rng, date)))
    data["_model_key"] = key
    if _splice_ceiling(data, gfs):
        data["_ceiling_model"] = engine.CEILING_MODEL_KEY
```

Остальное тело `_fetch_build` (с `out = tempfile.mkdtemp(...)` и ниже) не трогать.

`_splice_ceiling(data, None)` возвращает `False` — отдельная проверка на `None` не нужна.

- [ ] **Step 6: Обновить вызов в `_ensure`**

`forecast.py:240-249` — прокинуть модель дальше:

```python
async def _ensure(site: dict, rng: str, date: str | None, key: tuple, model: str | None = None):
    """Return (card, pngs, facts, fallback, rows, grid), fetching only on a cold cache."""
    now = time.monotonic()
    _purge(now)
    if key in _fcache:
        return _fcache[key][1:]
    card, pngs, facts, fallback, rows, grid = await _fetch_build(site, rng, date, model)
    _fcache[key] = (now + _TTL, card, pngs, facts, fallback, rows, grid)
    return card, pngs, facts, fallback, rows, grid
```

- [ ] **Step 7: Полный прогон**

Run: `.venv/bin/python -m pytest -q`
Expected: всё зелёное (сеть в тестах не трогается — `_fetch_build` везде замокан)

- [ ] **Step 8: Коммит**

```bash
git add forecast.py tests/test_ceiling_model.py
git commit -m "feat(forecast): потолок термиков подставляется из GFS"
```

---

### Task 5: forecast — тот же потолок на маршруте

**Files:**
- Modify: `forecast.py:324-342` (`_ensure_route_weather`)
- Test: `tests/test_ceiling_model.py`

**Interfaces:**
- Consumes: `_splice_ceiling_all`, `_fetch_ceiling` (Task 4), `engine.route_ceiling_url` (Task 1)
- Produces: `_ensure_route_weather(samples, date, model=None)` — тот же контракт, потолок во всех точках из GFS

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_ceiling_model.py`:

```python
async def test_route_weather_splices_ceiling_from_gfs(monkeypatch):
    """На маршруте потолок должен быть из той же модели, что и на старте —
    иначе «потолок» значит разное в двух частях одного ответа."""
    import engine
    from route import Sample

    body = om_1day(boundary_layer_height=None)
    times = body["hourly"]["time"]
    calls = []

    async def fake_weather(url):
        calls.append(url)
        return [om_1day(boundary_layer_height=None)]

    async def fake_ceiling(url):
        calls.append(url)
        return [_gfs(times)]

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "_fetch_ceiling", fake_ceiling)
    monkeypatch.setattr(engine, "get_model_key", lambda: "ecmwf")
    forecast._rcache.clear()

    samples = [Sample(km=0.0, lat=42.0, lon=44.0)]
    bodies = await forecast._ensure_route_weather(samples, "2026-07-29")

    assert bodies[0]["hourly"]["boundary_layer_height"][0] == 1400.0
    assert any("models=gfs_seamless" in u for u in calls)
```

`route.Sample` — датакласс, у которого обязательны только `km`, `lat`, `lon`
(`route.py:287-292`), остальные поля имеют значения по умолчанию.

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv/bin/python -m pytest tests/test_ceiling_model.py -q`
Expected: FAIL — потолок остался `None` (побочный запрос не делается)

- [ ] **Step 3: Реализовать**

Заменить `forecast.py:324-342`:

```python
async def _ensure_route_weather(samples, date, model=None):
    """Погода по всем сэмплам одним запросом. Скорость и тумблер ветра в ключ не
    входят: они меняют только пересчёт времени, который дешёв и идёт поверх кэша.

    Потолок, как и на старте, всегда из GFS — вторым узким запросом конкурентно
    с основным.
    """
    coords = [(s.lat, s.lon) for s in samples]
    mkey = model or engine.get_model_key()
    key = (_route_key(coords), date, mkey)
    now = time.monotonic()
    _purge(now)
    if key in _rcache:
        return _rcache[key][1]
    tz = os.environ.get("TZ") or "Asia/Tbilisi"
    url = engine.route_weather_url(coords, date, tz, model=mkey)
    try:
        if mkey == engine.CEILING_MODEL_KEY:
            bodies, gfs = await _fetch_route_weather(url), None
        else:
            bodies, gfs = await asyncio.gather(
                _fetch_route_weather(url),
                _fetch_ceiling(engine.route_ceiling_url(coords, date, tz)))
    except httpx.HTTPError as e:
        raise ForecastError(f"Не удалось получить прогноз от open-meteo: {e}")
    if len(bodies) != len(samples):
        raise ForecastError("open-meteo вернул другое число точек, чем запрошено")
    _splice_ceiling_all(bodies, gfs)
    _rcache[key] = (now + _TTL, bodies)
    return bodies
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/bin/python -m pytest tests/test_ceiling_model.py -q`
Expected: PASS

- [ ] **Step 5: Полный прогон**

Run: `.venv/bin/python -m pytest -q`
Expected: всё зелёное

- [ ] **Step 6: Коммит**

```bash
git add forecast.py tests/test_ceiling_model.py
git commit -m "feat(forecast): потолок на маршруте тоже из GFS"
```

---

### Task 6: forecast — проброс разовой модели до ключа кэша

**Files:**
- Modify: `forecast.py:122` (`_detail_context`), `forecast.py:150`, `forecast.py:170-197` (`_resolve`, `cached_dates`), `forecast.py:251-262` (`get_forecast`, `get_wind_grid`), `forecast.py:766-774` (`get_analysis`)
- Test: `tests/test_ceiling_model.py`

**Interfaces:**
- Consumes: `_ensure`, `_fetch_build` из Task 4
- Produces: `get_forecast(site_name, rng, date=None, model=None)`, `get_wind_grid(site_name, date, model=None)`, `get_analysis(site_name, rng, date=None, deep=False, model=None)`, `cached_dates(site_name, rng, date=None, model=None)`, `_resolve(site_name, rng, date=None, model=None)`

- [ ] **Step 1: Написать падающие тесты**

Добавить в `tests/test_ceiling_model.py`:

```python
# ---------------------------------------------------------------- разовая модель


def test_cache_key_separates_models():
    """Разовый рендер не должен вытеснять запись глобальной модели и наоборот."""
    import engine
    engine.set_model_key("auto")
    _s, _d, glob = forecast._resolve("Гудаури", "1d", "2026-07-29")
    _s, _d, once = forecast._resolve("Гудаури", "1d", "2026-07-29", model="ecmwf")
    assert glob != once
    assert glob[3] == "auto" and once[3] == "ecmwf"
    assert engine.get_model_key() == "auto"  # _resolve ничего не пишет


async def test_get_forecast_passes_model_down(monkeypatch):
    seen = {}

    async def fake_build(site, rng, date, model=None):
        seen["model"] = model
        return "CARD", [], {}, "FB", [], None

    monkeypatch.setattr(forecast, "_fetch_build", fake_build)
    forecast._fcache.clear()
    await forecast.get_forecast("Гудаури", "1d", "2026-07-29", model="icon")
    assert seen["model"] == "icon"
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_ceiling_model.py -q`
Expected: FAIL — `TypeError: _resolve() got an unexpected keyword argument 'model'`

- [ ] **Step 3: Реализовать проброс**

`_resolve` — сигнатура и последняя строка:

```python
def _resolve(site_name: str, rng: str, date: str | None, model: str | None = None):
```
```python
    return site, date, (site["name"], rng, date, model or engine.get_model_key())
```

`cached_dates`:

```python
def cached_dates(site_name: str, rng: str, date: str | None = None,
                 model: str | None = None) -> list[str] | None:
    """Dates (site-local) of a cached overview — for the day-picker. None on a cold cache."""
    try:
        _site, _date, key = _resolve(site_name, rng, date, model)
```

`get_forecast`:

```python
async def get_forecast(site_name: str, rng: str, date: str | None = None,
                       model: str | None = None):
    """Factual card + charts. No LLM. rng: 1d | 3d | week | 2weeks.

    `model` — разовый выбор кнопкой под прогнозом; глобальную настройку не трогает.
    """
    site, date, key = _resolve(site_name, rng, date, model)
    card, pngs, _facts, _fallback, _rows, _grid = await _ensure(site, rng, date, key, model)
    return card, pngs
```

`get_wind_grid`:

```python
async def get_wind_grid(site_name: str, date: str, model: str | None = None) -> bytes:
    """PNG of the altitude × hour wind grid for a single day. Reuses the warm 1d cache
    (no re-fetch) and builds the image on demand — /today never pays for it unused."""
    site, date, key = _resolve(site_name, "1d", date, model)
    _card, _pngs, _facts, _fallback, _rows, grid = await _ensure(site, "1d", date, key, model)
```

`get_analysis` — сигнатура, `_resolve`, `_ensure` и `_detail_context`:

```python
async def get_analysis(site_name: str, rng: str, date: str | None = None,
                       deep: bool = False, model: str | None = None) -> str:
```
```python
    site, date, base_key = _resolve(site_name, rng, date, model)
```
```python
    card, _pngs, facts, fallback, _rows, _grid = await _ensure(site, rng, date, base_key, model)
```
```python
        ctx = await _detail_context(site, date, model)
```

`_detail_context` — сигнатура и запрос предыдущего дня:

```python
async def _detail_context(site: dict, date: str, model: str | None = None) -> dict:
```
```python
            r = await client.get(engine.build_url(site, "1d", prev, model=model))
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/bin/python -m pytest tests/test_ceiling_model.py -q`
Expected: PASS

- [ ] **Step 5: Полный прогон**

Run: `.venv/bin/python -m pytest -q`
Expected: всё зелёное — все новые параметры необязательные, старые вызовы не сломаны

- [ ] **Step 6: Коммит**

```bash
git add forecast.py tests/test_ceiling_model.py
git commit -m "feat(forecast): разовая модель проходит до ключа кэша и URL"
```

---

### Task 7: bot — кнопка модели выбирает разово

**Files:**
- Modify: `bot.py:256-266` (`_model_switch_keyboard`), `bot.py:269-310` (`send_forecast`), `bot.py:410-435` (`cb_switch_model`), `tests/conftest.py:108-130` (фикстуры)
- Test: `tests/test_dialogs.py:574-591`

**Interfaces:**
- Consumes: `forecast.get_forecast(..., model=...)` (Task 6), `engine.MODELS`
- Produces: `send_forecast(message, site, rng, date=None, model=None)`, `_model_switch_keyboard(site, rng, date, current)`

- [ ] **Step 1: Обновить фикстуры под новый параметр**

`tests/conftest.py` — обе фикстуры записывают модель:

```python
@pytest.fixture()
def fc_calls(monkeypatch):
    """Patch forecast.get_forecast; returns the recorded (site, rng, date, model) calls."""
    calls = []

    async def fake(site, rng, date=None, model=None):
        calls.append((site, rng, date, model))
        return f"CARD {site} {rng} {date}", [b"png"]

    monkeypatch.setattr(forecast, "get_forecast", fake)
    return calls


@pytest.fixture()
def an_calls(monkeypatch):
    """Patch forecast.get_analysis; returns the recorded (site, rng, date, deep, model) calls."""
    calls = []

    async def fake(site, rng, date=None, deep=False, model=None):
        calls.append((site, rng, date, deep, model))
        return "АНАЛИЗ ГОТОВ"

    monkeypatch.setattr(forecast, "get_analysis", fake)
    return calls
```

- [ ] **Step 2: Переписать тесты кнопки под новое поведение**

В `tests/test_dialogs.py` заменить `test_model_switch_button_reruns_forecast` (строки 588-591) и поправить два соседних теста, которые ищут подпись клавиатуры:

```python
async def test_forecast_offers_model_switch_buttons(feed, session, fc_calls):
    await feed(text_update("/today Гудаури"))
    kb = kb_for(session, "🌐 Другая модель (разово):")
    datas = [b.callback_data for b in buttons(kb)]
    assert datas == [f"mf|auto|Гудаури|1d|{TODAY}", f"mf|ecmwf|Гудаури|1d|{TODAY}",
                     f"mf|gfs|Гудаури|1d|{TODAY}", f"mf|icon|Гудаури|1d|{TODAY}"]


async def test_overview_model_switch_has_empty_date(feed, session, fc_calls):
    await feed(text_update("/week Гудаури"))
    kb = kb_for(session, "🌐 Другая модель (разово):")
    assert [b.callback_data for b in buttons(kb)][0] == "mf|auto|Гудаури|week|"


async def test_model_switch_button_does_not_change_global_model(feed, session, fc_calls):
    """Кнопка под прогнозом — разовый выбор. Глобально модель меняет только
    /model: иначе один взгляд на альтернативную модель молча переопределял бы
    все последующие прогнозы, включая автоматические."""
    engine.set_model_key("auto")
    await feed(callback_update(f"mf|gfs|Гудаури|1d|{TODAY}"))
    assert engine.get_model_key() == "auto"                 # глобальная не тронута
    assert fc_calls == [("Гудаури", "1d", TODAY, "gfs")]    # пересчёт в выбранной


async def test_model_switch_marks_the_one_off_model_and_names_the_global(feed, session, fc_calls):
    engine.set_model_key("auto")
    await feed(callback_update(f"mf|ecmwf|Гудаури|1d|{TODAY}"))
    caption = [t for t in texts(session) if t.startswith("🌐")][-1]
    assert "ECMWF" in caption and "разово" in caption
    assert "Auto" in caption and "/model" in caption        # где менять постоянную
    kb = kb_for(session, caption)
    labels = [b.text for b in buttons(kb)]
    assert any("ECMWF" in l and "✓" in l for l in labels)   # галочка на показанной
    assert not any("Auto" in l and "✓" in l for l in labels)


async def test_model_switch_unknown_key_alerts_and_does_not_render(feed, session, fc_calls):
    await feed(callback_update(f"mf|plasma|Гудаури|1d|{TODAY}"))
    alert = cb_answers(session)[-1]
    assert "Неизвестная" in alert.text and alert.show_alert
    assert fc_calls == []
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_dialogs.py -q -k model`
Expected: FAIL — глобальная модель всё ещё меняется, подпись клавиатуры старая

- [ ] **Step 4: Реализовать клавиатуру и подпись**

Заменить `bot.py:256-266`:

```python
def _model_switch_keyboard(site: str, rng: str, date: str | None,
                           current: str) -> InlineKeyboardMarkup | None:
    """Row of model buttons under a forecast; tapping re-renders it with that model.
    An over-long site name overflows callback_data → _btn drops that button (with a warning).

    `current` — модель, которой посчитан ПОКАЗАННЫЙ прогноз, а не глобальная:
    после разового переключения галочка должна стоять на том, что на экране.
    """
    row = []
    for k in engine.MODELS:
        btn = _btn(f"{_model_short(k)}{' ✓' if k == current else ''}", f"mf|{k}|{site}|{rng}|{date or ''}")
        if btn is not None:
            row.append(btn)
    return InlineKeyboardMarkup(inline_keyboard=[row]) if row else None


def _model_switch_caption(model: str | None) -> str:
    """Подпись ряда моделей. При разовом выборе называет и постоянную модель —
    иначе непонятно, куда вернётся бот на следующем запросе."""
    if model is None:
        return "🌐 Другая модель (разово):"
    return (f"🌐 Модель: {engine.model_label(model)} — разово. "
            f"Постоянная: {engine.model_label(engine.get_model_key())} (/model)")
```

- [ ] **Step 5: Реализовать `send_forecast`**

В `bot.py:269` заменить сигнатуру и первый вызов:

```python
async def send_forecast(message: Message, site: str, rng: str, date: str | None = None,
                        model: str | None = None):
    if rng == "1d" and not date:
        date = dt.date.today().isoformat()
    try:
        # keeps the "typing…" status alive while forecast/analysis runs (>5 s)
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            card, pngs = await forecast.get_forecast(site, rng, date, model=model)
```

В конце `send_forecast` заменить блок ряда моделей (строки 306-308):

```python
    eff = model or engine.get_model_key()
    mkb = _model_switch_keyboard(site, rng, date, eff)  # let the user re-run in another model
    if mkb is not None:
        await message.answer(_model_switch_caption(model), reply_markup=mkb)
```

- [ ] **Step 6: Реализовать `cb_switch_model`**

Заменить `bot.py:410-435` целиком:

```python
@dp.callback_query(F.data.startswith("mf|"), flags={"forecast": True})
async def cb_switch_model(cb: CallbackQuery):
    """A model button under a forecast → re-render that forecast in that model.

    Выбор РАЗОВЫЙ: model.json не пишется. Постоянную модель меняет только /model —
    иначе взгляд на альтернативную модель молча переопределял бы все дальнейшие
    прогнозы, включая те, что пользователь запросит завтра.
    """
    msg = await cb_message(cb)
    if msg is None:
        return
    parts = cb.data.split("|")
    if len(parts) != 5:
        await cb.answer()
        return
    _, key, site, rng, date = parts
    if key not in engine.MODELS:
        await cb.answer("Неизвестная модель.", show_alert=True)
        return
    await cb.answer(f"{engine.model_label(key)} — разово, пересчитываю…")
    await send_forecast(msg, site, rng, date or None, model=key)
```

- [ ] **Step 7: Убедиться, что тесты проходят**

Run: `.venv/bin/python -m pytest tests/test_dialogs.py -q`
Expected: PASS

- [ ] **Step 8: Полный прогон**

Run: `.venv/bin/python -m pytest -q`
Expected: всё зелёное

- [ ] **Step 9: Коммит**

```bash
git add bot.py tests/conftest.py tests/test_dialogs.py
git commit -m "feat(bot): кнопка модели под прогнозом выбирает модель разово"
```

---

### Task 8: bot — код модели в callback_data соседних кнопок

**Files:**
- Modify: `bot.py:196-217` (`_day_picker_kb`), `bot.py:269-310` (`send_forecast`), `bot.py:691-716` (`cb_analysis`), `bot.py:718-740` (`cb_pick_day`), `bot.py:742-770` (`cb_wind_grid`)
- Test: `tests/test_dialogs.py`

**Interfaces:**
- Consumes: `engine.model_code`, `engine.model_for_code` (Task 1), `send_forecast(..., model=...)` (Task 7), `forecast.get_analysis(..., model=...)` / `get_wind_grid(..., model=...)` / `cached_dates(..., model=...)` (Task 6)
- Produces: `_split_cb(data, n) -> tuple[list[str] | None, str | None]`, `_model_sfx(model) -> str`

- [ ] **Step 1: Написать падающие тесты**

Добавить в `tests/test_dialogs.py` рядом с остальными тестами моделей:

```python
async def test_one_off_model_travels_to_every_button(feed, session, fc_calls):
    """ИИ-разбор и ветер по высотам должны считаться по той же модели, что
    показана: иначе разбор описывает не ту карточку, которую видит пользователь."""
    await feed(callback_update(f"mf|ecmwf|Гудаури|1d|{TODAY}"))
    more = [b.callback_data for b in buttons(kb_for(session, "Ещё:"))]
    assert f"llm|Гудаури|1d|{TODAY}|e" in more
    assert f"deep|Гудаури|1d|{TODAY}|e" in more
    assert f"wg|Гудаури|{TODAY}|e" in more


async def test_without_one_off_model_callbacks_are_unchanged(feed, session, fc_calls):
    """Обычный путь остаётся байт-в-байт: код дописывается только при разовом
    выборе, иначе он съедал бы запас длины у имён стартов."""
    await feed(text_update("/today Гудаури"))
    more = [b.callback_data for b in buttons(kb_for(session, "Ещё:"))]
    assert f"llm|Гудаури|1d|{TODAY}" in more
    assert not any(d.endswith("|e") or d.endswith("|a") for d in more)


async def test_analysis_button_carries_the_one_off_model(feed, session, an_calls):
    await feed(callback_update(f"llm|Гудаури|1d|{TODAY}|e"))
    assert an_calls == [("Гудаури", "1d", TODAY, False, "ecmwf")]


async def test_wind_grid_button_carries_the_one_off_model(feed, session, monkeypatch):
    seen = {}

    async def fake(site, date, model=None):
        seen["model"] = model
        return b"png"

    monkeypatch.setattr(forecast, "get_wind_grid", fake)
    await feed(callback_update(f"wg|Гудаури|{TODAY}|i"))
    assert seen["model"] == "icon"


async def test_day_picker_carries_the_one_off_model(feed, session, fc_calls):
    await feed(callback_update(f"pd|Гудаури|{TODAY}|g"))
    assert fc_calls == [("Гудаури", "1d", TODAY, "gfs")]


async def test_unknown_model_code_falls_back_to_global(feed, session, an_calls):
    """Устаревшая кнопка из старого сообщения не должна ронять обработчик."""
    await feed(callback_update(f"llm|Гудаури|1d|{TODAY}|z"))
    assert an_calls == [("Гудаури", "1d", TODAY, False, None)]


def test_every_model_button_fits_the_callback_limit():
    """Код модели съедает 2 байта из 64. Проверяем на реальных именах стартов."""
    import engine as eng
    for site in [s["name"] for s in eng.load_sites()]:
        for code in eng.MODEL_CODES.values():
            for data in (f"llm|{site}|2weeks|2026-07-29|{code}",
                         f"deep|{site}|2weeks|2026-07-29|{code}",
                         f"wg|{site}|2026-07-29|{code}",
                         f"pd|{site}|2026-07-29|{code}"):
                assert len(data.encode("utf-8")) <= 64, data
```

`forecast` и `engine` в `tests/test_dialogs.py` уже импортированы (строки 10-12), дополнительных импортов не нужно.

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_dialogs.py -q -k "one_off or model_code or callback_limit"`
Expected: FAIL — кнопки без кода, обработчики его не читают

- [ ] **Step 3: Реализовать помощники разбора**

В `bot.py` после `_btn` (строка 162) добавить:

```python
def _model_sfx(model: str | None) -> str:
    """Хвост callback_data с кодом разовой модели. Пусто без разового выбора —
    обычный путь не должен терять запас длины у имён стартов."""
    return f"|{engine.model_code(model)}" if model else ""


def _split_cb(data: str, n: int):
    """Разбор callback_data на n полей плюс необязательный код модели последним.

    Полный split, а не maxsplit: с ограничением дописанный код попал бы в поле
    даты. Символ «|» в именах стартов запрещён при /add, поэтому полей ровно
    столько, сколько положено. Возвращает (None, None) при неверном числе полей.
    """
    parts = data.split("|")
    if len(parts) == n:
        return parts, None
    if len(parts) == n + 1:
        return parts[:n], engine.model_for_code(parts[n])
    return None, None
```

- [ ] **Step 4: Дописывать код в кнопки**

`_day_picker_kb` — принимает модель и передаёт её в `cached_dates` и в кнопки (`bot.py:196-217`):

```python
def _day_picker_kb(site: str, rng: str, model: str | None = None) -> InlineKeyboardMarkup | None:
```
```python
    dates = forecast.cached_dates(site, rng, model=model)
```
```python
    sfx = _model_sfx(model)
    rows, row = [], []
    for iso in dates:
        d = dt.date.fromisoformat(iso)
        btn = _btn(f"{_WD[d.weekday()]} {d.day:02d}.{d.month:02d}", f"pd|{site}|{iso}{sfx}")
```

Строку `docstring`/начало функции выше `dates = ...` не трогать.

`send_forecast` — три ряда кнопок (`bot.py:296-305`):

```python
    # LLM analysis is off by default — offer it on demand.
    sfx = _model_sfx(model)
    row = [_btn("🧠 Разбор от ИИ", f"llm|{site}|{rng}|{date or ''}{sfx}")]
    if rng == "1d":  # deep analysis (surrounding points + previous day) — 1-day only
        row.append(_btn("📊 Глубокий разбор", f"deep|{site}|{rng}|{date or ''}{sfx}"))
    row = [b for b in row if b is not None]
    kb_rows = [row] if row else []
    if rng == "1d":  # wind aloft grid (altitude × hour) — 1-day only
        wg = _btn("🌬 Ветер по высотам", f"wg|{site}|{date or ''}{sfx}")
        if wg is not None:
            kb_rows.append([wg])
    if kb_rows:
        await message.answer("Ещё:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    if rng != "1d":  # overview → let the user drill into a single day
        kb = _day_picker_kb(site, rng, model)
```

- [ ] **Step 5: Читать код в обработчиках**

`cb_analysis` (`bot.py:696-706`):

```python
    parts, model = _split_cb(cb.data, 4)
    if parts is None:
        await cb.answer()
        return
    kind, site, rng, date = parts
    deep = kind == "deep"
    await cb.answer("Считаю глубокий разбор…" if deep else "Считаю разбор…")
    try:
        async with ChatActionSender.typing(bot=msg.bot, chat_id=msg.chat.id):
            text = await forecast.get_analysis(site, rng, date or None, deep=deep, model=model)
```

`cb_pick_day` (`bot.py:724-740`):

```python
    parts, model = _split_cb(cb.data, 3)
    if parts is None:
        await cb.answer()
        return
    try:
        day = dt.date.fromisoformat(parts[2])
    except ValueError:
        await cb.answer()
        return
    _, site, date = parts
```

и последняя строка обработчика:

```python
    await send_forecast(msg, site, "1d", date, model=model)
```

`cb_wind_grid` (`bot.py:747-762`):

```python
    parts, model = _split_cb(cb.data, 3)
    if parts is None:
        await cb.answer()
        return
    try:
        day = dt.date.fromisoformat(parts[2])
    except ValueError:
        await cb.answer()
        return
    _, site, date = parts
```

и вызов:

```python
            png = await forecast.get_wind_grid(site, date, model=model)
```

- [ ] **Step 6: Убедиться, что тесты проходят**

Run: `.venv/bin/python -m pytest tests/test_dialogs.py -q`
Expected: PASS

- [ ] **Step 7: Полный прогон**

Run: `.venv/bin/python -m pytest -q`
Expected: всё зелёное

- [ ] **Step 8: Коммит**

```bash
git add bot.py tests/test_dialogs.py
git commit -m "feat(bot): разовая модель едет в кнопках пересчитанного прогноза"
```

---

### Task 9: README — обе новые оговорки

**Files:**
- Modify: `README.md:28`, `README.md:158-178`

**Interfaces:**
- Consumes: поведение из Task 1-8
- Produces: документация (кода не производит)

- [ ] **Step 1: Обновить строку таблицы команд**

`README.md:28` — кнопка больше не меняет модель насовсем:

```markdown
| `/model [auto\|ecmwf\|gfs\|icon]` | выбор метеомодели (деф. Auto); без аргумента — кнопки-пикер. **Единственный** способ сменить модель насовсем: кнопка под прогнозом пересчитывает разово |
```

- [ ] **Step 2: Переписать раздел «Метеомодель»**

Заменить `README.md:158-161`:

```markdown
**Метеомодель.** Источник open-meteo (`&models=`): `auto` (`best_match`), `ecmwf`,
`gfs`, `icon`. По умолчанию — **Auto**. Постоянную модель меняет только команда
`/model` (без аргумента — кнопки-пикер). Кнопки «🌐 Другая модель» под прогнозом
пересчитывают **разово**: глобальная настройка не трогается, а разовый выбор
распространяется на все кнопки того же сообщения — ИИ-разбор и ветер по высотам
считаются по той модели, что показана в карточке. Текущая модель подписана в карточке.

**Потолок термиков всегда считается по GFS**, независимо от выбранной модели.
Отдельный узкий запрос за `boundary_layer_height` идёт конкурентно с основным, и
серия подставляется в ответ по индексу (массивы часов у open-meteo совпадают
между моделями). Причин две: у ECMWF и ICON этой серии нет вовсе, а под `auto`
её отдаёт неизвестно какая подложка `best_match` — число оказывается несравнимым
между стартами и днями. Когда выбрана сама GFS, второго запроса нет. Если
побочный запрос не удался, потолок считается по выбранной модели, то есть на
ECMWF и ICON его по-прежнему не будет. В карточке это подписано явно:
`· ECMWF (потолок GFS)`.

Из GFS берётся ровно одна переменная. Заполнять ей остальные пробелы значило бы
подменить чужой моделью половину входов скоринга — тогда выбор ECMWF теряет смысл.
```

- [ ] **Step 3: Поправить вывод под таблицей моделей**

`README.md:173` — потолок больше не выпадает:

```markdown
На ECMWF выпадают сдвиг ветра, видимость, LI и CIN — это **4 вето из 13 не могут
сработать в принципе**. W\* и глубина рабочего слоя теперь работают везде:
пограничный слой всегда берётся из GFS (см. выше), а радиация есть у всех
моделей. Скоринг честно деградирует (веса перенормируются, непроверенные вето
перечисляются словами в карточке), но дефолт должен считать всё. Молний у
open-meteo для Кавказа нет ни на одной модели: `lightning_potential` и
`thunderstorm_probability` существуют только для ICON-D2 в Центральной Европе.
```

Счёт вето не меняется: ни одно из 13 вето не читает `boundary_layer_height`
напрямую (`criteria.VETOES`, строки 394-430). Он кормит `w_star` и `bl_depth` —
то есть два мультипликативных штрафа и один оцениваемый параметр, но не вето.
Выпадающие на ECMWF четыре — `cape_cin`, `lifted_index`, `visibility`, `shear`.

- [ ] **Step 4: Проверить, что тесты не читают изменённые строки README**

Run: `.venv/bin/python -m pytest -q`
Expected: всё зелёное

- [ ] **Step 5: Коммит**

```bash
git add README.md
git commit -m "docs: потолок всегда по GFS, кнопка модели выбирает разово"
```

---

## Проверка после всех задач

- [ ] `.venv/bin/python -m pytest -q` — 714 существующих плюс новые, всё зелёное
- [ ] `grep -n "set_model_key" bot.py` — остались только `cmd_model` и `cb_pick_model`, в `cb_switch_model` вызова нет
- [ ] `grep -n "model_label(get_model_key())" engine.py` — пусто, обе подписи идут через `_model_note`
- [ ] Живая проверка одним запросом: временно выставить `/model ecmwf`, запросить прогноз на день и убедиться, что в карточке есть строка «(потолок GFS)» и непустой потолок

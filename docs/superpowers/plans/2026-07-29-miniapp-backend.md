# Mini App: бэкенд-фундамент (фазы 1–2) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести хранилище с JSON-файлов на SQLite с разделением на общее и личное, и убрать из домена неявные чтения глобальных настроек — чтобы поверх него можно было поставить второй интерфейс.

**Architecture:** Новый модуль `store.py` — единственное место с SQL и `user_id`. `engine.py` перестаёт трогать хранилище и остаётся расчётами и рендерингом. `settings.py` и `routes.py` удаляются. Публичные функции `forecast.py` начинают требовать `model` и `cfg` явными параметрами; кэш начинает хранить сырьё, а производные (текст, PNG, факты) считает лениво.

**Tech Stack:** Python 3.12, `sqlite3` из стандартной библиотеки, pytest. Новых зависимостей в этих двух фазах нет.

## Global Constraints

- Спека: `docs/superpowers/specs/2026-07-28-miniapp-architecture-design.md`. При расхождении плана со спекой — права спека.
- **Поведение бота меняется только там, где это записано в спеке:** личные настройки вместо общих (задача 7), исчезает сообщение о потерянной точке по координатам (задача 7, точки теперь переживают рестарт), час пика для Gemini становится тем же, что в карточке (задача 10). Всё остальное пользователь заметить не должен.
- **Тесты зелёные к концу каждой задачи, без исключений.** Красных коммитов в ветке не бывает: харнесс, домен и бот читают хранилище и переключаются одним коммитом в задаче 7. Тесты, которые правятся осознанно, перечислены в задачах 7, 9, 10.
- Сообщения пользователю — по-русски, как в существующем коде. Комментарии в коде — по-русски там, где объясняют «почему»; докстринги — как в соседних функциях модуля.
- Имена полей `avg_route_speed_kmh`, `wind_correction_enabled`, `model_key` фиксированы: совпадают с ключами нынешнего `settings.DEFAULTS`, чтобы переименования не было.
- `store.py` не импортирует ни один модуль проекта. Это проверяется тестом в задаче 1.
- Коммит после каждой задачи. Ветка: `feature/miniapp-backend`.
- Прогон тестов: `.venv/bin/python -m pytest -q`.

---

## Структура файлов

| Файл | Ответственность | Действие |
|---|---|---|
| `store.py` | SQLite: схема, подключение, старты, настройки, маршруты, рельеф, ad-hoc, миграция | Создать |
| `engine.py` | Метеорасчёты, URL, текстовый рендер. Больше не трогает диск | Изменить |
| `forecast.py` | Фетч, кэш, оркестрация. `model` и `cfg` — явные параметры | Изменить |
| `route.py` | Геометрия и физика. Добавляется разбор строк маршрута из хранилища | Изменить |
| `bot.py` | Хендлеры резолвят `prefs` пользователя | Изменить |
| `settings.py` | — | Удалить |
| `routes.py` | — | Удалить |
| `tests/conftest.py` | Временная SQLite на тест вместо трёх JSON-файлов | Изменить |
| `tests/test_store.py` | Тесты хранилища | Создать |
| `tests/test_store_migration.py` | Тесты миграции из JSON | Создать |
| `tests/test_lazy_cache.py` | Тесты ленивых производных кэша | Создать |

`store.py` держится одним файлом, а не пакетом: таблиц шесть, функций около двадцати, и все они про одно — доступ к данным. Дробить его на `store/sites.py`, `store/prefs.py` значило бы разносить по файлам то, что меняется вместе.

---

# ФАЗА 1 — хранилище

### Task 1: `store.py` — схема и подключение

**Files:**
- Create: `store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: ничего
- Produces:
  - `store.DB_PATH: str` — путь к файлу БД, из `DB_PATH` env или `<repo>/data/pgbot.db`
  - `store.SCHEMA: str` — DDL всех таблиц
  - `store.connect() -> sqlite3.Connection` — соединение с `row_factory=sqlite3.Row`, WAL, `foreign_keys=ON`
  - `store.init() -> None` — создаёт каталог и таблицы, идемпотентна

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_store.py`:

```python
"""Тесты хранилища. Своя временная БД на тест — conftest переезжает на неё в задаче 7."""
import importlib
import os
import sqlite3

import pytest


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Свежий модуль store с БД во временном каталоге.

    Модуль читает DB_PATH на импорте (как engine читает SITES_FILE), поэтому
    перезагружаем его после подмены переменной окружения.
    """
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    import store as st
    importlib.reload(st)
    st.init()
    return st


def test_init_creates_all_tables(store):
    with store.connect() as conn:
        names = {r["name"] for r in
                 conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sites", "site_aliases", "user_prefs", "routes",
            "terrain", "adhoc_points"} <= names


def test_init_is_idempotent(store):
    store.init()
    store.init()
    with store.connect() as conn:
        n = conn.execute("SELECT count(*) c FROM sqlite_master WHERE type='table'").fetchone()["c"]
    assert n >= 6


def test_connect_uses_wal(store):
    with store.connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_connect_returns_rows_by_name(store):
    with store.connect() as conn:
        conn.execute("INSERT INTO sites (name, lat, lon, elevation_m, added_at) "
                     "VALUES ('X', 1.0, 2.0, 300, '2026-01-01')")
        row = conn.execute("SELECT name, elevation_m FROM sites").fetchone()
    assert row["name"] == "X" and row["elevation_m"] == 300


def test_alias_cascade_on_site_delete(store):
    with store.connect() as conn:
        conn.execute("INSERT INTO sites (name, lat, lon, elevation_m, added_at) "
                     "VALUES ('X', 1.0, 2.0, 300, '2026-01-01')")
        conn.execute("INSERT INTO site_aliases (alias, name) VALUES ('x', 'X')")
        conn.execute("DELETE FROM sites WHERE name = 'X'")
        left = conn.execute("SELECT count(*) c FROM site_aliases").fetchone()["c"]
    assert left == 0


def test_store_imports_no_project_modules():
    """store — фундамент; зависимость от engine/route/forecast создала бы цикл."""
    import ast
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.parent / "store.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"engine", "route", "forecast", "bot", "charts",
                            "criteria", "analysis", "guards"})
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'store'`

- [ ] **Step 3: Написать `store.py`**

```python
"""SQLite-хранилище бота.

Единственный модуль, который знает про user_id и SQL. Ни от одного модуля
проекта не зависит: на нём стоят и engine, и forecast, и bot, и любая
зависимость обратно замкнула бы цикл.

Что общее, а что личное:
  общее — старты (библиотека команды), рельеф, точки по координатам;
  личное — маршруты, маршрутные настройки, выбор метеомодели.
"""
import dataclasses
import datetime as dt
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH") or os.path.join(HERE, "data", "pgbot.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
  name        TEXT PRIMARY KEY,
  lat         REAL NOT NULL,
  lon         REAL NOT NULL,
  elevation_m INTEGER NOT NULL,
  aspect      TEXT,
  aspect_deg  REAL,
  slope_deg   REAL,
  route_top_m INTEGER,
  notes       TEXT,
  added_by    INTEGER,
  added_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS site_aliases (
  alias TEXT PRIMARY KEY,
  name  TEXT NOT NULL REFERENCES sites(name) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_prefs (
  user_id                 INTEGER PRIMARY KEY,
  avg_route_speed_kmh     REAL    NOT NULL DEFAULT 25.0,
  wind_correction_enabled INTEGER NOT NULL DEFAULT 1,
  model_key               TEXT    NOT NULL DEFAULT 'auto'
);

CREATE TABLE IF NOT EXISTS routes (
  user_id  INTEGER NOT NULL,
  name     TEXT    NOT NULL,
  points   TEXT    NOT NULL,
  saved_at TEXT    NOT NULL,
  PRIMARY KEY (user_id, name)
);

CREATE TABLE IF NOT EXISTS terrain (
  grid_key   TEXT PRIMARY KEY,
  elevations TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS adhoc_points (
  name        TEXT PRIMARY KEY,
  lat         REAL NOT NULL,
  lon         REAL NOT NULL,
  elevation_m INTEGER NOT NULL,
  created_at  TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    """Соединение на операцию. WAL — потому что в одном процессе живут два
    писателя: хендлеры бота и (позже) HTTP-эндпоинты."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init() -> None:
    """Создать каталог и таблицы. Идемпотентна — зовётся на каждом старте."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/bin/python -m pytest tests/test_store.py -q`
Expected: PASS, 6 тестов

- [ ] **Step 5: Коммит**

```bash
git add store.py tests/test_store.py
git commit -m "feat(store): схема SQLite и подключение"
```

---

### Task 2: `store.py` — старты

**Files:**
- Modify: `store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `store.connect`, `store.init`, `store._now` (задача 1)
- Produces:
  - `store.load_sites() -> list[dict]` — все старты, отсортированы по имени. Каждый словарь имеет ключи `name, aliases, lat, lon, elevation_m, aspect, aspect_deg, slope_deg, route_top_m, notes` — та же форма, что раньше отдавал `engine.load_sites()`, плюс `added_by`
  - `store.find_site(name: str) -> dict | None` — по имени или псевдониму, без учёта регистра. **Возвращает `None`, а не бросает `SystemExit`**
  - `store.add_site(site: dict, added_by: int | None = None) -> None` — `ValueError` при конфликте имени с именем или псевдонимом
  - `store.remove_site(name: str) -> None` — `ValueError`, если не найден

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_store.py`:

```python
SITE = {"name": "Гудаури", "aliases": ["gudauri", "гуда"], "lat": 42.47, "lon": 44.48,
        "elevation_m": 2200, "aspect": "Ю", "aspect_deg": 180.0, "notes": "гребень"}


def test_add_and_load_roundtrip(store):
    store.add_site(SITE, added_by=777)
    got = store.load_sites()
    assert len(got) == 1
    s = got[0]
    assert s["name"] == "Гудаури"
    assert s["lat"] == 42.47 and s["elevation_m"] == 2200
    assert s["aspect_deg"] == 180.0
    # sorted() ставит ASCII перед кириллицей — порядок именно такой
    assert sorted(s["aliases"]) == ["gudauri", "гуда"]
    assert s["added_by"] == 777


def test_load_sites_sorted_by_name(store):
    store.add_site({**SITE, "name": "Яремче", "aliases": []})
    store.add_site({**SITE, "name": "Алушта", "aliases": []})
    assert [s["name"] for s in store.load_sites()] == ["Алушта", "Яремче"]


def test_find_site_by_name_case_insensitive(store):
    store.add_site(SITE)
    assert store.find_site("гудаури")["name"] == "Гудаури"
    assert store.find_site("  ГУДАУРИ  ")["name"] == "Гудаури"


def test_find_site_by_alias(store):
    store.add_site(SITE)
    assert store.find_site("GUDAURI")["name"] == "Гудаури"


def test_find_site_missing_returns_none(store):
    """Раньше engine.find_site бросал SystemExit, и forecast._resolve его ловил.
    Отсутствие записи — обычный результат поиска, а не завершение программы."""
    assert store.find_site("нет такого") is None


def test_add_site_rejects_duplicate_name(store):
    store.add_site(SITE)
    with pytest.raises(ValueError, match="уже есть"):
        store.add_site({**SITE, "aliases": []})


def test_add_site_rejects_name_taken_by_alias(store):
    store.add_site(SITE)
    with pytest.raises(ValueError, match="псевдоним"):
        store.add_site({**SITE, "name": "Гуда", "aliases": []})


def test_add_site_optional_fields_default_to_none(store):
    store.add_site({"name": "X", "lat": 1.0, "lon": 2.0, "elevation_m": 300})
    s = store.find_site("X")
    assert s["aspect_deg"] is None and s["route_top_m"] is None
    assert s["slope_deg"] is None and s["aliases"] == []


def test_remove_site_drops_aliases(store):
    store.add_site(SITE)
    store.remove_site("гудаури")
    assert store.load_sites() == []
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) c FROM site_aliases").fetchone()["c"] == 0


def test_remove_site_missing_raises(store):
    with pytest.raises(ValueError, match="не найден"):
        store.remove_site("Нет")
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_store.py -q`
Expected: FAIL — `AttributeError: module 'store' has no attribute 'add_site'`

- [ ] **Step 3: Реализовать**

Дописать в `store.py`:

```python
# ------------------------------------------------------------------ старты
# Общая библиотека: старт — это факт о местности, а не личное предпочтение.
# Имя остаётся идентичностью: на нём построены ключи кэша прогноза и
# callback_data кнопок.

_SITE_COLUMNS = ("name", "lat", "lon", "elevation_m", "aspect", "aspect_deg",
                 "slope_deg", "route_top_m", "notes", "added_by")


def _site_row_to_dict(row: sqlite3.Row, aliases: list[str]) -> dict:
    out = {k: row[k] for k in _SITE_COLUMNS}
    out["aliases"] = aliases
    return out


def load_sites() -> list[dict]:
    """Все старты, по алфавиту. Форма словаря та же, что отдавал engine.load_sites()."""
    with connect() as conn:
        rows = conn.execute("SELECT * FROM sites ORDER BY name").fetchall()
        by_site: dict[str, list[str]] = {}
        for a in conn.execute("SELECT alias, name FROM site_aliases"):
            by_site.setdefault(a["name"], []).append(a["alias"])
    return [_site_row_to_dict(r, sorted(by_site.get(r["name"], []))) for r in rows]


def find_site(name: str) -> dict | None:
    """Старт по имени или псевдониму, без учёта регистра. None, если не найден."""
    key = name.strip().lower()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM sites WHERE lower(name) = ?", (key,)).fetchone()
        if row is None:
            hit = conn.execute(
                "SELECT name FROM site_aliases WHERE alias = ?", (key,)).fetchone()
            if hit is None:
                return None
            row = conn.execute(
                "SELECT * FROM sites WHERE name = ?", (hit["name"],)).fetchone()
            if row is None:
                return None
        aliases = [a["alias"] for a in conn.execute(
            "SELECT alias FROM site_aliases WHERE name = ?", (row["name"],))]
    return _site_row_to_dict(row, sorted(aliases))


def add_site(site: dict, added_by: int | None = None) -> None:
    """Добавить старт. ValueError, если имя занято именем ИЛИ псевдонимом другого:
    find_site матчит и то и другое, и затенённый старт стал бы недостижим."""
    key = site["name"].strip().lower()
    with connect() as conn:
        if conn.execute("SELECT 1 FROM sites WHERE lower(name) = ?", (key,)).fetchone():
            raise ValueError(f"старт «{site['name']}» уже есть")
        clash = conn.execute(
            "SELECT name FROM site_aliases WHERE alias = ?", (key,)).fetchone()
        if clash:
            raise ValueError(f"имя «{site['name']}» уже занято как псевдоним "
                             f"старта «{clash['name']}»")
        conn.execute(
            "INSERT INTO sites (name, lat, lon, elevation_m, aspect, aspect_deg,"
            " slope_deg, route_top_m, notes, added_by, added_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (site["name"], site["lat"], site["lon"], site["elevation_m"],
             site.get("aspect"), site.get("aspect_deg"), site.get("slope_deg"),
             site.get("route_top_m"), site.get("notes"), added_by, _now()))
        for alias in site.get("aliases") or []:
            a = alias.strip().lower()
            if a and a != key:
                conn.execute("INSERT OR IGNORE INTO site_aliases (alias, name)"
                             " VALUES (?, ?)", (a, site["name"]))


def remove_site(name: str) -> None:
    """Удалить старт по имени. ValueError, если не найден. Псевдонимы уходят каскадом."""
    with connect() as conn:
        row = conn.execute("SELECT name FROM sites WHERE lower(name) = ?",
                           (name.strip().lower(),)).fetchone()
        if row is None:
            raise ValueError(f"старт «{name}» не найден")
        conn.execute("DELETE FROM sites WHERE name = ?", (row["name"],))
```

**Регистр сравнивается в Python, а не в SQL.** Встроенный `lower()` в SQLite
работает только с ASCII: `SELECT lower('ГУДАУРИ')` возвращает `'ГУДАУРИ'` без
изменений. Запросы вида `WHERE lower(name) = ?` на кириллических именах — а они
здесь почти все — молча не находили бы ничего, и проверка на дубли пропускала бы
их. Поэтому строки вычитываются и сравниваются `.lower()` на стороне Python во
всех четырёх местах: поиск по имени и по псевдониму в `find_site`, проверка
имени и проверка псевдонима в `add_site`, поиск в `remove_site`. Комментарий с
этой причиной нужен рядом с каждым — иначе следующий читатель «упростит» обратно
в SQL и тихо вернёт баг.

Цена — полный проход по таблице вместо индексного поиска. При десятках стартов
это неважно; если библиотека вырастет, правильный ход — отдельная колонка с
заранее приведённым к нижнему регистру ключом, а не возврат к `lower()` в SQL.

Примечание для реализующего: `a != key` в `add_site` отбрасывает псевдоним,
совпадающий с собственным именем старта (бот кладёт `aliases: [name.lower()]`).
Иначе `find_site` нашёл бы старт дважды, а `add_site` следующего старта с таким
же именем ругался бы «занято как псевдоним» вместо «уже есть».

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/bin/python -m pytest tests/test_store.py -q`
Expected: PASS, 16 тестов

- [ ] **Step 5: Коммит**

```bash
git add store.py tests/test_store.py
git commit -m "feat(store): старты — общая библиотека с псевдонимами"
```

---

### Task 3: `store.py` — личные настройки

**Files:**
- Modify: `store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `store.connect`, `store.MODELS` не нужен — валидация ключа модели остаётся в `engine`
- Produces:
  - `store.Prefs` — замороженный dataclass с полями `avg_route_speed_kmh: float`, `wind_correction_enabled: bool`, `model_key: str`
  - `store.DEFAULT_PREFS: Prefs`
  - `store.SPEED_MIN = 10.0`, `store.SPEED_MAX = 45.0`
  - `store.prefs(user_id: int) -> Prefs` — дефолты, если записи нет; строку в БД не создаёт
  - `store.set_speed(user_id: int, value: float) -> None` — `ValueError` вне диапазона
  - `store.set_wind_correction(user_id: int, on: bool) -> None`
  - `store.set_model(user_id: int, key: str) -> None`

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_store.py`:

```python
def test_prefs_defaults_for_unknown_user(store):
    p = store.prefs(12345)
    assert p.avg_route_speed_kmh == 25.0
    assert p.wind_correction_enabled is True
    assert p.model_key == "auto"


def test_prefs_read_does_not_create_row(store):
    store.prefs(12345)
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) c FROM user_prefs").fetchone()["c"] == 0


def test_set_speed_roundtrip(store):
    store.set_speed(1, 32.0)
    assert store.prefs(1).avg_route_speed_kmh == 32.0


def test_set_speed_keeps_neighbours(store):
    store.set_model(1, "gfs")
    store.set_speed(1, 30.0)
    p = store.prefs(1)
    assert p.model_key == "gfs" and p.avg_route_speed_kmh == 30.0


@pytest.mark.parametrize("bad", [9.9, 45.1, 0.0, -5.0])
def test_set_speed_rejects_out_of_range(store, bad):
    with pytest.raises(ValueError):
        store.set_speed(1, bad)


def test_set_wind_correction_roundtrip(store):
    store.set_wind_correction(1, False)
    assert store.prefs(1).wind_correction_enabled is False
    store.set_wind_correction(1, True)
    assert store.prefs(1).wind_correction_enabled is True


def test_prefs_are_per_user(store):
    store.set_speed(1, 30.0)
    store.set_speed(2, 40.0)
    assert store.prefs(1).avg_route_speed_kmh == 30.0
    assert store.prefs(2).avg_route_speed_kmh == 40.0
    assert store.prefs(3).avg_route_speed_kmh == 25.0


def test_prefs_is_frozen(store):
    p = store.prefs(1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.model_key = "gfs"
```

В шапку `tests/test_store.py` добавить `import dataclasses`.

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_store.py -q -k prefs or speed or wind`
Expected: FAIL — `AttributeError: module 'store' has no attribute 'prefs'`

- [ ] **Step 3: Реализовать**

Дописать в `store.py`:

```python
# ------------------------------------------------------------ личные настройки
# 25 км/ч — разумный дефолт для уверенного XC-пилота на B+. Реальный разброс:
# 18–22 в слабый день, 25–30 в рабочий, 30–35 у сильных пилотов на коротком маршруте.
SPEED_MIN, SPEED_MAX = 10.0, 45.0


@dataclasses.dataclass(frozen=True)
class Prefs:
    """Личные настройки пользователя.

    Не словарь: обращения к нему расходятся по обоим адаптерам (бот и HTTP),
    и опечатка в имени поля должна падать сразу, а не отдавать None.
    Имена полей совпадают с ключами старого settings.DEFAULTS.
    """
    avg_route_speed_kmh: float = 25.0
    wind_correction_enabled: bool = True
    model_key: str = "auto"


DEFAULT_PREFS = Prefs()


def prefs(user_id: int) -> Prefs:
    """Настройки пользователя; дефолты, если он ещё ничего не менял.

    Строку не создаёт: новый пилот не должен ничего регистрировать, чтобы
    посмотреть прогноз.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT avg_route_speed_kmh, wind_correction_enabled, model_key"
            " FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return DEFAULT_PREFS
    return Prefs(avg_route_speed_kmh=row["avg_route_speed_kmh"],
                 wind_correction_enabled=bool(row["wind_correction_enabled"]),
                 model_key=row["model_key"])


def _set_pref(user_id: int, column: str, value) -> None:
    """UPSERT одного поля. Имя колонки подставляется из литералов вызывающих
    функций — снаружи оно не приходит."""
    with connect() as conn:
        conn.execute(
            f"INSERT INTO user_prefs (user_id, {column}) VALUES (?, ?)"
            f" ON CONFLICT(user_id) DO UPDATE SET {column} = excluded.{column}",
            (user_id, value))


def set_speed(user_id: int, value: float) -> None:
    """Средняя маршрутная скорость в км/ч. ValueError вне допустимого диапазона."""
    value = float(value)
    if not SPEED_MIN <= value <= SPEED_MAX:
        raise ValueError(
            f"средняя маршрутная скорость должна быть от {SPEED_MIN:.0f} "
            f"до {SPEED_MAX:.0f} км/ч. Это средняя по маршруту с учётом наборов "
            "в термиках, а не скорость крыла.")
    _set_pref(user_id, "avg_route_speed_kmh", value)


def set_wind_correction(user_id: int, on: bool) -> None:
    _set_pref(user_id, "wind_correction_enabled", 1 if on else 0)


def set_model(user_id: int, key: str) -> None:
    """Постоянная модель пользователя. Ключ валидирует вызывающий (engine.MODELS):
    список моделей — знание домена, а не хранилища."""
    _set_pref(user_id, "model_key", key)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/bin/python -m pytest tests/test_store.py -q`
Expected: PASS, 27 тестов

- [ ] **Step 5: Коммит**

```bash
git add store.py tests/test_store.py
git commit -m "feat(store): личные настройки маршрута и модели"
```

---

### Task 4: `store.py` — личные маршруты и `route.points_from_rows`

**Files:**
- Modify: `store.py`, `route.py`
- Test: `tests/test_store.py`, `tests/test_routes_store.py`

**Interfaces:**
- Consumes: `store.connect`, `store._now`
- Produces:
  - `store.MAX_ROUTES = 20`
  - `store.routes_list(user_id: int) -> dict[str, dict]` — `{имя: {"points": [[lat, lon, name], ...], "saved": "ISO"}}`
  - `store.route_rows(user_id: int, name: str) -> list | None` — сырые строки точек
  - `store.route_save(user_id: int, name: str, rows: list) -> None` — `ValueError` при переполнении
  - `store.route_delete(user_id: int, name: str) -> bool`
  - `route.points_from_rows(rows) -> list[Point] | None` — сборка `Point` из сырых строк; `None`, если запись битая или точек меньше `MIN_POINTS`

Разбор сырых строк живёт в `route.py`, а не в `store.py`: `Point` определён там,
а `store` по правилу из «Global Constraints» не импортирует модули проекта.

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_store.py`:

```python
PTS = [[42.4, 44.4, "старт"], [42.2, 44.6, "финиш"]]


def test_route_save_and_list(store):
    store.route_save(1, "Гудаури → Пасанаури", PTS)
    got = store.routes_list(1)
    assert list(got) == ["Гудаури → Пасанаури"]
    assert got["Гудаури → Пасанаури"]["points"] == PTS
    assert got["Гудаури → Пасанаури"]["saved"]


def test_routes_are_per_user(store):
    store.route_save(1, "Мой", PTS)
    assert store.routes_list(2) == {}
    assert store.route_rows(2, "Мой") is None


def test_route_save_overwrites_same_name(store):
    store.route_save(1, "Мой", PTS)
    store.route_save(1, "Мой", [[1.0, 2.0, None], [3.0, 4.0, None]])
    assert store.route_rows(1, "Мой") == [[1.0, 2.0, None], [3.0, 4.0, None]]
    assert len(store.routes_list(1)) == 1


def test_route_save_rejects_overflow(store):
    for i in range(store.MAX_ROUTES):
        store.route_save(1, f"м{i}", PTS)
    with pytest.raises(ValueError, match="удали"):
        store.route_save(1, "лишний", PTS)


def test_route_save_overflow_allows_overwrite(store):
    """Переполнение не должно мешать перезаписать уже существующий маршрут."""
    for i in range(store.MAX_ROUTES):
        store.route_save(1, f"м{i}", PTS)
    store.route_save(1, "м0", PTS)   # не бросает


def test_route_delete(store):
    store.route_save(1, "Мой", PTS)
    assert store.route_delete(1, "Мой") is True
    assert store.route_delete(1, "Мой") is False


def test_route_rows_missing_returns_none(store):
    assert store.route_rows(1, "нет") is None
```

Дописать в `tests/test_routes_store.py` (файл остаётся, меняется предмет тестирования):

```python
def test_points_from_rows_builds_points():
    import route
    pts = route.points_from_rows([[42.4, 44.4, "старт"], [42.2, 44.6, None]])
    assert [p.lat for p in pts] == [42.4, 42.2]
    assert pts[0].name == "старт" and pts[1].name is None


def test_points_from_rows_rejects_corrupt():
    """Битая запись читается как None, а не роняет бота."""
    import route
    assert route.points_from_rows([["нет", 44.4, None], [42.2, 44.6, None]]) is None
    assert route.points_from_rows([[42.4], [42.2, 44.6, None]]) is None


def test_points_from_rows_rejects_too_few():
    import route
    assert route.points_from_rows([[42.4, 44.4, None]]) is None
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_store.py tests/test_routes_store.py -q`
Expected: FAIL — `AttributeError: module 'store' has no attribute 'route_save'`

- [ ] **Step 3: Реализовать**

Дописать в `store.py`:

```python
# ------------------------------------------------------------ личные маршруты
# Хранится ТОЛЬКО геометрия. Погода всегда считается заново, поэтому устаревать
# здесь нечему: сохранённый маршрут — это набор координат, а не прогноз.
# Точки лежат JSON-строкой намеренно: запросов по отдельной точке нет,
# отдельная таблица была бы схемой ради схемы.
MAX_ROUTES = 20


def routes_list(user_id: int) -> dict[str, dict]:
    """Все маршруты пользователя. Битые записи пропускаются, а не роняют выдачу."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT name, points, saved_at FROM routes WHERE user_id = ? ORDER BY name",
            (user_id,)).fetchall()
    out = {}
    for r in rows:
        try:
            pts = json.loads(r["points"])
        except ValueError:
            continue
        if isinstance(pts, list):
            out[r["name"]] = {"points": pts, "saved": r["saved_at"]}
    return out


def route_rows(user_id: int, name: str) -> list | None:
    """Сырые строки точек: [[lat, lon, name], ...]. None, если нет или битая."""
    with connect() as conn:
        row = conn.execute(
            "SELECT points FROM routes WHERE user_id = ? AND name = ?",
            (user_id, name)).fetchone()
    if row is None:
        return None
    try:
        pts = json.loads(row["points"])
    except ValueError:
        return None
    return pts if isinstance(pts, list) else None


def route_save(user_id: int, name: str, rows: list) -> None:
    """Сохранить точки под именем. ValueError при переполнении.

    Перезапись существующего имени переполнением не считается — иначе на
    заполненном списке нельзя было бы поправить уже сохранённый маршрут.
    """
    with connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM routes WHERE user_id = ? AND name = ?",
            (user_id, name)).fetchone()
        if not exists:
            n = conn.execute("SELECT count(*) c FROM routes WHERE user_id = ?",
                             (user_id,)).fetchone()["c"]
            if n >= MAX_ROUTES:
                raise ValueError(f"сохранено уже {MAX_ROUTES} маршрутов — "
                                 "удали ненужный через /delroute")
        conn.execute(
            "INSERT INTO routes (user_id, name, points, saved_at) VALUES (?,?,?,?)"
            " ON CONFLICT(user_id, name) DO UPDATE SET"
            " points = excluded.points, saved_at = excluded.saved_at",
            (user_id, name, json.dumps(rows, ensure_ascii=False), _now()))


def route_delete(user_id: int, name: str) -> bool:
    """True, если удалили; False, если такого маршрута не было."""
    with connect() as conn:
        cur = conn.execute("DELETE FROM routes WHERE user_id = ? AND name = ?",
                           (user_id, name))
        return cur.rowcount > 0
```

Дописать в `route.py` рядом с классом `Point`:

```python
def points_from_rows(rows):
    """Точки из сырых строк хранилища: [[lat, lon, name], ...] → [Point].

    None при битой записи или нехватке точек — маршрут, который нельзя
    посчитать, лучше показать как отсутствующий, чем уронить бота.
    """
    out = []
    for item in rows or []:
        try:
            lat, lon = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError, KeyError):
            return None
        out.append(Point(lat, lon, item[2] if len(item) > 2 else None))
    return out if len(out) >= MIN_POINTS else None
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/bin/python -m pytest tests/test_store.py tests/test_routes_store.py -q`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add store.py route.py tests/test_store.py tests/test_routes_store.py
git commit -m "feat(store): личные маршруты; разбор точек переезжает в route"
```

---

### Task 5: `store.py` — рельеф, точки по координатам, уборка

**Files:**
- Modify: `store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `store.connect`, `store._now`
- Produces:
  - `store.terrain_get(grid_key: str) -> list | None`
  - `store.terrain_put(grid_key: str, elevations: list) -> None`
  - `store.adhoc_put(lat: float, lon: float, elevation_m: int) -> str` — возвращает имя `"42.0893, 45.4012"`
  - `store.adhoc_get(name: str) -> dict | None` — словарь той же формы, что старты (`aspect`/`aspect_deg` = `None`)
  - `store.purge_adhoc(older_than_days: int = 30) -> int` — сколько удалено

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_store.py`:

```python
def test_terrain_roundtrip(store):
    store.terrain_put("k1", [100, 200, 300])
    assert store.terrain_get("k1") == [100, 200, 300]


def test_terrain_missing_returns_none(store):
    assert store.terrain_get("нет") is None


def test_terrain_put_overwrites(store):
    store.terrain_put("k1", [1])
    store.terrain_put("k1", [2, 3])
    assert store.terrain_get("k1") == [2, 3]


def test_adhoc_roundtrip_and_name_format(store):
    name = store.adhoc_put(42.089329, 45.401151, 686)
    assert name == "42.0893, 45.4012"
    got = store.adhoc_get(name)
    assert got["name"] == name and got["elevation_m"] == 686
    assert got["aspect"] is None and got["aspect_deg"] is None
    assert got["aliases"] == []


def test_adhoc_survives_new_connection(store):
    """Раньше ad-hoc точки жили в памяти процесса и умирали при рестарте."""
    name = store.adhoc_put(1.0, 2.0, 300)
    assert store.adhoc_get(name) is not None


def test_adhoc_missing_returns_none(store):
    assert store.adhoc_get("42.0000, 45.0000") is None


def test_purge_adhoc_removes_old_keeps_fresh(store):
    fresh = store.adhoc_put(1.0, 2.0, 300)
    old = store.adhoc_put(3.0, 4.0, 400)
    with store.connect() as conn:
        conn.execute("UPDATE adhoc_points SET created_at = ? WHERE name = ?",
                     ("2020-01-01T00:00:00+00:00", old))
    assert store.purge_adhoc(older_than_days=30) == 1
    assert store.adhoc_get(old) is None
    assert store.adhoc_get(fresh) is not None
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_store.py -q -k "terrain or adhoc"`
Expected: FAIL — `AttributeError: module 'store' has no attribute 'terrain_put'`

- [ ] **Step 3: Реализовать**

Дописать в `store.py`:

```python
# ------------------------------------------------- рельеф и точки по координатам
# Рельеф не меняется никогда, но стоит отдельного запроса к Elevation API.
# До переезда в БД он жил в словаре процесса и терялся при каждом рестарте.


def terrain_get(grid_key: str) -> list | None:
    with connect() as conn:
        row = conn.execute("SELECT elevations FROM terrain WHERE grid_key = ?",
                           (grid_key,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["elevations"])
    except ValueError:
        return None


def terrain_put(grid_key: str, elevations: list) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO terrain (grid_key, elevations, fetched_at) VALUES (?,?,?)"
            " ON CONFLICT(grid_key) DO UPDATE SET"
            " elevations = excluded.elevations, fetched_at = excluded.fetched_at",
            (grid_key, json.dumps(elevations), _now()))


def adhoc_name(lat: float, lon: float) -> str:
    """Имя точки по координатам. Оно же ключ: координаты уникальны глобально,
    поэтому таблица общая, а не по пользователям."""
    return f"{lat:.4f}, {lon:.4f}"


def adhoc_put(lat: float, lon: float, elevation_m: int) -> str:
    name = adhoc_name(lat, lon)
    with connect() as conn:
        conn.execute(
            "INSERT INTO adhoc_points (name, lat, lon, elevation_m, created_at)"
            " VALUES (?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET"
            " elevation_m = excluded.elevation_m, created_at = excluded.created_at",
            (name, lat, lon, elevation_m, _now()))
    return name


def adhoc_get(name: str) -> dict | None:
    """Точка в форме словаря старта. Экспозиция неизвестна, поэтому вердикт по
    направлению ветра для неё пропускается — так же, как было в памяти."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM adhoc_points WHERE name = ?",
                           (name,)).fetchone()
    if row is None:
        return None
    return {"name": row["name"], "aliases": [], "lat": row["lat"], "lon": row["lon"],
            "elevation_m": row["elevation_m"], "aspect": None, "aspect_deg": None,
            "slope_deg": None, "route_top_m": None, "notes": "", "added_by": None}


def purge_adhoc(older_than_days: int = 30) -> int:
    """Убрать старые точки по координатам. Возвращает число удалённых."""
    cutoff = (dt.datetime.now(dt.timezone.utc)
              - dt.timedelta(days=older_than_days)).isoformat(timespec="seconds")
    with connect() as conn:
        cur = conn.execute("DELETE FROM adhoc_points WHERE created_at < ?", (cutoff,))
        return cur.rowcount
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/bin/python -m pytest tests/test_store.py -q`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add store.py tests/test_store.py
git commit -m "feat(store): рельеф и точки по координатам переживают рестарт"
```

---

### Task 6: `store.py` — миграция из JSON

**Files:**
- Modify: `store.py`
- Test: `tests/test_store_migration.py`

**Interfaces:**
- Consumes: `store.add_site`, `store.route_save`, `store._set_pref`, `store.init`
- Produces:
  - `store.migrate_from_json(data_dir: str, allowed_user_ids) -> dict` — отчёт `{"sites": int, "routes": int, "users": int, "skipped": list[str]}`
  - `store.bootstrap(data_dir: str, allowed_user_ids, packaged_sites: str) -> dict` — `init()` + миграция при пустой БД + засев из упакованного `sites.json`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_store_migration.py`:

```python
"""Миграция JSON-файлов в SQLite. Один раз, при первом старте на новой схеме."""
import importlib
import json
import os

import pytest


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    import store as st
    importlib.reload(st)
    return st


@pytest.fixture()
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return str(d)


def write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


SITES_JSON = {"_comment": "игнорируется", "sites": [
    {"name": "Лалискури", "aliases": ["laliskuri", "лалискури"], "lat": 42.089329,
     "lon": 45.401151, "elevation_m": 686, "aspect": "S", "aspect_deg": 180,
     "notes": "южная экспозиция"}]}


def test_migrates_sites_with_aliases(store, data_dir):
    write(os.path.join(data_dir, "sites.json"), SITES_JSON)
    store.init()
    report = store.migrate_from_json(data_dir, frozenset())
    assert report["sites"] == 1
    s = store.find_site("laliskuri")
    assert s["name"] == "Лалискури" and s["elevation_m"] == 686
    assert s["aspect_deg"] == 180


def test_comment_key_ignored(store, data_dir):
    write(os.path.join(data_dir, "sites.json"), SITES_JSON)
    store.init()
    store.migrate_from_json(data_dir, frozenset())
    assert [s["name"] for s in store.load_sites()] == ["Лалискури"]


def test_renames_migrated_files(store, data_dir):
    p = os.path.join(data_dir, "sites.json")
    write(p, SITES_JSON)
    store.init()
    store.migrate_from_json(data_dir, frozenset())
    assert not os.path.exists(p)
    assert os.path.exists(p + ".migrated")


def test_routes_copied_to_every_allowed_user(store, data_dir):
    write(os.path.join(data_dir, "routes.json"),
          {"Гудаури → Пасанаури": {"points": [[42.4, 44.4, None], [42.2, 44.6, None]],
                                   "saved": "2026-07-24"}})
    store.init()
    report = store.migrate_from_json(data_dir, frozenset({111, 222}))
    assert report["routes"] == 2
    assert list(store.routes_list(111)) == ["Гудаури → Пасанаури"]
    assert list(store.routes_list(222)) == ["Гудаури → Пасанаури"]


def test_routes_kept_when_no_allowlist(store, data_dir):
    """В открытом режиме раздавать общие маршруты некому — файл остаётся на месте."""
    p = os.path.join(data_dir, "routes.json")
    write(p, {"Мой": {"points": [[1.0, 2.0, None], [3.0, 4.0, None]]}})
    store.init()
    report = store.migrate_from_json(data_dir, frozenset())
    assert report["routes"] == 0
    assert "routes.json" in report["skipped"]
    assert os.path.exists(p)               # не переименован — миграцию можно повторить


def test_settings_and_model_become_user_defaults(store, data_dir):
    write(os.path.join(data_dir, "settings.json"),
          {"avg_route_speed_kmh": 32.0, "wind_correction_enabled": False})
    write(os.path.join(data_dir, "model.json"), {"model": "gfs"})
    store.init()
    store.migrate_from_json(data_dir, frozenset({111}))
    p = store.prefs(111)
    assert p.avg_route_speed_kmh == 32.0
    assert p.wind_correction_enabled is False
    assert p.model_key == "gfs"


def test_migration_is_not_repeated_on_second_run(store, data_dir):
    write(os.path.join(data_dir, "sites.json"), SITES_JSON)
    store.init()
    store.migrate_from_json(data_dir, frozenset())
    second = store.migrate_from_json(data_dir, frozenset())
    assert second["sites"] == 0
    assert len(store.load_sites()) == 1


def test_corrupt_file_does_not_abort_migration(store, data_dir):
    with open(os.path.join(data_dir, "sites.json"), "w", encoding="utf-8") as f:
        f.write("{не json")
    write(os.path.join(data_dir, "model.json"), {"model": "icon"})
    store.init()
    report = store.migrate_from_json(data_dir, frozenset({111}))
    assert "sites.json" in report["skipped"]
    assert store.prefs(111).model_key == "icon"


def test_bootstrap_seeds_from_packaged_sites_when_empty(store, data_dir, tmp_path):
    packaged = tmp_path / "packaged.json"
    write(str(packaged), SITES_JSON)
    report = store.bootstrap(data_dir, frozenset(), str(packaged))
    assert report["sites"] == 1
    assert store.find_site("Лалискури") is not None


def test_bootstrap_does_not_seed_when_sites_exist(store, data_dir, tmp_path):
    packaged = tmp_path / "packaged.json"
    write(str(packaged), SITES_JSON)
    store.init()
    store.add_site({"name": "Свой", "lat": 1.0, "lon": 2.0, "elevation_m": 10})
    report = store.bootstrap(data_dir, frozenset(), str(packaged))
    assert report["sites"] == 0
    assert [s["name"] for s in store.load_sites()] == ["Свой"]
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_store_migration.py -q`
Expected: FAIL — `AttributeError: module 'store' has no attribute 'migrate_from_json'`

- [ ] **Step 3: Реализовать**

Дописать в `store.py`:

```python
# ------------------------------------------------------------------ миграция
# Разовый перенос с JSON-файлов. Файлы не удаляются, а переименовываются в
# *.migrated: откат — вернуть имена и откатить образ.

def _read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _mark_migrated(path: str) -> None:
    os.replace(path, path + ".migrated")


def migrate_from_json(data_dir: str, allowed_user_ids) -> dict:
    """Перенести sites/routes/settings/model из JSON в БД.

    allowed_user_ids — кому раздать бывшие общими маршруты. В открытом режиме
    (список пуст) раздавать некому: маршруты пропускаются, файл остаётся, и
    миграцию можно повторить, когда список появится.
    """
    report = {"sites": 0, "routes": 0, "users": 0, "skipped": []}

    sites_path = os.path.join(data_dir, "sites.json")
    if os.path.exists(sites_path):
        try:
            raw = _read_json(sites_path)
            for s in raw.get("sites", []):
                # не-словарь в списке — битая запись; add_site(None) уронил бы
                # TypeError'ом всю миграцию, и остальные файлы не переехали бы
                if not isinstance(s, dict):
                    continue
                try:
                    add_site(s)
                    report["sites"] += 1
                except (ValueError, TypeError, KeyError):
                    pass          # уже перенесён или битый — одна запись, не вся миграция
            _mark_migrated(sites_path)
        except (OSError, ValueError, AttributeError):
            report["skipped"].append("sites.json")

    routes_path = os.path.join(data_dir, "routes.json")
    if os.path.exists(routes_path):
        if not allowed_user_ids:
            report["skipped"].append("routes.json")
        else:
            try:
                raw = _read_json(routes_path)
                for name, entry in (raw or {}).items():
                    pts = (entry or {}).get("points")
                    if not isinstance(pts, list):
                        continue
                    for uid in allowed_user_ids:
                        route_save(uid, name, pts)
                        report["routes"] += 1
                _mark_migrated(routes_path)
            except (OSError, ValueError, AttributeError):
                report["skipped"].append("routes.json")

    # settings и model раздаются тем же, кому маршруты. Пустой список — значит
    # раздавать некому: файл НЕ переименовываем, иначе значения пропадут
    # безвозвратно и повторить миграцию будет уже не с чего.
    defaults = {}
    settings_path = os.path.join(data_dir, "settings.json")
    if os.path.exists(settings_path) and not allowed_user_ids:
        report["skipped"].append("settings.json")
    elif os.path.exists(settings_path):
        try:
            raw = _read_json(settings_path)
            if isinstance(raw, dict):
                for k in ("avg_route_speed_kmh", "wind_correction_enabled"):
                    if k in raw:
                        defaults[k] = raw[k]
            _mark_migrated(settings_path)
        except (OSError, ValueError):
            report["skipped"].append("settings.json")

    model_path = os.path.join(data_dir, "model.json")
    if os.path.exists(model_path) and not allowed_user_ids:
        report["skipped"].append("model.json")
    elif os.path.exists(model_path):
        try:
            raw = _read_json(model_path)
            if isinstance(raw, dict) and raw.get("model"):
                defaults["model_key"] = raw["model"]
            _mark_migrated(model_path)
        except (OSError, ValueError):
            report["skipped"].append("model.json")

    if defaults:
        for uid in allowed_user_ids:
            for column, value in defaults.items():
                if column == "wind_correction_enabled":
                    value = 1 if value else 0
                _set_pref(uid, column, value)
            report["users"] += 1

    return report


def bootstrap(data_dir: str, allowed_user_ids, packaged_sites: str) -> dict:
    """Полная подготовка хранилища на старте: схема, миграция, засев.

    Засев из упакованного sites.json срабатывает только на пустой библиотеке —
    иначе удалённый старт возвращался бы после каждого рестарта.
    """
    init()
    report = migrate_from_json(data_dir, allowed_user_ids)
    if not load_sites() and os.path.exists(packaged_sites):
        try:
            for s in _read_json(packaged_sites).get("sites", []):
                if not isinstance(s, dict):
                    continue
                try:
                    add_site(s)
                    report["sites"] += 1
                except (ValueError, TypeError, KeyError):
                    pass
        except (OSError, ValueError, AttributeError):
            report["skipped"].append(os.path.basename(packaged_sites))
    purge_adhoc()
    return report
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/bin/python -m pytest tests/test_store_migration.py -q`
Expected: PASS, 10 тестов

- [ ] **Step 5: Коммит**

```bash
git add store.py tests/test_store_migration.py
git commit -m "feat(store): миграция с JSON-файлов и засев библиотеки стартов"
```

---

### Task 7: переезд на `store` — харнесс, домен и бот одним коммитом

Промежуточного зелёного состояния между харнессом, доменом и ботом не
существует: все трое читают хранилище и должны переключиться разом. Поэтому
одна задача и один коммит — красных коммитов в ветке не будет.

Задача крупная, но правка механическая: перенос вызовов на уже готовый и
оттестированный `store` из задач 1–6.

#### 7a. Харнесс тестов

**Files:**
- Modify: `tests/conftest.py:1-60`, `tests/conftest.py:75-110`
- Modify: `tests/test_settings.py` (переписывается целиком)

**Interfaces:**
- Consumes: весь `store` из задач 1–6
- Produces:
  - `conftest.write_sites(sites: list[dict])` — тот же контракт, что раньше, но пишет в БД
  - фикстура `fresh_state` пересоздаёт БД перед каждым тестом
  - `tests/test_settings.py` удаляется, его 7 тестов уже покрыты `test_store.py`

На этом подшаге ломается всё, что зовёт `engine.load_sites` — чинят подшаги 7b и
7c. Коммита между ними нет, поэтому в ветку красное состояние не попадает.

- [ ] **Step 1: Переписать `conftest.py`**

Заменить блок с 15-й по 60-ю строку (создание временного `sites.json`) на:

```python
_tmpdir = tempfile.mkdtemp(prefix="pgbot_tests_")
DB_PATH = os.path.join(_tmpdir, "test.db")

# Env must be set before importing bot/engine/store (they read it at import time).
os.environ["DB_PATH"] = DB_PATH
os.environ["BOT_TOKEN"] = "42:TEST"
os.environ["ALLOWED_USER_IDS"] = ""  # open mode — whitelist passes everyone
os.environ["COOLDOWN_SEC"] = "0"
os.environ["GEMINI_API_KEY"] = ""

DEFAULT_SITES = [
    {"name": "Гудаури", "aliases": ["gudauri", "гуда"], "lat": 42.47, "lon": 44.48,
     "elevation_m": 2200, "aspect": "Ю", "aspect_deg": 180.0, "notes": ""},
    {"name": "Лалискури", "aliases": ["laliskuri"], "lat": 42.1, "lon": 45.3,
     "elevation_m": 900, "aspect": "ЮЗ", "aspect_deg": 225.0, "notes": ""},
]

import pytest  # noqa: E402
from aiogram import Bot  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402

import bot as botmod  # noqa: E402
import engine  # noqa: E402
import forecast  # noqa: E402
import store  # noqa: E402

TEST_USER_ID = 4242  # id, который подставляют tests/tg.py в сообщениях и колбэках
```

Заменить `write_sites` и `fresh_state`:

```python
def write_sites(sites: list[dict]):
    """Заменить библиотеку стартов ровно на переданный список."""
    with store.connect() as conn:
        conn.execute("DELETE FROM sites")
    for s in sites:
        store.add_site(s)


@pytest.fixture(autouse=True)
def fresh_state():
    """Чистая БД, пустые кэши, пустой FSM — перед каждым тестом."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    for suffix in ("-wal", "-shm"):
        if os.path.exists(DB_PATH + suffix):
            os.remove(DB_PATH + suffix)
    store.init()
    write_sites(DEFAULT_SITES)
    forecast._fcache.clear()
    forecast._acache.clear()
    forecast._rcache.clear()
    botmod.dp.fsm.storage.storage.clear()  # MemoryStorage internals
    botmod._route_cache.clear()            # токены маршрутов под кнопками
    yield
```

Из `fresh_state` уходят `forecast._adhoc.clear()` и `forecast._terrain_cache.clear()`
(эти словари удаляются в задаче 8), а также удаление `MODEL_FILE`, `SETTINGS_FILE`,
`ROUTES_FILE`. Импорты `routes` и `settings` из шапки убрать.

- [ ] **Step 2: Удалить `tests/test_settings.py`**

```bash
git rm tests/test_settings.py
```

Все 7 его проверок уже есть в `tests/test_store.py` (дефолты, диапазон скорости,
сохранение соседнего поля, порча файла → дефолты заменена на «нет строки → дефолты»).


#### 7b. `engine` и `forecast` перестают трогать диск

**Files:**
- Modify: `engine.py:29-37`, `engine.py:80-107`, `engine.py:136-206`, `engine.py:1131`
- Modify: `forecast.py:56`, `forecast.py:71`, `forecast.py:162-186`, `forecast.py:360-404`, `forecast.py:684`
- Test: `tests/test_store.py` (уже написаны), существующие доменные тесты

**Interfaces:**
- Consumes: `store.load_sites`, `store.find_site`, `store.add_site`, `store.remove_site`, `store.adhoc_put`, `store.adhoc_get`, `store.terrain_get`, `store.terrain_put`
- Produces: `engine` без файловых операций. Удаляются `engine.SITES`, `engine.DEFAULT_SITES`, `engine.MODEL_FILE`, `engine.load_sites`, `engine.find_site`, `engine._load_raw`, `engine.add_site`, `engine.remove_site`, `engine.ensure_sites_file`, `engine.get_model_key`, `engine.set_model_key`. Остаются `engine.MODELS`, `engine.DEFAULT_MODEL_KEY`, `engine.model_id`, `engine.model_label`, `engine.model_code`, `engine.model_for_code`, `engine.parse_aspect`

`parse_aspect` остаётся в `engine`: это разбор пользовательского ввода в градусы,
а не доступ к данным.

- [ ] **Step 1: Убрать хранилище из `engine.py`**

Удалить строки 29–31 (`DEFAULT_SITES`, `SITES`), строку 36 (`MODEL_FILE`),
функции `get_model_key`, `set_model_key`, `ensure_sites_file`, `load_sites`,
`find_site`, `_load_raw`, `add_site`, `remove_site`. Удалить импорт `shutil`,
если он больше не используется.

В `build_url` (строка ~221), `ceiling_url` (~240), `route_weather_url` (~229) и
`_model_note` (~406) пока оставить `model` как есть — обязательным он становится
в задаче 10. На этом шаге заменить только `or get_model_key()` на
`or DEFAULT_MODEL_KEY`, чтобы модуль импортировался.

В `engine.main()` (строка 1131) заменить:

```python
    site = find_site(a.site)
```

на:

```python
    import store
    site = store.find_site(a.site)
    if site is None:
        raise SystemExit(f"Старт не найден: {a.site}. Есть: "
                         + ", ".join(s["name"] for s in store.load_sites()))
```

- [ ] **Step 2: Перевести `forecast.py` на `store`**

Добавить `import store` в шапку. Затем:

`known_sites()` (строка 56):

```python
def known_sites():
    return [s["name"] for s in store.load_sites()]
```

`scan_week` (строка 71): `sites = engine.load_sites()` → `sites = store.load_sites()`

`_nearest_site` вызывающий (строка 684): `engine.load_sites()` → `store.load_sites()`

`register_adhoc` (строка 162) и `_resolve` (строка 170) — целиком:

```python
def register_adhoc(lat: float, lon: float, elev: int) -> str:
    """Зарегистрировать точку по координатам и вернуть её имя для поиска."""
    return store.adhoc_put(lat, lon, elev)


def _resolve(site_name: str, rng: str, date: str | None, model: str | None = None):
    if rng not in engine.RANGE_DAYS:
        raise ForecastError(f"Неизвестный диапазон: {rng}")
    site = store.find_site(site_name) or store.adhoc_get(site_name)
    if site is None:
        raise ForecastError(f"Старт не найден: {site_name}. /sites — список.")
    if rng == "1d" and not date:
        date = dt.date.today().isoformat()
    return site, date, (site["name"], rng, date, model or engine.DEFAULT_MODEL_KEY)
```

Удалить модульный словарь `_adhoc` и регулярку `_ADHOC_NAME_RE` вместе с веткой
«точка больше не в памяти»: точки теперь переживают рестарт, и объяснять
пользователю нечего.

Заменить кэш рельефа на хранилище — `_ensure_terrain` (строка 392):

```python
async def _ensure_terrain(grid):
    """Высоты сетки: из хранилища, иначе запрос к Elevation API.

    Рельеф не меняется, поэтому срока годности у записи нет.
    """
    key = json.dumps(_route_key(grid), separators=(",", ":"))
    cached = store.terrain_get(key)
    if cached is not None:
        return cached
    elev = await fetch_terrain(grid)
    if elev is not None:
        store.terrain_put(key, elev)
    return elev
```

Добавить `import json` в шапку `forecast.py`, если его там нет. Удалить
`_terrain_cache` и `_TERRAIN_CACHE_MAX`, убрать `_terrain_cache` из `_purge`.


#### 7c. `bot` переходит на личные настройки

**Files:**
- Modify: `bot.py:296-302`, `bot.py:340-350`, `bot.py:395-420`, `bot.py:473-533`, `bot.py:534-560`, `bot.py:656-670`, `bot.py:960-1045`, `bot.py:1163-1178`
- Delete: `settings.py`, `routes.py`
- Modify: `tests/test_settings_dialog.py`, `tests/test_route_saved_dialog.py`, `tests/test_dialogs.py`
- Test: существующие диалоговые тесты

**Interfaces:**
- Consumes: `store.prefs`, `store.set_speed`, `store.set_wind_correction`, `store.set_model`, `store.routes_list`, `store.route_rows`, `store.route_save`, `store.route_delete`, `store.add_site`, `store.remove_site`, `route.points_from_rows`
- Produces: `bot.py`, где каждый хендлер берёт `user_id` из события. Публичных функций не добавляет.

- [ ] **Step 1: Заменить импорты и точку входа**

В шапке `bot.py` убрать `import routes` и `import settings`, добавить `import store`.

В `main()` заменить `engine.ensure_sites_file()` на:

```python
    data_dir = os.path.dirname(store.DB_PATH) or "."
    report = store.bootstrap(data_dir, guards._allowed_ids(),
                             os.path.join(os.path.dirname(os.path.abspath(engine.__file__)),
                                          "sites.json"))
    log.info("store: %s", report)
```

- [ ] **Step 2: Перевести хендлеры на `store`**

Точечные замены. Везде `uid = message.from_user.id` или `uid = cb.from_user.id`.

`_model_switch_caption` (строка 296) принимает вторым аргументом постоянную модель
пользователя вместо чтения глобальной:

```python
def _model_switch_caption(model: str | None, permanent: str) -> str:
    if model is None:
        return "🌐 Другая модель (разово):"
    return (f"🌐 Модель: {engine.model_label(model)} — разово. "
            f"Постоянная: {engine.model_label(permanent)} (/model)")
```

`send_forecast` (строка 303) получает `model` от вызывающего, а строка 345
(`eff = model or engine.get_model_key()`) заменяется на `eff = model or prefs.model_key`,
где `prefs` приходит параметром.

`cmd_model` (395) и `cb_pick_model` (419): `engine.get_model_key()` →
`store.prefs(uid).model_key`, `engine.set_model_key(key)` → `store.set_model(uid, key)`.

`_settings_text` (473) и `_settings_keyboard` (481) принимают `cfg: store.Prefs`
и обращаются к нему атрибутами: `cfg.wind_correction_enabled`,
`cfg.avg_route_speed_kmh`.

`cb_set_speed` (496), `cb_toggle_wind` (512), `settings_speed_value` (521):
`settings.set_*(…)` → `store.set_*(uid, …)`.

`_finish_add` (534): `engine.add_site(site)` → `store.add_site(site, added_by=message.from_user.id)`.

`cmd_removesite` (656): `engine.remove_site(name)` → `store.remove_site(name)`.

Маршруты (960–1045, 1163–1178): `routes.get(name)` → `route.points_from_rows(store.route_rows(uid, name))`,
`routes.list_all()` → `store.routes_list(uid)`, `routes.save(name, pts)` →
`store.route_save(uid, name, [[p.lat, p.lon, p.name] for p in pts])`,
`routes.delete(name)` → `store.route_delete(uid, name)`.

Проверку длины маршрута, которая была в `routes.save`, перенести в `cmd_saveroute`
перед вызовом:

```python
    if len(pts) > route.MAX_POINTS:
        await message.answer(f"⚠️ слишком много точек: {len(pts)}, "
                             f"максимум {route.MAX_POINTS}")
        return
```

- [ ] **Step 3: Удалить `settings.py` и `routes.py`**

```bash
git rm settings.py routes.py
```

- [ ] **Step 4: Поправить диалоговые тесты**

В `tests/test_settings_dialog.py`, `tests/test_route_saved_dialog.py` и
`tests/test_dialogs.py` заменить обращения к удалённым модулям на `store` с
`conftest.TEST_USER_ID`. Например:

```python
# было
assert settings.get()["avg_route_speed_kmh"] == 30.0
# стало
assert store.prefs(TEST_USER_ID).avg_route_speed_kmh == 30.0
```

```python
# было
assert engine.get_model_key() == "gfs"
# стало
assert store.prefs(TEST_USER_ID).model_key == "gfs"
```

Проверить, что `tests/tg.py` подставляет в `from_user` тот же id, что
`conftest.TEST_USER_ID`; если там другое значение — привести `TEST_USER_ID` к нему,
а не наоборот (правка одного места вместо всех фабрик событий).

- [ ] **Step 5: Прогнать весь набор**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -5`
Expected: PASS. Ожидаемое число — 606 минус 7 удалённых из `test_settings.py`,
плюс новые из `test_store.py` (27), `test_store_migration.py` (11) и трёх
добавленных в `test_routes_store.py` — итого около 640.

- [ ] **Step 6: Коммит**

```bash
git add bot.py tests/
git rm settings.py routes.py
git commit -m "feat(bot): личные настройки, маршруты и модель у каждого пилота

settings.py и routes.py удалены — их роль забрал store."
```

#### 7d. Проверка и коммит

- [ ] **Финальный шаг: прогнать весь набор и закоммитить**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -5`
Expected: PASS. Ожидаемое число — 606 минус 7 удалённых из `test_settings.py`,
плюс новые из `test_store.py` (27), `test_store_migration.py` (11) и трёх
добавленных в `test_routes_store.py` — итого около 640.

Красным этот прогон быть не может: если он красный, задача не закончена.

```bash
git add store.py engine.py forecast.py route.py bot.py tests/
git rm settings.py routes.py
git commit -m "feat: хранилище переезжает в store, настройки становятся личными

conftest, engine, forecast и bot читают хранилище и переключаются одним
коммитом — промежуточного зелёного состояния между ними нет.

settings.py и routes.py удалены: их роль забрал store."
```

---

# ФАЗА 2 — явные параметры и ленивый кэш

### Task 8: `model` становится обязательным в `engine`

**Files:**
- Modify: `engine.py:218-268`, `engine.py:399-417`, `engine.py:1131-1136`
- Test: `tests/test_engine_model.py`, `tests/test_ceiling_model.py`

**Interfaces:**
- Consumes: `engine.MODELS`, `engine.DEFAULT_MODEL_KEY`
- Produces:
  - `engine.build_url(site, rng, date=None, *, model)` — `model` обязателен, keyword-only
  - `engine.route_weather_url(coords, date, tz, *, model)`
  - `engine.ceiling_url(site, rng, date=None)` — без изменений, всегда GFS
  - `engine._model_note(data)` — читает только `data["_model_key"]`, без запасного чтения глобалки

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_engine_model.py`:

```python
def test_build_url_requires_model():
    """Забыть модель должно быть ошибкой вызова, а не тихим падением на дефолт."""
    site = {"name": "X", "lat": 1.0, "lon": 2.0, "elevation_m": 100}
    with pytest.raises(TypeError):
        engine.build_url(site, "1d", None)


def test_build_url_uses_given_model():
    site = {"name": "X", "lat": 1.0, "lon": 2.0, "elevation_m": 100}
    assert "models=gfs_seamless" in engine.build_url(site, "1d", None, model="gfs")
    assert "models=ecmwf_ifs025" in engine.build_url(site, "1d", None, model="ecmwf")


def test_route_weather_url_requires_model():
    with pytest.raises(TypeError):
        engine.route_weather_url([(1.0, 2.0)], "2026-07-29", "auto")


def test_model_note_reads_only_response_key():
    """_model_note больше не подсматривает в глобальную настройку."""
    assert "ECMWF" in engine._model_note({"_model_key": "ecmwf", "hourly": {}})
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_engine_model.py -q`
Expected: FAIL — `build_url` пока принимает вызов без `model`

- [ ] **Step 3: Реализовать**

В `engine.py` изменить сигнатуры:

```python
def build_url(site, rng, date=None, *, model):
    ...
            f"&wind_speed_unit=ms&timezone=auto&models={model_id(model)}")


def route_weather_url(coords, date, tz, *, model):
    ...
            f"&models={model_id(model)}"
```

В `_model_note` убрать запасное чтение:

```python
def _model_note(data):
    key = data.get("_model_key") or DEFAULT_MODEL_KEY
```

(`_fetch_build` всегда проставляет `_model_key`; `DEFAULT_MODEL_KEY` остаётся
только для ответов, собранных в тестах вручную.)

В `engine.main()` передать модель явно:

```python
        print(build_url(site, a.range, a.date, model=DEFAULT_MODEL_KEY)); return
```

Убрать из `tests/test_ceiling_model.py` и `tests/test_engine_degrade.py`
`monkeypatch.setattr(engine, "get_model_key", …)` — функции больше нет, модель
передаётся аргументом.

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -5`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add engine.py tests/
git commit -m "refactor(engine): model — обязательный параметр URL-функций"
```

---

### Task 9: `model` и `cfg` становятся обязательными в `forecast`

**Files:**
- Modify: `forecast.py:64-92`, `forecast.py:170-186`, `forecast.py:280-355`, `forecast.py:405-436`, `forecast.py:667-760`, `forecast.py:838-880`
- Modify: `bot.py` — все вызовы `forecast.*`
- Test: `tests/conftest.py` (фикстуры `fc_calls`, `an_calls`)

**Interfaces:**
- Consumes: `engine.build_url(…, model=…)`, `engine.route_weather_url(…, model=…)` (задача 10), `store.Prefs` (задача 3)
- Produces:
  - `forecast.get_forecast(site_name, rng, date, *, model)`
  - `forecast.get_wind_grid(site_name, date, *, model)`
  - `forecast.get_analysis(site_name, rng, date=None, deep=False, *, model)`
  - `forecast.scan_week(*, model)`
  - `forecast.get_route(points, name, date, departure_h=None, *, cfg, model)`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_explicit_params.py`:

```python
"""Модель и настройки приходят параметром: домен не должен знать, кто спрашивает.

Проверяется сигнатура, а не вызов: корутина с недостающим keyword-only
аргументом падает ещё до await, и оборачивать это в asyncio.run незачем.
"""
import inspect

import forecast

REQUIRED = [
    (forecast.get_forecast,  "model"),
    (forecast.get_wind_grid, "model"),
    (forecast.get_analysis,  "model"),
    (forecast.scan_week,     "model"),
    (forecast.get_route,     "model"),
    (forecast.get_route,     "cfg"),
]
# get_facts появляется в задаче 11 и дописывается в этот список там же.


def test_required_params_have_no_default():
    for fn, name in REQUIRED:
        p = inspect.signature(fn).parameters[name]
        assert p.default is inspect.Parameter.empty, f"{fn.__name__}: {name} с дефолтом"


def test_required_params_are_keyword_only():
    """Позиционными их делать нельзя: у get_route перед ними стоит
    departure_h со значением по умолчанию."""
    for fn, name in REQUIRED:
        p = inspect.signature(fn).parameters[name]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, f"{fn.__name__}: {name}"
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_explicit_params.py -q`
Expected: FAIL — у параметров есть значения по умолчанию

- [ ] **Step 3: Реализовать**

`forecast.py`:

```python
async def scan_week(*, model) -> dict:
    sites = store.load_sites()

    async def fetch(site):
        key = (site["name"], "week", None, model)
        _c, _p, _f, _fb, rows, _grid = await _ensure(site, "week", None, key, model)
        return rows
    ...


def _resolve(site_name, rng, date, model):
    ...
    return site, date, (site["name"], rng, date, model)


async def get_forecast(site_name: str, rng: str, date: str | None = None, *, model):
    site, date, key = _resolve(site_name, rng, date, model)
    ...


async def get_wind_grid(site_name: str, date: str, *, model) -> bytes:
    ...


async def get_analysis(site_name: str, rng: str, date: str | None = None,
                       deep: bool = False, *, model) -> str:
    ...


async def get_route(points, name, date, departure_h=None, *, cfg, model):
    """Профиль маршрута. cfg — store.Prefs пользователя, model — его модель."""
    _check_date(date)
    # строка `cfg = settings.get()` удаляется — cfg приходит параметром
    ...
    bodies = await _ensure_route_weather(samples, date, model)
```

Восемь мест переходят с `cfg["…"]` на `cfg.…`:

| Файл | Строка | Было | Стало |
|---|---|---|---|
| `forecast.py` | 606 | `cfg["avg_route_speed_kmh"]` | `cfg.avg_route_speed_kmh` |
| `forecast.py` | 621 | `cfg["wind_correction_enabled"]` | `cfg.wind_correction_enabled` |
| `forecast.py` | 728 | `cfg["avg_route_speed_kmh"]` | `cfg.avg_route_speed_kmh` |
| `forecast.py` | 729 | `cfg["wind_correction_enabled"]` | `cfg.wind_correction_enabled` |
| `bot.py` | 475 | `cfg["wind_correction_enabled"]` | `cfg.wind_correction_enabled` |
| `bot.py` | 477 | `cfg['avg_route_speed_kmh']` | `cfg.avg_route_speed_kmh` |
| `bot.py` | 486 | `cfg["wind_correction_enabled"]` | `cfg.wind_correction_enabled` |
| `bot.py` | 487 | `cfg['wind_correction_enabled']` | `cfg.wind_correction_enabled` |

`_ensure_route_weather(samples, date, model)` — `model` становится позиционным
обязательным, `mkey = model` вместо `model or engine.get_model_key()`.

В `bot.py` каждый вызов `forecast.*` получает `model=` и, где нужно, `cfg=`:

```python
prefs = store.prefs(uid)
profile = await forecast.get_route(points, name, date, departure,
                                   cfg=prefs, model=prefs.model_key)
```

Фикстуры в `conftest.py`:

```python
@pytest.fixture()
def fc_calls(monkeypatch):
    calls = []

    async def fake(site, rng, date=None, *, model):
        calls.append((site, rng, date, model))
        return f"CARD {site} {rng} {date}", [b"png"]

    monkeypatch.setattr(forecast, "get_forecast", fake)
    return calls


@pytest.fixture()
def an_calls(monkeypatch):
    calls = []

    async def fake(site, rng, date=None, deep=False, *, model):
        calls.append((site, rng, date, deep, model))
        return "АНАЛИЗ ГОТОВ"

    monkeypatch.setattr(forecast, "get_analysis", fake)
    return calls
```

- [ ] **Step 4: Прогнать весь набор**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -5`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add forecast.py bot.py tests/
git commit -m "refactor(forecast): model и cfg — обязательные параметры

Домен больше не знает, кто спрашивает: предпочтения резолвит адаптер."
```

---

### Task 10: единый источник чисел — час пика и оговорки

**Files:**
- Modify: `engine.py:767-860` (`report_1day`), `engine.py:991-1060` (`facts_1day`)
- Test: `tests/test_engine_facts.py`

**Interfaces:**
- Consumes: `engine.assess_day`, `engine.sun_hours`, `engine.wind_from_avg`, `engine.dir_verdict`
- Produces:
  - `engine.facts_1day(data, site, assessment=None)` дополнительно содержит ключи:
    - `peak_hour: int` — час пика, тот же, что показывает карточка
    - `fly_dir_deg: float` — направление ветра в рабочее окно
    - `dir_verdict: str` — «в лоб» / «боковой» / «в спину» словами
    - `dir_class: str` — `head` / `cross` / `tail`
    - `caveats: list[str]` — оговорки, которые раньше жили только внутри строки
  - `engine.report_1day` берёт эти значения из фактов и не пересчитывает их

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_engine_facts.py`. Файл уже импортирует билдеры строкой
`from fixtures import om_1day as _full_1d, site as _site` — используем их же.
В шапку файла добавить `import re`.

```python
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
    assert facts["dir_class"] in ("head", "cross", "tail")
    assert facts["dir_verdict"]
    assert 0 <= facts["fly_dir_deg"] < 360


def test_facts_carry_caveats():
    facts = engine.facts_1day(_full_1d(), _site())
    assert isinstance(facts["caveats"], list)
    # старт из fixtures.site() без route_top_m — вето «база ниже вершин» не проверяется
    assert any("route_top_m" in c for c in facts["caveats"])
```

Примечание реализующему: `card` — третий элемент кортежа `report_1day`, именно в
нём строка «пик HH–HH». Если после правки в карточке пика нет (нет термического
окна на этих данных), значит подобранный профиль температуры не даёт окна —
поднять значения так, чтобы `assess_day` вернул непустое `fly_window`.

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv/bin/python -m pytest tests/test_engine_facts.py -q -k "peak_hour or direction or caveats"`
Expected: FAIL — `KeyError: 'peak_hour'`

- [ ] **Step 3: Вынести общий расчёт**

Добавить в `engine.py` перед `report_1day`:

```python
def _day_frame(data, site, assessment=None):
    """Величины, нужные и карточке, и фактам, посчитанные ровно один раз.

    До этого час пика считался в двух местах по разным правилам: карточка брала
    максимум по рабочему окну с тай-брейком по солнцу на склоне, факты — простой
    максимум температуры за световой день. Профиль ветра, уходивший в Gemini, мог
    относиться не к тому часу, что видел пилот.
    """
    H, D = data["hourly"], data["daily"]
    t = H["time"]
    sr, ss = D["sunrise"][0], D["sunset"][0]
    day = daylight_idx(t, sr, ss)
    temp = H["temperature_2m"]
    assess, ctx = assessment or assess_day(data, site)
    tw = ctx["thermal_window"]
    workable = [i for i in day
                if tw and tw["start_hour"] <= hour_of(t[i]) <= tw["end_hour"]]
    ref = tw["peak_hour"] if tw else hour_of(t[max(day, key=lambda i: temp[i])])
    tmax_i = max(workable or day,
                 key=lambda i: (round(temp[i], 1), -abs(hour_of(t[i]) - ref)))
    # направление в рабочее окно (11–16, взвешенное по скорости) — НЕ суточное
    # доминирующее: слабый ночной сток утягивает его от термического ветра
    core = [i for i in day if 11 <= hour_of(t[i]) <= 16] or [tmax_i]
    fly_dir = wind_from_avg([H["wind_direction_10m"][i] for i in core],
                            [max(H["wind_speed_10m"][i], 0.3) for i in core])
    dv, dc = dir_verdict(fly_dir, site["aspect_deg"])
    return {"day": day, "assess": assess, "ctx": ctx, "thermal_window": tw,
            "tmax_i": tmax_i, "peak_hour": hour_of(t[tmax_i]),
            "fly_dir": fly_dir, "dir_verdict": dv, "dir_class": dc}
```

- [ ] **Step 4: Переключить обе функции на общий расчёт**

В `report_1day` заменить самостоятельные вычисления `assess/ctx/tw/workable/ref/tmax_i/peak_h/core/fly_dir/dv,dc`
на один вызов `frame = _day_frame(data, site, assessment)` и чтение из него.
Список оговорок собирать в отдельную функцию:

```python
def day_caveats(data, site, frame):
    """Оговорки под карточкой. Возвращает список строк — их же кладут в факты."""
    cav = []
    assess = frame["assess"]
    if assess.vetoes_in_window:
        cav.append("вето внутри окна: " + ", ".join(
            criteria.veto_labels(assess.vetoes_in_window)))
    if any(h.raw.get("foehn_suspect") for h in assess.hours):
        cav.append("признаки фёна (эвристика по косвенным приметам, не расчёт) — "
                   "роторы с подветра могут быть жёсткими")
    ...
    return cav
```

Перенести в неё существующие ветки из `report_1day` дословно, не меняя текстов.
`report_1day` печатает `"⚠️ " + "; ".join(cav) + "."` как раньше.

В `facts_1day` заменить строку `tmax_i = max(day, key=lambda i: temp[i])` на
`frame = _day_frame(data, site, assessment)` и `tmax_i = frame["tmax_i"]`, а в
возвращаемый словарь добавить:

```python
        "peak_hour": frame["peak_hour"],
        "fly_dir_deg": round(frame["fly_dir"], 1),
        "dir_verdict": frame["dir_verdict"],
        "dir_class": frame["dir_class"],
        "caveats": day_caveats(data, site, frame),
```

- [ ] **Step 5: Прогнать весь набор**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -5`
Expected: PASS

Если падают golden-тесты промпта (`tests/test_route_prompt.py`,
`tests/test_analysis.py`) — сверить, что изменился только состав ключей фактов,
а не значения существующих, и обновить эталон.

- [ ] **Step 6: Коммит**

```bash
git add engine.py tests/
git commit -m "fix(engine): карточка и факты берут час пика из одного расчёта

Раньше report_1day выбирал пик по рабочему окну, а facts_1day — по максимуму
температуры за световой день, и профиль ветра для Gemini мог относиться к
другому часу. Заодно направление в окно и оговорки переезжают в факты."
```

---

### Task 11: кэш хранит сырьё, производные считаются лениво

**Files:**
- Modify: `forecast.py:16-30` (объявления кэшей), `forecast.py:280-355`
- Test: `tests/test_lazy_cache.py`

**Interfaces:**
- Consumes: `engine.assess_day`, `engine.report_1day`, `engine.facts_1day`, `engine.report_overview`, `engine.facts_overview`, `engine.overview_rows`, `engine.wind_grid`
- Produces:
  - `forecast._fcache[key] = (expires, data, assessment, derived)` где `derived: dict`
  - `forecast._ensure(site, rng, date, key, model) -> tuple` — возвращает `(data, assessment, derived)`
  - `forecast._derive(site, rng, data, assessment, derived, what: str)` — считает и запоминает одну производную
  - `forecast.get_facts(site_name, rng, date=None, *, model) -> dict` — новая публичная функция

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_lazy_cache.py`:

```python
"""Кэш держит сырьё; текст, PNG и факты считаются только тогда, когда их просят.

До этого _fetch_build рендерил 2-3 PNG через Pillow на каждый промах кэша —
и рендерил бы их на каждый запрос из приложения, где они не нужны.
"""
import pytest

import asyncio

import pytest

import charts
import engine
import forecast
from fixtures import DATE, om_1day


@pytest.fixture()
def net(monkeypatch):
    """Подменяет сетевой запрос ответом-фикстурой и считает обращения.

    Тот же приём, что в tests/test_engine_model.py: бот не мокает HTTP целиком,
    а подменяет forecast._fetch_main. Побочный запрос за потолком уже заглушён
    автофикстурой no_ceiling_request из conftest.
    """
    calls = []

    async def fake(url):
        calls.append(url)
        return om_1day()

    monkeypatch.setattr(forecast, "_fetch_main", fake)
    return calls


@pytest.fixture()
def count_png(monkeypatch):
    """Считает, сколько раз рисовалась метеограмма.

    Патчится charts, а не engine: engine импортирует функцию внутри report_1day
    (`from charts import meteogram_png`), то есть достаёт её из charts на каждом
    вызове.
    """
    calls = []
    real = charts.meteogram_png

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(charts, "meteogram_png", counting)
    return calls


def test_get_facts_does_not_render_png(net, count_png):
    asyncio.run(forecast.get_facts("Гудаури", "1d", DATE, model="auto"))
    assert count_png == []


def test_get_forecast_renders_png_once(net, count_png):
    asyncio.run(forecast.get_forecast("Гудаури", "1d", DATE, model="auto"))
    asyncio.run(forecast.get_forecast("Гудаури", "1d", DATE, model="auto"))
    assert len(count_png) == 1


def test_facts_then_forecast_hits_network_once(net):
    asyncio.run(forecast.get_facts("Гудаури", "1d", DATE, model="auto"))
    asyncio.run(forecast.get_forecast("Гудаури", "1d", DATE, model="auto"))
    assert len(net) == 1


def test_assess_day_computed_once_per_entry(net, monkeypatch):
    calls = []
    real = engine.assess_day

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(engine, "assess_day", counting)
    asyncio.run(forecast.get_facts("Гудаури", "1d", DATE, model="auto"))
    asyncio.run(forecast.get_forecast("Гудаури", "1d", DATE, model="auto"))
    assert len(calls) == 1
```

Дописать в `tests/test_explicit_params.py` строку в список `REQUIRED`:

```python
    (forecast.get_facts,     "model"),
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_lazy_cache.py -q`
Expected: FAIL — `AttributeError: module 'forecast' has no attribute 'get_facts'`

- [ ] **Step 3: Реализовать**

Заменить `_fetch_build` и `_ensure` в `forecast.py`:

```python
async def _fetch_raw(site: dict, rng: str, date: str | None, model: str):
    """Сходить за данными и посчитать оценку. Ничего не рендерит.

    Потолок всегда берётся из GFS отдельным узким запросом — конкурентно с
    основным, поэтому задержка не растёт. Когда выбрана сама GFS, запроса нет.
    """
    main = _fetch_main(engine.build_url(site, rng, date, model=model))
    if model == engine.CEILING_MODEL_KEY:
        data, gfs = await main, None
    else:
        data, gfs = await asyncio.gather(
            main, _fetch_ceiling(engine.ceiling_url(site, rng, date)))
    data["_model_key"] = model
    if _splice_ceiling(data, gfs):
        data["_ceiling_model"] = engine.CEILING_MODEL_KEY
    # один расчёт лётности на карточку, графики и данные для LLM — иначе три
    # места считали бы его независимо и могли разойтись
    assessment = engine.assess_day(data, site) if rng == "1d" else None
    return data, assessment


def _derive(site: dict, rng: str, data: dict, assessment, derived: dict, what: str):
    """Посчитать производную и запомнить её в записи кэша.

    what: "text" (fallback + card + pngs) | "facts" | "rows" | "grid"
    """
    if what in derived:
        return derived[what]
    if what == "text":
        out = tempfile.mkdtemp(prefix="pgfc_")
        try:
            if rng == "1d":
                fallback, png_paths, card = engine.report_1day(data, site, out, assessment)
            else:
                fallback, png_paths, card = engine.report_overview(data, site, rng, out)
            derived["text"] = (card, [pathlib.Path(p).read_bytes() for p in png_paths],
                               fallback)
        finally:
            shutil.rmtree(out, ignore_errors=True)
    elif what == "facts":
        derived["facts"] = (engine.facts_1day(data, site, assessment) if rng == "1d"
                            else engine.facts_overview(data, site, rng))
    elif what == "rows":
        derived["rows"] = [] if rng == "1d" else engine.overview_rows(data, site)
    elif what == "grid":
        derived["grid"] = engine.wind_grid(data, site) if rng == "1d" else None
    return derived[what]


async def _ensure(site: dict, rng: str, date: str | None, key: tuple, model: str):
    """Вернуть (data, assessment, derived), сходив в сеть только на холодном кэше."""
    now = time.monotonic()
    _purge(now)
    if key in _fcache:
        _exp, data, assessment, derived = _fcache[key]
        return data, assessment, derived
    data, assessment = await _fetch_raw(site, rng, date, model)
    derived: dict = {}
    _fcache[key] = (now + _TTL, data, assessment, derived)
    return data, assessment, derived
```

Переписать публичные функции:

```python
async def get_forecast(site_name: str, rng: str, date: str | None = None, *, model):
    """Факты карточкой + графики. Без LLM. rng: 1d | 3d | week | 2weeks."""
    site, date, key = _resolve(site_name, rng, date, model)
    data, assessment, derived = await _ensure(site, rng, date, key, model)
    card, pngs, _fallback = _derive(site, rng, data, assessment, derived, "text")
    return card, pngs


async def get_facts(site_name: str, rng: str, date: str | None = None, *, model) -> dict:
    """Структурированные факты — то же, что уходит в Gemini, и то же, что
    отдаётся приложению. PNG при этом не рисуются."""
    site, date, key = _resolve(site_name, rng, date, model)
    data, assessment, derived = await _ensure(site, rng, date, key, model)
    return _derive(site, rng, data, assessment, derived, "facts")


async def get_wind_grid(site_name: str, date: str, *, model) -> bytes:
    site, date, key = _resolve(site_name, "1d", date, model)
    data, assessment, derived = await _ensure(site, "1d", date, key, model)
    grid = _derive(site, "1d", data, assessment, derived, "grid")
    if not grid:
        raise ForecastError("Данные по высотам недоступны для этого дня.")
    out = tempfile.mkdtemp(prefix="pgwg_")
    try:
        import charts
        return pathlib.Path(charts.wind_grid_png(grid, site, out)).read_bytes()
    finally:
        shutil.rmtree(out, ignore_errors=True)
```

Поправить два оставшихся потребителя `_ensure`:

- `scan_week.fetch` → `rows = _derive(site, "week", *(await _ensure(...)), "rows")`,
  разложив кортеж явно, а не звёздочкой:
  ```python
  data, assessment, derived = await _ensure(site, "week", None, key, model)
  return _derive(site, "week", data, assessment, derived, "rows")
  ```
- `get_analysis` → берёт `facts` и `text`:
  ```python
  data, assessment, derived = await _ensure(site, rng, date, base_key, model)
  facts = _derive(site, rng, data, assessment, derived, "facts")
  card, _pngs, fallback = _derive(site, rng, data, assessment, derived, "text")
  rules_tail = fallback[len(card):].strip() or fallback
  ```

Поправить `cached_dates` (строка 187): запись кэша теперь четырёхэлементная,
факты лежат в `derived` и могут быть ещё не посчитаны:

```python
def cached_dates(site_name, rng, date=None, model=None):
    """Даты закэшированного обзора — для пикера дней. None на холодном кэше."""
    try:
        site, _date, key = _resolve(site_name, rng, date, model or engine.DEFAULT_MODEL_KEY)
    except ForecastError:
        return None
    entry = _fcache.get(key)
    if entry is None:
        return None
    _exp, data, assessment, derived = entry
    facts = _derive(site, rng, data, assessment, derived, "facts")
    days = facts.get("days_daytime") or []
    return [d["date"] for d in days] or None
```

- [ ] **Step 4: Прогнать весь набор**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -5`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add forecast.py tests/test_lazy_cache.py
git commit -m "perf(forecast): кэш держит сырьё, производные считаются лениво

Запрос фактов больше не рендерит PNG — иначе каждый вызов из приложения
платил бы за три картинки, которые никто не увидит."
```

---

### Task 12: Dockerfile, compose и README

**Files:**
- Modify: `Dockerfile`, `docker-compose.yml`, `.env.example`, `README.md`
- Test: ручная проверка сборки

**Interfaces:**
- Consumes: `store.DB_PATH`, `store.bootstrap`
- Produces: образ, где данные лежат в `/app/data/pgbot.db`

- [ ] **Step 1: Обновить `docker-compose.yml`**

Заменить блок `environment`:

```yaml
    environment:
      - TZ=${TZ:-Asia/Tbilisi}
      # БД в том же именованном томе, что раньше держал sites.json —
      # старые файлы там же, миграция подхватит их на первом старте
      - DB_PATH=/app/data/pgbot.db
```

- [ ] **Step 2: Обновить `.env.example`**

Заменить строки про `SITES_FILE`, `MODEL_FILE`, `SETTINGS_FILE`, `ROUTES_FILE`
одной:

```
# Файл базы. По умолчанию — data/pgbot.db рядом с кодом; в контейнере
# перекрывается на /app/data/pgbot.db (том с правами на запись).
DB_PATH=
```

- [ ] **Step 3: Обновить `README.md`**

В разделе про хранение заменить упоминания четырёх JSON-файлов на описание БД:
общая библиотека стартов, личные маршруты и настройки, миграция при первом
старте с переименованием файлов в `*.migrated`.

- [ ] **Step 4: Проверить сборку и миграцию**

```bash
docker compose build
docker compose run --rm pgbot python -c "
import store, os
os.environ.setdefault('DB_PATH', '/app/data/pgbot.db')
print(store.bootstrap('/app/data', frozenset(), '/app/sites.json'))
print([s['name'] for s in store.load_sites()])
"
```

Expected: отчёт с `sites >= 1` и список стартов.

- [ ] **Step 5: Прогнать весь набор и закоммитить**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -3`
Expected: PASS

```bash
git add Dockerfile docker-compose.yml .env.example README.md
git commit -m "chore: деплой переходит на DB_PATH вместо четырёх JSON-файлов"
```

---

## Что остаётся на следующие планы

- **Фаза 3** — `app.py`, `api.py`, валидация `initData`, Caddy в compose.
- **Фаза 4** — `webapp/` на Vite + React.
- **Фаза 5** — домен и кнопка меню в BotFather.

## Самопроверка плана

Проверено против спеки `2026-07-28-miniapp-architecture-design.md`:

| Требование спеки | Задача |
|---|---|
| Схема шести таблиц | 1 |
| Старты — общая библиотека, псевдонимы | 2 |
| `find_site` возвращает `None` вместо `SystemExit` | 2 |
| `Prefs` — замороженный dataclass, ленивые дефолты | 3 |
| Маршруты по пользователю, `MAX_ROUTES` | 4 |
| Рельеф и ad-hoc переживают рестарт, уборка 30 дней | 5 |
| Миграция, раздача по `ALLOWED_USER_IDS`, `*.migrated` | 6 |
| Пустой `ALLOWED_USER_IDS` — маршруты не переносятся | 6 |
| `conftest` на временной SQLite | 7a |
| `engine` без хранилища | 7b |
| `settings.py` и `routes.py` удаляются | 7c |
| `model` обязателен в URL-функциях | 8 |
| `model` и `cfg` обязательны в `forecast` | 9 |
| 8 мест `cfg["…"]` → `cfg.…` | 9 |
| Единый источник чисел, час пика | 10 |
| Ленивый кэш, `get_facts` | 11 |
| `DB_PATH` вместо четырёх переменных | 12 |

Не покрыто планом намеренно: `store.py` не импортирует модули проекта — проверяется
тестом в задаче 1, отдельной задачи не требует.

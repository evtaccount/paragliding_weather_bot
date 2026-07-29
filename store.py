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
        # Сначала ищем по имени (с учётом регистра через Python, т.к. SQLite's lower() не работает с кириллицей)
        all_sites = conn.execute("SELECT * FROM sites").fetchall()
        row = None
        for site_row in all_sites:
            if site_row["name"].lower() == key:
                row = site_row
                break

        if row is None:
            # Ищем по псевдониму
            all_aliases = conn.execute("SELECT alias, name FROM site_aliases").fetchall()
            site_name = None
            for alias_row in all_aliases:
                if alias_row["alias"].lower() == key:
                    site_name = alias_row["name"]
                    break
            if site_name is None:
                return None
            row = conn.execute(
                "SELECT * FROM sites WHERE name = ?", (site_name,)).fetchone()
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
        # Проверка по имени (с учётом регистра через Python, т.к. SQLite's lower() не работает с кириллицей)
        all_sites = conn.execute("SELECT name FROM sites").fetchall()
        for site_row in all_sites:
            if site_row["name"].lower() == key:
                raise ValueError(f"старт «{site['name']}» уже есть")

        # Проверка по псевдониму
        all_aliases = conn.execute("SELECT alias, name FROM site_aliases").fetchall()
        for alias_row in all_aliases:
            if alias_row["alias"].lower() == key:
                raise ValueError(f"имя «{site['name']}» уже занято как псевдоним "
                                 f"старта «{alias_row['name']}»")

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
    key = name.strip().lower()
    with connect() as conn:
        # Поиск по имени (с учётом регистра через Python, т.к. SQLite's lower() не работает с кириллицей)
        all_sites = conn.execute("SELECT name FROM sites").fetchall()
        actual_name = None
        for site_row in all_sites:
            if site_row["name"].lower() == key:
                actual_name = site_row["name"]
                break

        if actual_name is None:
            raise ValueError(f"старт «{name}» не найден")
        conn.execute("DELETE FROM sites WHERE name = ?", (actual_name,))

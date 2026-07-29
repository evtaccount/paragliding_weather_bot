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

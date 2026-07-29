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

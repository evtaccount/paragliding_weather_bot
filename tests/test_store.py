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

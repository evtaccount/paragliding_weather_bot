"""Тесты хранилища. Своя временная БД на тест — conftest переезжает на неё в задаче 7."""
import dataclasses
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

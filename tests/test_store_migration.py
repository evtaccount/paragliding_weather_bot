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

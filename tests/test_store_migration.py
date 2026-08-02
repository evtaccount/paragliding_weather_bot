"""Миграция JSON-файлов в SQLite. Один раз, при первом старте на новой схеме."""
import importlib
import json
import os

import pytest

import engine

# тот же список, что подставляет бот. valid_model_keys обязателен: «забыли
# передать» раньше означало «не проверяем», и это была дыра — миграция это
# единственный путь записи model_key без валидации перед ним.
MODEL_KEYS = set(engine.MODELS)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Свежий модуль store с БД во временном каталоге.

    reload() меняет модуль-синглтон целиком — на тот же объект ссылаются
    conftest, bot и forecast. Без отката DB_PATH на teardown все тестовые
    файлы, которые прогонятся после этого, останутся смотреть на протухший
    tmp_path (см. review finding 1).
    """
    harness_db_path = os.environ["DB_PATH"]  # conftest всегда ставит его до импорта
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    import store as st
    importlib.reload(st)
    yield st
    os.environ["DB_PATH"] = harness_db_path
    importlib.reload(st)


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
    report = store.migrate_from_json(data_dir, frozenset(), valid_model_keys=MODEL_KEYS)
    assert report["sites"] == 1
    s = store.find_site("laliskuri")
    assert s["name"] == "Лалискури" and s["elevation_m"] == 686
    assert s["aspect_deg"] == 180


def test_comment_key_ignored(store, data_dir):
    write(os.path.join(data_dir, "sites.json"), SITES_JSON)
    store.init()
    store.migrate_from_json(data_dir, frozenset(), valid_model_keys=MODEL_KEYS)
    assert [s["name"] for s in store.load_sites()] == ["Лалискури"]


def test_renames_migrated_files(store, data_dir):
    p = os.path.join(data_dir, "sites.json")
    write(p, SITES_JSON)
    store.init()
    store.migrate_from_json(data_dir, frozenset(), valid_model_keys=MODEL_KEYS)
    assert not os.path.exists(p)
    assert os.path.exists(p + ".migrated")


def test_routes_copied_to_every_allowed_user(store, data_dir):
    write(os.path.join(data_dir, "routes.json"),
          {"Гудаури → Пасанаури": {"points": [[42.4, 44.4, None], [42.2, 44.6, None]],
                                   "saved": "2026-07-24"}})
    store.init()
    report = store.migrate_from_json(data_dir, frozenset({111, 222}), valid_model_keys=MODEL_KEYS)
    assert report["routes"] == 2
    assert list(store.routes_list(111)) == ["Гудаури → Пасанаури"]
    assert list(store.routes_list(222)) == ["Гудаури → Пасанаури"]


def test_routes_kept_when_no_allowlist(store, data_dir):
    """С пустым списком раздавать общие маршруты некому — файл остаётся на месте."""
    p = os.path.join(data_dir, "routes.json")
    write(p, {"Мой": {"points": [[1.0, 2.0, None], [3.0, 4.0, None]]}})
    store.init()
    report = store.migrate_from_json(data_dir, frozenset(), valid_model_keys=MODEL_KEYS)
    assert report["routes"] == 0
    assert "routes.json" in report["skipped"]
    assert os.path.exists(p)               # не переименован — миграцию можно повторить


def test_settings_and_model_become_user_defaults(store, data_dir):
    write(os.path.join(data_dir, "settings.json"),
          {"avg_route_speed_kmh": 32.0, "wind_correction_enabled": False})
    write(os.path.join(data_dir, "model.json"), {"model": "gfs"})
    store.init()
    store.migrate_from_json(data_dir, frozenset({111}), valid_model_keys=MODEL_KEYS)
    p = store.prefs(111)
    assert p.avg_route_speed_kmh == 32.0
    assert p.wind_correction_enabled is False
    assert p.model_key == "gfs"


def test_migration_is_not_repeated_on_second_run(store, data_dir):
    write(os.path.join(data_dir, "sites.json"), SITES_JSON)
    store.init()
    store.migrate_from_json(data_dir, frozenset(), valid_model_keys=MODEL_KEYS)
    second = store.migrate_from_json(data_dir, frozenset(), valid_model_keys=MODEL_KEYS)
    assert second["sites"] == 0
    assert len(store.load_sites()) == 1


def test_corrupt_file_does_not_abort_migration(store, data_dir):
    with open(os.path.join(data_dir, "sites.json"), "w", encoding="utf-8") as f:
        f.write("{не json")
    write(os.path.join(data_dir, "model.json"), {"model": "icon"})
    store.init()
    report = store.migrate_from_json(data_dir, frozenset({111}), valid_model_keys=MODEL_KEYS)
    assert "sites.json" in report["skipped"]
    assert store.prefs(111).model_key == "icon"


def test_malformed_site_entry_does_not_abort_migration(store, data_dir):
    """Регрессия: null/строка/число в sites — раньше add_site(s) роняла всю
    миграцию TypeError'ом, до model.json дело не доходило."""
    write(os.path.join(data_dir, "sites.json"),
          {"sites": [None, "мусор", 42,
                     {"name": "Ок", "lat": 1.0, "lon": 2.0, "elevation_m": 100}]})
    write(os.path.join(data_dir, "model.json"), {"model": "icon"})
    store.init()
    report = store.migrate_from_json(data_dir, frozenset({111}), valid_model_keys=MODEL_KEYS)
    assert report["sites"] == 1
    assert [s["name"] for s in store.load_sites()] == ["Ок"]
    assert store.prefs(111).model_key == "icon"
    assert os.path.exists(os.path.join(data_dir, "sites.json.migrated"))


def test_rerun_does_not_duplicate_routes(store, data_dir):
    write(os.path.join(data_dir, "routes.json"),
          {"Мой": {"points": [[1.0, 2.0, None], [3.0, 4.0, None]]}})
    store.init()
    store.migrate_from_json(data_dir, frozenset({111}), valid_model_keys=MODEL_KEYS)
    second = store.migrate_from_json(data_dir, frozenset({111}), valid_model_keys=MODEL_KEYS)
    assert second["routes"] == 0
    assert list(store.routes_list(111)) == ["Мой"]


def test_rerun_does_not_duplicate_settings_and_model(store, data_dir):
    write(os.path.join(data_dir, "settings.json"), {"avg_route_speed_kmh": 32.0})
    write(os.path.join(data_dir, "model.json"), {"model": "gfs"})
    store.init()
    store.migrate_from_json(data_dir, frozenset({111}), valid_model_keys=MODEL_KEYS)
    second = store.migrate_from_json(data_dir, frozenset({111}), valid_model_keys=MODEL_KEYS)
    assert second["users"] == 0
    assert store.prefs(111).avg_route_speed_kmh == 32.0
    assert store.prefs(111).model_key == "gfs"


def test_second_run_migrates_once_allowlist_configured(store, data_dir):
    """Первый прогон с пустым списком ничего не переносит и оставляет файлы
    на месте; второй — после появления allowlist — переносит их успешно."""
    write(os.path.join(data_dir, "routes.json"),
          {"Мой": {"points": [[1.0, 2.0, None], [3.0, 4.0, None]]}})
    write(os.path.join(data_dir, "settings.json"), {"avg_route_speed_kmh": 32.0})
    write(os.path.join(data_dir, "model.json"), {"model": "gfs"})
    store.init()

    first = store.migrate_from_json(data_dir, frozenset(), valid_model_keys=MODEL_KEYS)
    assert first["routes"] == 0 and first["users"] == 0
    assert set(first["skipped"]) == {"routes.json", "settings.json", "model.json"}

    second = store.migrate_from_json(data_dir, frozenset({111}), valid_model_keys=MODEL_KEYS)
    assert second["routes"] == 1
    assert second["users"] == 1
    assert list(store.routes_list(111)) == ["Мой"]
    assert store.prefs(111).avg_route_speed_kmh == 32.0
    assert store.prefs(111).model_key == "gfs"


def test_bootstrap_seeds_from_packaged_sites_when_empty(store, data_dir, tmp_path):
    packaged = tmp_path / "packaged.json"
    write(str(packaged), SITES_JSON)
    report = store.bootstrap(data_dir, frozenset(), str(packaged), valid_model_keys=MODEL_KEYS)
    assert report["sites"] == 1
    assert store.find_site("Лалискури") is not None


def test_bootstrap_does_not_seed_when_sites_exist(store, data_dir, tmp_path):
    packaged = tmp_path / "packaged.json"
    write(str(packaged), SITES_JSON)
    store.init()
    store.add_site({"name": "Свой", "lat": 1.0, "lon": 2.0, "elevation_m": 10})
    report = store.bootstrap(data_dir, frozenset(), str(packaged), valid_model_keys=MODEL_KEYS)
    assert report["sites"] == 0
    assert [s["name"] for s in store.load_sites()] == ["Свой"]


def test_reloading_store_fixture_does_not_leak_into_other_test_files():
    """Regression for review finding 1. Специально БЕЗ фикстуры `store` — см.
    тот же тест в test_store.py: каждый предыдущий тест здесь уже брал её и на
    teardown должен был откатить DB_PATH обратно на гарнесс."""
    import conftest
    import store as st
    assert st.DB_PATH == conftest.DB_PATH


# --------------------------------------------------- потери переноса видно снаружи
#
# Файлы после переноса переименовываются в *.migrated — значит любая
# пропущенная запись исчезает молча: данные лежат рядом, но никто не знает,
# что туда надо смотреть. Всё, что в БД не попало, теперь в report["dropped"].

def test_dropped_records_are_counted_and_named(store, data_dir):
    write(os.path.join(data_dir, "sites.json"),
          {"sites": [None, {"name": "Ок", "lat": 1.0, "lon": 2.0, "elevation_m": 100}]})
    write(os.path.join(data_dir, "routes.json"),
          {"Кривой": {"points": "не список"},
           "Целый": {"points": [[1.0, 2.0, None], [3.0, 4.0, None]]}})
    store.init()
    report = store.migrate_from_json(data_dir, frozenset({111}), valid_model_keys=MODEL_KEYS)
    assert report["sites"] == 1 and report["routes"] == 1
    assert len(report["dropped"]) == 2, report["dropped"]
    assert any("запись #0" in d for d in report["dropped"])
    assert any("Кривой" in d and "points" in d for d in report["dropped"])
    # файлы всё равно переименованы — потому отчёт и обязан назвать потерю
    assert os.path.exists(os.path.join(data_dir, "routes.json.migrated"))


def test_clean_migration_drops_nothing(store, data_dir):
    write(os.path.join(data_dir, "sites.json"), SITES_JSON)
    store.init()
    assert store.migrate_from_json(data_dir, frozenset(), valid_model_keys=MODEL_KEYS)["dropped"] == []


def test_site_with_null_coordinates_does_not_abort_the_start(store, data_dir):
    """«lat»: null даёт NOT NULL constraint failed. Раньше он летел наружу из
    bootstrap и ронял бота на старте — одинаково на каждом рестарте, и чинить
    это можно было только правкой JSON руками."""
    write(os.path.join(data_dir, "sites.json"),
          {"sites": [{"name": "Дыра", "lat": None, "lon": 44.0, "elevation_m": 100},
                     {"name": "Ок", "lat": 1.0, "lon": 2.0, "elevation_m": 100}]})
    store.init()
    report = store.migrate_from_json(data_dir, frozenset(), valid_model_keys=MODEL_KEYS)
    assert report["sites"] == 1
    assert [s["name"] for s in store.load_sites()] == ["Ок"]
    assert any("Дыра" in d for d in report["dropped"]), report["dropped"]


def test_bootstrap_seed_survives_a_site_with_null_coordinates(store, data_dir, tmp_path):
    """Та же беда во втором месте — засеве из упакованного файла."""
    packaged = tmp_path / "packaged.json"
    write(str(packaged), {"sites": [
        {"name": "Дыра", "lat": None, "lon": 44.0, "elevation_m": 100},
        {"name": "Ок", "lat": 1.0, "lon": 2.0, "elevation_m": 100}]})
    report = store.bootstrap(data_dir, frozenset(), str(packaged), valid_model_keys=MODEL_KEYS)
    assert report["sites"] == 1
    assert any("Дыра" in d for d in report["dropped"]), report["dropped"]


# -------------------------------------------- значения настроек проверяются здесь
#
# Миграция — единственный путь записи, перед которым нет валидации set_speed() /
# выбора модели в боте. Неизвестный ключ модели ронял engine.model_id KeyError'ом
# на каждом запросе пилота, нечисловая скорость доезжала до колонки как есть.

def test_unknown_model_key_falls_back_to_the_default(store, data_dir):
    write(os.path.join(data_dir, "model.json"), {"model": "wrf"})
    store.init()
    report = store.migrate_from_json(data_dir, frozenset({111}),
                                     valid_model_keys=MODEL_KEYS)
    assert store.prefs(111).model_key == store.DEFAULT_PREFS.model_key
    assert any("wrf" in d for d in report["dropped"]), report["dropped"]


def test_known_model_key_still_migrates(store, data_dir):
    write(os.path.join(data_dir, "model.json"), {"model": "gfs"})
    store.init()
    report = store.migrate_from_json(data_dir, frozenset({111}),
                                     valid_model_keys=MODEL_KEYS)
    assert store.prefs(111).model_key == "gfs"
    assert report["dropped"] == []


def test_non_numeric_speed_falls_back_to_the_default(store, data_dir):
    write(os.path.join(data_dir, "settings.json"), {"avg_route_speed_kmh": "быстро"})
    store.init()
    report = store.migrate_from_json(data_dir, frozenset({111}), valid_model_keys=MODEL_KEYS)
    speed = store.prefs(111).avg_route_speed_kmh
    assert speed == store.DEFAULT_PREFS.avg_route_speed_kmh
    assert isinstance(speed, float)
    assert any("быстро" in d for d in report["dropped"]), report["dropped"]


def test_out_of_range_speed_falls_back_to_the_default(store, data_dir):
    write(os.path.join(data_dir, "settings.json"),
          {"avg_route_speed_kmh": 500.0, "wind_correction_enabled": False})
    store.init()
    report = store.migrate_from_json(data_dir, frozenset({111}), valid_model_keys=MODEL_KEYS)
    assert store.prefs(111).avg_route_speed_kmh == store.DEFAULT_PREFS.avg_route_speed_kmh
    assert store.prefs(111).wind_correction_enabled is False   # соседнее поле уцелело
    assert any("500" in d for d in report["dropped"]), report["dropped"]


# ------------------------------------------ старые файлы ищутся и в корне репозитория
#
# Каталог БД — это <repo>/data при незаданном DB_PATH, а systemd-путь запускает
# бота из корня репозитория, куда старые дефолты SITES_FILE / ROUTES_FILE /
# SETTINGS_FILE / MODEL_FILE и клали файлы. Под Docker оба каталога совпадали с
# томом, поэтому промах был виден только на bare metal.

def test_legacy_files_are_found_in_the_extra_dir(store, data_dir, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    write(str(root / "routes.json"), {"Мой": {"points": [[1.0, 2.0, None], [3.0, 4.0, None]]}})
    write(str(root / "settings.json"), {"avg_route_speed_kmh": 32.0})
    write(str(root / "model.json"), {"model": "gfs"})
    store.init()
    report = store.migrate_from_json(data_dir, frozenset({111}), extra_dirs=(str(root),),
                                     valid_model_keys=MODEL_KEYS)
    assert report["routes"] == 1 and report["users"] == 1
    assert list(store.routes_list(111)) == ["Мой"]
    assert store.prefs(111).avg_route_speed_kmh == 32.0
    assert store.prefs(111).model_key == "gfs"
    assert os.path.exists(str(root / "model.json.migrated"))


def test_data_dir_wins_over_the_extra_dir(store, data_dir, tmp_path):
    """Docker-путь не должен пострадать: личные файлы там лежат в томе."""
    root = tmp_path / "root"
    root.mkdir()
    write(os.path.join(data_dir, "model.json"), {"model": "icon"})
    write(str(root / "model.json"), {"model": "gfs"})
    store.init()
    store.migrate_from_json(data_dir, frozenset({111}), extra_dirs=(str(root),),
                                     valid_model_keys=MODEL_KEYS)
    assert store.prefs(111).model_key == "icon"
    assert os.path.exists(str(root / "model.json"))    # второй не тронут


def test_packaged_seed_is_not_eaten_by_migration(store, data_dir, tmp_path):
    """Упакованный sites.json лежит в корне репозитория под тем же именем.

    Съешь его миграцией — и он уедет в *.migrated; после пересборки образа
    файл вернётся, миграция прогонится снова и вернёт удалённые старты.
    """
    root = tmp_path / "root"
    root.mkdir()
    packaged = root / "sites.json"
    write(str(packaged), SITES_JSON)
    report = store.bootstrap(data_dir, frozenset(), str(packaged), extra_dirs=(str(root),),
                             valid_model_keys=MODEL_KEYS)
    assert os.path.exists(str(packaged))
    assert not os.path.exists(str(packaged) + ".migrated")
    assert report["sites"] == 1            # в БД попал засевом, а не переносом


# ------------------------- проверку модели нельзя пропустить, забыв параметр
#
# Первый заход на находку 7 сделал valid_model_keys необязательным
# (`=None` → «не проверять»). Проверку это давало только тому, кто о ней помнит:
# store.migrate_from_json(data_dir, {111}) без параметра писала «несуществующая»
# в колонку как есть, и дальше engine.model_id ронял KeyError на КАЖДОМ запросе
# этого пилота — навсегда, без способа вылечиться самому.

def test_model_validation_cannot_be_skipped_by_omitting_the_parameter():
    """Обязательный keyword-only у обеих функций — дефолт это и была дыра."""
    import inspect
    import store as st
    for fn in (st.migrate_from_json, st.bootstrap):
        p = inspect.signature(fn).parameters["valid_model_keys"]
        assert p.default is inspect.Parameter.empty, f"{fn.__name__}: снова с дефолтом"
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, f"{fn.__name__}: не keyword-only"


def test_migrate_without_model_keys_raises_type_error(store, data_dir):
    with pytest.raises(TypeError):
        store.migrate_from_json(data_dir, frozenset({111}))


def test_bootstrap_without_model_keys_raises_type_error(store, data_dir, tmp_path):
    packaged = tmp_path / "packaged.json"
    write(str(packaged), SITES_JSON)
    with pytest.raises(TypeError):
        store.bootstrap(data_dir, frozenset({111}), str(packaged))


def test_unknown_model_never_reaches_the_pilot(store, data_dir):
    """Сквозная проверка того самого отказа: после миграции ключ пилота обязан
    быть таким, который engine умеет превратить в id модели."""
    write(os.path.join(data_dir, "model.json"), {"model": "несуществующая"})
    store.init()
    report = store.migrate_from_json(data_dir, frozenset({111}),
                                     valid_model_keys=MODEL_KEYS)
    key = store.prefs(111).model_key
    assert key == store.DEFAULT_PREFS.model_key
    assert engine.model_id(key)              # не KeyError, как было на боевом ключе
    assert any("несуществующая" in d for d in report["dropped"]), report["dropped"]

"""Подготовка хранилища на старте бота: где ищем старые файлы и как кричим о потерях.

store.bootstrap здесь подменён намеренно: настоящий вызов пошёл бы искать
routes.json / settings.json / model.json в корне НАСТОЯЩЕГО репозитория и
переименовал бы их в *.migrated у того, у кого они там лежат. Проверяем именно
проводку — какие каталоги и какой список моделей уезжают в хранилище.
"""
import logging
import os

import pytest

import bot as botmod
import engine
import store

REPO_ROOT = os.path.dirname(os.path.abspath(engine.__file__))


@pytest.fixture()
def calls(monkeypatch):
    """Подменённый store.bootstrap: пишет аргументы, отдаёт заданный отчёт."""
    recorded = {}

    def fake(data_dir, allowed, packaged, **kw):
        recorded.update(data_dir=data_dir, allowed=allowed, packaged=packaged, **kw)
        return recorded.setdefault("report", {"sites": 0, "routes": 0, "users": 0,
                                              "skipped": [], "dropped": []})

    monkeypatch.setattr(store, "bootstrap", fake)
    return recorded


def _bot_warnings(caplog):
    """Только предупреждения самого бота: guards на каждом вызове ругается на
    пустой ALLOWED_USER_IDS, и этот шум к миграции отношения не имеет."""
    return [r.getMessage() for r in caplog.records
            if r.name == "pgbot" and r.levelno >= logging.WARNING]


def test_migration_also_looks_in_the_repo_root(calls):
    """Каталог БД при незаданном DB_PATH — это <repo>/data, а systemd-путь
    держал старые файлы в корне репозитория (дефолты ROUTES_FILE /
    SETTINGS_FILE / MODEL_FILE). Ищем в обоих местах, иначе личные маршруты и
    настройки такой установки не нашлись бы никогда."""
    botmod._bootstrap_store()
    assert REPO_ROOT in calls["extra_dirs"]
    assert calls["data_dir"] == os.path.dirname(store.DB_PATH)


def test_packaged_seed_path_is_still_the_repo_copy(calls):
    botmod._bootstrap_store()
    assert calls["packaged"] == os.path.join(REPO_ROOT, "sites.json")


def test_model_keys_are_handed_to_the_store(calls):
    """Список моделей — знание домена; хранилище его не держит, но без него
    неизвестный ключ из model.json доехал бы до колонки."""
    botmod._bootstrap_store()
    assert set(calls["valid_model_keys"]) == set(engine.MODELS)


def test_dropped_records_are_logged_loudly(calls, caplog):
    calls["report"] = {"sites": 1, "routes": 0, "users": 0, "skipped": [],
                       "dropped": ["sites.json: «Дыра» — NOT NULL constraint failed"]}
    with caplog.at_level(logging.WARNING, logger="pgbot"):
        botmod._bootstrap_store()
    warnings = _bot_warnings(caplog)
    assert warnings, "потеря записи прошла без предупреждения"
    assert any("Дыра" in w and "migrated" in w for w in warnings), warnings


def test_clean_migration_stays_quiet(calls, caplog):
    with caplog.at_level(logging.WARNING, logger="pgbot"):
        botmod._bootstrap_store()
    assert _bot_warnings(caplog) == []

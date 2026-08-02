"""Личные настройки через HTTP."""
import pytest

import engine
import store
from conftest import TEST_USER_ID
from tma import header


async def test_defaults_for_a_pilot_who_never_changed_anything(client):
    r = await client.get("/api/prefs", headers=header(uid=1))
    body = r.json()
    assert body["avg_route_speed_kmh"] == store.DEFAULT_PREFS.avg_route_speed_kmh
    assert body["wind_correction_enabled"] is True
    assert body["model_key"] == store.DEFAULT_PREFS.model_key


async def test_reading_prefs_creates_no_row(client):
    """Новый пилот ничего не регистрирует, чтобы посмотреть прогноз."""
    await client.get("/api/prefs", headers=header(uid=555))
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM user_prefs").fetchone()["c"] == 0


async def test_prefs_carry_the_model_list(client):
    """Список моделей приезжает вместе с настройками, а не отдельным запросом:
    выбиралка модели без подписей — это ключи вроде «icon» на экране."""
    body = (await client.get("/api/prefs", headers=header())).json()
    keys = [m["key"] for m in body["models"]]
    assert keys == ["auto", "ecmwf", "gfs", "icon"]
    assert all(m["label"] for m in body["models"])


async def test_prefs_name_the_ceiling_model(client):
    """Модель потолка термиков приезжает с настройками, а не пишется словом на
    экране.

    Мини-приложение объясняет пилоту, почему потолок не меняется вместе с
    выбранной моделью, и держало это объяснение копией константы: «всегда по
    GFS» стояло словом в четырёх местах TypeScript при одной
    engine.CEILING_MODEL_KEY в домене (финальное ревью ветки, I1). Ключ едет
    рядом с подписью — по нему приложение может отличить «потолок считается
    той же моделью, что и всё остальное» от «другой».
    """
    body = (await client.get("/api/prefs", headers=header())).json()
    assert body["ceiling_model"]["key"] == engine.CEILING_MODEL_KEY
    assert body["ceiling_model"]["label"] == engine.model_label(engine.CEILING_MODEL_KEY)
    assert body["ceiling_model"]["key"] in [m["key"] for m in body["models"]]


async def test_patch_speed(client):
    r = await client.patch("/api/prefs", json={"avg_route_speed_kmh": 32.0},
                           headers=header(uid=1))
    assert r.status_code == 200
    assert store.prefs(1).avg_route_speed_kmh == 32.0
    assert r.json()["avg_route_speed_kmh"] == 32.0, "ответ должен нести новое значение"


async def test_patch_answers_with_the_same_shape_as_get(client):
    """Ответ PATCH — это ПОЛНЫЕ настройки, как у GET, а не эхо присланного поля.

    Мини-приложение кладёт тело ответа PATCH прямо в свой кэш настроек
    (webapp/src/api/queries.ts: useUpdatePrefs → setQueryData) и не
    перезапрашивает их отдельным GET — так закрыто окно, в котором экран
    показывал прежнее значение, а нажатие, попавшее в это окно, отправляло его
    повторно. Цена решения: неполный ответ ляжет в кэш молча, и экран настроек
    упадёт на отсутствующем ключе (models), забрав с собой всё приложение —
    все четыре вкладки смонтированы одновременно. Контракт «PATCH отвечает тем
    же набором ключей, что и GET» до этого теста не проверял никто.
    """
    get_body = (await client.get("/api/prefs", headers=header(uid=1))).json()
    patch_body = (await client.patch("/api/prefs", json={"wind_correction_enabled": False},
                                     headers=header(uid=1))).json()
    assert patch_body.keys() == get_body.keys()
    # Список моделей — не просто ключ, а то, по чему приложение подписывает
    # выбранную модель: пустой или урезанный он так же ломает экран.
    assert patch_body["models"] == get_body["models"]


async def test_patch_wind_correction(client):
    await client.patch("/api/prefs", json={"wind_correction_enabled": False},
                       headers=header(uid=1))
    assert store.prefs(1).wind_correction_enabled is False


async def test_patch_model(client):
    await client.patch("/api/prefs", json={"model_key": "ecmwf"}, headers=header(uid=1))
    assert store.prefs(1).model_key == "ecmwf"


async def test_patch_touches_only_what_was_sent(client):
    """PATCH, а не PUT: приложение меняет один тумблер и не обязано присылать
    остальные — иначе оно молча затрёт их дефолтами."""
    store.set_speed(1, 30.0)
    await client.patch("/api/prefs", json={"model_key": "gfs"}, headers=header(uid=1))
    assert store.prefs(1).avg_route_speed_kmh == 30.0


async def test_speed_outside_the_range_is_400_with_the_domain_text(client):
    r = await client.patch("/api/prefs", json={"avg_route_speed_kmh": 500.0},
                           headers=header(uid=1))
    assert r.status_code == 400
    assert "скорость крыла" in r.text, "текст store уже написан для пилота"
    assert store.prefs(1).avg_route_speed_kmh == store.DEFAULT_PREFS.avg_route_speed_kmh


async def test_unknown_model_is_400(client):
    r = await client.patch("/api/prefs", json={"model_key": "нет-такой"},
                           headers=header(uid=1))
    assert r.status_code == 400
    assert store.prefs(1).model_key == store.DEFAULT_PREFS.model_key


async def test_prefs_are_personal(client):
    await client.patch("/api/prefs", json={"model_key": "icon"}, headers=header(uid=1))
    body = (await client.get("/api/prefs", headers=header(uid=2))).json()
    assert body["model_key"] == store.DEFAULT_PREFS.model_key, "настройки соседа"


async def test_a_rejected_patch_saves_nothing_at_all(client):
    """400 означает «не сохранилось ничего». Запись по мере разбора успевала
    сохранить скорость и падала на модели: ответ говорил «не принято», а
    половина настроек уже поменялась."""
    r = await client.patch("/api/prefs",
                           json={"avg_route_speed_kmh": 33.0,
                                 "wind_correction_enabled": False,
                                 "model_key": "нет-такой"},
                           headers=header(uid=1))
    assert r.status_code == 400
    p = store.prefs(1)
    assert p.avg_route_speed_kmh == store.DEFAULT_PREFS.avg_route_speed_kmh
    assert p.wind_correction_enabled is store.DEFAULT_PREFS.wind_correction_enabled


async def test_a_rejected_speed_leaves_the_other_fields_alone(client):
    """Вторая половина того же: падает не модель, а скорость."""
    r = await client.patch("/api/prefs",
                           json={"avg_route_speed_kmh": 500.0, "model_key": "gfs"},
                           headers=header(uid=1))
    assert r.status_code == 400
    assert store.prefs(1).model_key == store.DEFAULT_PREFS.model_key

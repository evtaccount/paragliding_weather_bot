"""Общая библиотека стартов через HTTP."""
import pytest

import store
from conftest import DEFAULT_SITES
from tma import header

NEW = {"name": "Казбеги", "lat": 42.66, "lon": 44.64, "elevation_m": 1750,
       "aspect": "Ю", "aspect_deg": 180.0, "aliases": ["kazbegi"], "notes": ""}


async def test_sites_lists_the_shared_library(client):
    body = (await client.get("/api/sites", headers=header())).json()
    assert [s["name"] for s in body] == [s["name"] for s in DEFAULT_SITES]


async def test_the_library_is_the_same_for_everyone(client):
    """Старты общие по решению: два пилота видят одно и то же."""
    a = (await client.get("/api/sites", headers=header(uid=1))).json()
    b = (await client.get("/api/sites", headers=header(uid=2))).json()
    assert a == b


async def test_add_a_site(client):
    r = await client.post("/api/sites", json=NEW, headers=header(uid=1))
    assert r.status_code == 201
    assert store.find_site("Казбеги") is not None


async def test_added_site_remembers_who_added_it(client):
    await client.post("/api/sites", json=NEW, headers=header(uid=77))
    with store.connect() as conn:
        row = conn.execute("SELECT added_by FROM sites WHERE name = ?",
                           ("Казбеги",)).fetchone()
    assert row["added_by"] == 77


async def test_adding_a_duplicate_name_is_409(client):
    await client.post("/api/sites", json=NEW, headers=header())
    r = await client.post("/api/sites", json=NEW, headers=header())
    assert r.status_code == 409


async def test_a_site_can_be_found_by_alias(client):
    body = (await client.get("/api/sites/гуда", headers=header())).json()
    assert body["name"] == "Гудаури"


async def test_unknown_site_is_404(client):
    assert (await client.get("/api/sites/нетутакого",
                             headers=header())).status_code == 404


async def test_delete_a_site(client):
    r = await client.delete("/api/sites/Гудаури", headers=header())
    assert r.status_code == 204
    assert store.find_site("Гудаури") is None


async def test_deleting_an_unknown_site_is_404(client):
    """204 на несуществующее имя соврал бы: пилот решил бы, что удалил старт,
    а на деле опечатался."""
    assert (await client.delete("/api/sites/нетутакого",
                                headers=header())).status_code == 404


async def test_a_site_name_that_breaks_buttons_is_400(client):
    """Имя приезжает в callback_data бота, у которой потолок 64 байта.
    Приложение и чат делят одну библиотеку, поэтому потолок общий."""
    r = await client.post("/api/sites", json={**NEW, "name": "я" * 40},
                          headers=header())
    assert r.status_code == 400
    assert store.load_sites() and len(store.load_sites()) == len(DEFAULT_SITES)


async def test_a_pipe_in_the_name_is_400(client):
    """`|` — разделитель полей в callback_data. Старт с таким именем не падает
    и не ругается: _split_cb получает лишнее поле, возвращает (None, None), и
    кнопки под этим стартом молча перестают работать навсегда."""
    r = await client.post("/api/sites", json={**NEW, "name": "Каз|беги"},
                          headers=header())
    assert r.status_code == 400
    assert store.find_site("Каз|беги") is None


async def test_elevation_by_coordinates(client, elevation):
    r = await client.post("/api/elevation", json={"lat": 42.5, "lon": 44.5},
                          headers=header())
    assert r.json()["elevation_m"] == 1234


async def test_elevation_needs_authorization(client, elevation):
    assert (await client.post("/api/elevation",
                              json={"lat": 42.5, "lon": 44.5})).status_code == 401

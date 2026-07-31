"""Разбор файлов маршрута и личные сохранённые маршруты."""
import pytest

import store
from tma import header

ROWS = [[42.4776, 44.4787, "старт"], [42.1176, 44.4787, "финиш"]]

# Байтовый литерал с кириллицей внутри b"""...""" не компилируется (bytes —
# только ASCII), поэтому текст собирается как str и кодируется в UTF-8.
GPX = """<?xml version="1.0"?>
<gpx version="1.1"><rte>
<rtept lat="42.4776" lon="44.4787"><name>старт</name></rtept>
<rtept lat="42.1176" lon="44.4787"><name>финиш</name></rtept>
</rte></gpx>""".encode()


# Путь один, тело всегда multipart: файл приезжает полем file, вставленный
# список координат — полем text. Два разных типа тела на одном пути FastAPI
# не различает, а второй путь ради текста удвоил бы контракт.
async def test_parse_text(client):
    r = await client.post("/api/route/parse",
                          data={"text": "42.4776, 44.4787, старт\n"
                                        "42.1176, 44.4787, финиш"},
                          headers=header())
    assert [p[0] for p in r.json()["points"]] == [42.4776, 42.1176]


async def test_parse_gpx_upload(client):
    r = await client.post("/api/route/parse",
                          files={"file": ("track.gpx", GPX, "application/gpx+xml")},
                          headers=header())
    assert len(r.json()["points"]) == 2


async def test_parse_kmz_is_refused_with_the_same_words_as_in_chat(client):
    """KMZ — архив. Приложение и чат обязаны объяснять это одинаково."""
    r = await client.post("/api/route/parse",
                          files={"file": ("track.kmz", b"PK\x03\x04", "application/kmz")},
                          headers=header())
    assert r.status_code == 400
    assert "распакуй" in r.text.lower()


async def test_parse_rejects_an_oversized_file(client):
    """Чужой трек на сотни тысяч точек не должен класть сервер — тот же потолок,
    что стоит в чате."""
    import route
    big = b"<gpx>" + b"x" * route.MAX_GPX_BYTES
    r = await client.post("/api/route/parse",
                          files={"file": ("big.gpx", big, "application/gpx+xml")},
                          headers=header())
    assert r.status_code == 400


async def test_parse_garbage_is_400_with_the_domain_text(client):
    r = await client.post("/api/route/parse", data={"text": "это не координаты"},
                          headers=header())
    assert r.status_code == 400


async def test_parse_without_input_is_400(client):
    assert (await client.post("/api/route/parse", data={},
                              headers=header())).status_code == 400


async def test_parse_saves_nothing(client):
    """Разбор — чистое преобразование: пилот ещё не решил сохранять."""
    await client.post("/api/route/parse",
                      files={"file": ("track.gpx", GPX, "application/gpx+xml")},
                      headers=header(uid=1))
    assert store.routes_list(1) == {}


async def test_routes_lists_only_your_own(client):
    store.route_save(1, "Мой", ROWS)
    store.route_save(2, "Чужой", ROWS)
    body = (await client.get("/api/routes", headers=header(uid=1))).json()
    assert [r["name"] for r in body] == ["Мой"]


async def test_save_a_route(client):
    r = await client.post("/api/routes", json={"name": "Мой", "points": ROWS},
                          headers=header(uid=1))
    assert r.status_code == 201
    assert store.route_rows(1, "Мой") == ROWS


async def test_saving_the_same_name_overwrites_and_says_so(client):
    store.route_save(1, "Мой", ROWS)
    r = await client.post("/api/routes",
                          json={"name": "Мой", "points": list(reversed(ROWS))},
                          headers=header(uid=1))
    assert r.json()["overwritten"] is True
    assert store.route_rows(1, "Мой")[0][0] == 42.1176


async def test_the_route_limit_is_enforced(client):
    for i in range(store.MAX_ROUTES):
        store.route_save(1, f"м{i}", ROWS)
    r = await client.post("/api/routes", json={"name": "ещё", "points": ROWS},
                          headers=header(uid=1))
    assert r.status_code == 400


async def test_delete_a_route(client):
    store.route_save(1, "Мой", ROWS)
    assert (await client.delete("/api/routes/Мой",
                                headers=header(uid=1))).status_code == 204
    assert store.routes_list(1) == {}


async def test_deleting_an_unknown_route_is_404(client):
    assert (await client.delete("/api/routes/нету",
                                headers=header(uid=1))).status_code == 404


async def test_you_cannot_delete_a_teammates_route(client):
    """Маршруты личные: чужое имя для тебя просто не существует."""
    store.route_save(2, "Чужой", ROWS)
    assert (await client.delete("/api/routes/Чужой",
                                headers=header(uid=1))).status_code == 404
    assert store.route_rows(2, "Чужой") == ROWS

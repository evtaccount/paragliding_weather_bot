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


async def test_added_by_is_not_in_the_create_response(client):
    """Telegram id того, кто завёл старт, — не дело клиента: библиотека общая
    на всех допущенных, и приложение открывают друзья владельца, а не он один.
    Применения этому полю у клиента нет (api._public_site)."""
    r = await client.post("/api/sites", json=NEW, headers=header(uid=77))
    assert "added_by" not in r.json()
    with store.connect() as conn:
        row = conn.execute("SELECT added_by FROM sites WHERE name = ?",
                           ("Казбеги",)).fetchone()
    assert row["added_by"] == 77  # в базе поле остаётся — как и задумано


async def test_added_by_is_not_in_the_list_response(client):
    await client.post("/api/sites", json=NEW, headers=header(uid=77))
    body = (await client.get("/api/sites", headers=header())).json()
    assert all("added_by" not in s for s in body)


async def test_added_by_is_not_in_the_single_site_response(client):
    await client.post("/api/sites", json=NEW, headers=header(uid=77))
    body = (await client.get("/api/sites/Казбеги", headers=header())).json()
    assert "added_by" not in body


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


async def test_an_empty_site_name_is_400(client):
    """store.name_error не проверял пустоту — та же дыра, что чинили для
    маршрутов (см. tests/test_api_routes_crud.py): пустое имя дало бы кнопку
    с пустым текстом, а библиотека стартов ОБЩАЯ — сломанная кнопка была бы
    видна каждому пилоту, а не только тому, кто её завёл."""
    r = await client.post("/api/sites", json={**NEW, "name": ""}, headers=header())
    assert r.status_code == 400
    assert store.load_sites() and len(store.load_sites()) == len(DEFAULT_SITES)


async def test_a_whitespace_only_site_name_is_400(client):
    r = await client.post("/api/sites", json={**NEW, "name": "   "}, headers=header())
    assert r.status_code == 400
    assert store.load_sites() and len(store.load_sites()) == len(DEFAULT_SITES)


async def test_impossible_latitude_is_400(client):
    """bot.py проверяет -90..90/-180..180 в двух местах (cmd_add, parse_coords);
    приложение делило с ними общую библиотеку стартов, но не саму проверку —
    старт с lat=999 попадал бы в /sites у каждого пилота и в failed
    scan_week навсегда."""
    r = await client.post("/api/sites", json={**NEW, "lat": 999.0}, headers=header())
    assert r.status_code == 400
    assert store.find_site("Казбеги") is None


async def test_impossible_longitude_is_400(client):
    r = await client.post("/api/sites", json={**NEW, "lon": -4000.0}, headers=header())
    assert r.status_code == 400
    assert store.find_site("Казбеги") is None


async def test_valid_coordinates_still_create_a_site(client):
    r = await client.post("/api/sites", json=NEW, headers=header())
    assert r.status_code == 201


async def test_a_pipe_in_the_name_is_400(client):
    """`|` — разделитель полей в callback_data. Старт с таким именем не падает
    и не ругается: _split_cb получает лишнее поле, возвращает (None, None), и
    кнопки под этим стартом молча перестают работать навсегда."""
    r = await client.post("/api/sites", json={**NEW, "name": "Каз|беги"},
                          headers=header())
    assert r.status_code == 400
    assert store.find_site("Каз|беги") is None


async def test_a_huge_note_is_400(client):
    """Библиотека общая и целиком уезжает КАЖДОМУ пилоту при КАЖДОМ открытии
    приложения. Один запрос с notes на 5 000 000 символов проходил с 201,
    после чего GET /api/sites весил 10 269 330 байт вместо 293 — и эти
    десять мегабайт качал бы каждый с мобильного интернета в горах, ради чего
    приложение и делалось (финальное ревью ветки, безопасность, I3). Из чата
    это было недостижимо: bot.cmd_add notes не задаёт вовсе."""
    r = await client.post("/api/sites",
                          json={**NEW, "notes": "я" * (store.NOTES_MAX_CHARS + 1)},
                          headers=header())
    assert r.status_code == 400
    assert store.find_site("Казбеги") is None


async def test_a_pile_of_aliases_is_400(client):
    r = await client.post("/api/sites",
                          json={**NEW, "aliases": [f"a{i}" for i in range(store.MAX_ALIASES + 1)]},
                          headers=header())
    assert r.status_code == 400
    assert store.find_site("Казбеги") is None


async def test_an_alias_is_held_to_the_same_rules_as_a_name(client):
    """find_site ищет и по имени, и по псевдониму: псевдоним — это второе имя
    старта, и в кнопки чата он попадает так же."""
    r = await client.post("/api/sites", json={**NEW, "aliases": ["я" * 40]},
                          headers=header())
    assert r.status_code == 400
    assert store.find_site("Казбеги") is None


@pytest.mark.parametrize("field,value", [
    ("elevation_m", 10**18),
    ("aspect_deg", 1e308),
    ("slope_deg", -5000.0),
    ("route_top_m", 10**9),
])
async def test_impossible_numbers_are_400(client, field, value):
    """Все четыре приняты живым сервером в ревью. Высота и уклон едут прямо в
    расчёт (engine.slope_sun_index, вето «база ниже вершин маршрута»), и
    старт с ними торчал бы у каждого пилота в /sites и в failed у scan_week."""
    r = await client.post("/api/sites", json={**NEW, field: value}, headers=header())
    assert r.status_code == 400, r.text
    assert store.find_site("Казбеги") is None


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
async def test_non_finite_numbers_are_400_and_never_come_back(client, literal):
    """Числа, которых нет: json их разбирает, pydantic отвергает, а штатный
    обработчик FastAPI клал отвергнутое значение обратно в ответ — и на
    сериализации ответа падал сам (json.dumps(allow_nan=False)).

    Воспроизведено на всех трёх литералах: было 500 и двухэкранная трасса в
    логе на каждую попытку, при том что три остальных числовых поля отвечали
    чистым 400 (финальное ревью ветки, круг 2, I5). Достижимо без злого
    умысла — высоту в форму подставляет POST /api/elevation.

    Тело собирается строкой: httpx сериализует `json=` через json.dumps с
    allow_nan=False и упал бы раньше сервера, не отправив запрос.
    """
    raw = ('{"name": "Казбеги", "lat": 42.66, "lon": 44.64, "elevation_m": %s}'
           % literal)
    r = await client.post("/api/sites", content=raw,
                          headers={**header(), "content-type": "application/json"})
    assert r.status_code == 400, r.text
    assert "elevation_m" in r.json()["detail"]
    # Отвергнутое значение не возвращается отправителю ни в каком виде.
    assert "nan" not in r.text.lower() and "infinity" not in r.text.lower(), r.text
    assert store.find_site("Казбеги") is None


async def test_a_refused_body_does_not_echo_what_was_sent(client):
    """Тот же обработчик, обычный отказ разбора: наружу уходят имена полей, а
    не присланные значения. Штатный обработчик отвечал 422 и возвращал `input`
    целиком — то есть отправитель мог получить обратно ровно столько байт,
    сколько прислал (см. store.details_error про ту же цену)."""
    raw = ('{"name": "Казбеги", "lat": 42.66, "lon": 44.64, '
           '"elevation_m": "%s"}' % ("высоко" * 1000))
    r = await client.post("/api/sites", content=raw,
                          headers={**header(), "content-type": "application/json"})
    assert r.status_code == 400, r.text
    assert "высоко" not in r.text
    assert len(r.text) < 200, len(r.text)


async def test_a_wordy_aspect_is_400(client):
    """Румб — метка из 1–3 букв (engine.card, webapp/src/format.ts). Живой
    сервер принимал aspect = «не сторона света»."""
    r = await client.post("/api/sites", json={**NEW, "aspect": "не сторона света"},
                          headers=header())
    assert r.status_code == 400
    assert store.find_site("Казбеги") is None


async def test_a_normal_note_and_aliases_still_pass(client):
    """Потолки не должны отсекать то, ради чего поля заведены: заметка в
    абзац и пара псевдонимов — обычный старт из sites.json."""
    r = await client.post("/api/sites",
                          json={**NEW, "notes": "Восточная Грузия. Экспозиция южная." * 3,
                                "aliases": ["kazbegi", "казбек"]},
                          headers=header())
    assert r.status_code == 201, r.text
    assert store.find_site("казбек") is not None


async def test_elevation_by_coordinates(client, elevation):
    r = await client.post("/api/elevation", json={"lat": 42.5, "lon": 44.5},
                          headers=header())
    assert r.json()["elevation_m"] == 1234


async def test_elevation_needs_authorization(client, elevation):
    assert (await client.post("/api/elevation",
                              json={"lat": 42.5, "lon": 44.5})).status_code == 401

"""Команды сохранённых маршрутов."""
import datetime as dt

import pytest

import engine
import forecast
import route
import store
from conftest import TEST_USER_ID
from fixtures import om_route
from tg import buttons, callback_update, keyboards, text_update, texts

BODY = ("/route\n"
        "42.4776, 44.4787, старт\n"
        "42.1176, 44.4787, финиш")
PTS = [route.Point(42.4776, 44.4787, "старт"), route.Point(42.1176, 44.4787, "финиш")]
ROWS = [[p.lat, p.lon, p.name] for p in PTS]


def save(name, rows=None):
    store.route_save(TEST_USER_ID, name, rows or ROWS)


def saved():
    return store.routes_list(TEST_USER_ID)


def _n(url):
    return url.split("latitude=")[1].split("&")[0].count(",") + 1


@pytest.fixture()
def api(monkeypatch):
    async def fake_weather(url):
        return om_route(_n(url))

    async def fake_terrain(coords):
        return [1000.0] * len(coords)

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)


async def test_saveroute_without_a_computed_route_says_so(feed, session):
    await feed(text_update("/saveroute Гудаури"))
    assert "/route" in texts(session)[-1]


async def test_saveroute_stores_the_last_computed_route(feed, session, api):
    await feed(text_update(BODY))
    await feed(text_update("/saveroute Гудаури"))
    assert store.route_rows(TEST_USER_ID, "Гудаури") is not None
    assert "Гудаури" in texts(session)[-1]


async def test_saveroute_over_a_corrupt_route_says_overwritten(feed, session, api):
    """Занятое имя с нечитаемым points — всё равно «Перезаписал».

    routes_list() битую запись пропускает, поэтому проверка занятости по нему
    сказала бы «нет» и бот отчитался бы «Сохранил», хотя чужие точки исчезли.
    """
    with store.connect() as conn:
        conn.execute("INSERT INTO routes (user_id, name, points, saved_at)"
                     " VALUES (?,?,?,?)", (TEST_USER_ID, "Гудаури", "{битый", "2026-07-29"))
    await feed(text_update(BODY))
    await feed(text_update("/saveroute Гудаури"))
    assert texts(session)[-1].startswith("Перезаписал")
    assert store.route_rows(TEST_USER_ID, "Гудаури") == ROWS


async def test_saveroute_needs_a_name(feed, session, api):
    await feed(text_update(BODY))
    await feed(text_update("/saveroute"))
    assert saved() == {}


async def test_saveroute_refuses_too_many_points(feed, session):
    """Потолок числа точек. Разборщики маршрута до кэша столько не пропустят,
    поэтому запрос кладём в кэш напрямую — проверяем именно страховку /saveroute.
    """
    import bot as botmod
    long_route = [route.Point(42.0 + i / 1000.0, 44.0) for i in range(route.MAX_POINTS + 1)]
    botmod._remember_route(long_route, None, "2026-07-29", None)
    await feed(text_update("/saveroute Длинный"))
    assert "слишком много точек" in texts(session)[-1]
    assert saved() == {}


async def test_saveroute_refuses_a_name_that_breaks_buttons(feed, session, api):
    await feed(text_update(BODY))
    await feed(text_update("/saveroute " + "я" * 40))
    assert saved() == {}
    assert "❌" in texts(session)[-1]


async def test_routes_lists_what_is_saved(feed, session):
    save("Гудаури")
    await feed(text_update("/routes"))
    out = texts(session)[-1]
    assert "Гудаури" in out and "км" in out


async def test_routes_shows_a_date_not_a_timestamp(feed, session):
    """Regression for review finding 2. store хранит saved_at полным ISO-
    таймстампом (store._now()); удалённый routes.py показывал в /routes только
    дату сохранения (dt.date.today().isoformat()) — не время. Пилоту время не
    нужно, а строка вида «...2026-07-29T12:18:55+00:00» выглядит как баг."""
    save("Гудаури")
    await feed(text_update("/routes"))
    line = next(l for l in texts(session)[-1].splitlines() if "Гудаури" in l)
    assert line.endswith(dt.date.today().isoformat())
    assert "T" not in line


async def test_routes_offers_a_button_per_route(feed, session):
    save("Гудаури")
    await feed(text_update("/routes"))
    assert [b.callback_data for b in buttons(keyboards(session)[-1])] == ["rr|Гудаури"]


async def test_routes_when_empty_points_at_saveroute(feed, session):
    await feed(text_update("/routes"))
    assert "/saveroute" in texts(session)[-1]


async def test_the_button_computes_the_saved_route(feed, session, api):
    save("Гудаури")
    await feed(callback_update("rr|Гудаури"))
    assert any("Гудаури" in t for t in texts(session))


async def test_delroute_removes_it(feed, session):
    save("Гудаури")
    await feed(text_update("/delroute Гудаури"))
    assert saved() == {}


async def test_delroute_of_an_unknown_name_lists_the_known_ones(feed, session):
    save("Гудаури")
    await feed(text_update("/delroute Казбеги"))
    assert "Гудаури" in texts(session)[-1]


async def test_route_by_saved_name(feed, session, api):
    save("Гудаури")
    await feed(text_update("/route Гудаури"))
    assert any("🗺" in t for t in texts(session))


async def test_route_by_saved_name_with_date_and_time(feed, session, api):
    save("Гудаури")
    await feed(text_update("/route Гудаури завтра 11:30"))
    card = next(t for t in texts(session) if "🗺" in t)
    assert "11:30" in card
    # engine.fmt_date не паддирует число месяца: используем {d.day}, не strftime("%d"),
    # поэтому 1–9 числа в карточке без нулей (1 авг, не 01 авг).
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    assert engine.fmt_date(tomorrow) in card


async def test_a_multi_word_name_still_resolves(feed, session, api):
    """Имя из нескольких слов — обычное дело: «Гудаури Пасанаури»."""
    save("Гудаури Пасанаури")
    await feed(text_update("/route Гудаури Пасанаури завтра"))
    assert any("🗺" in t for t in texts(session))


async def test_an_unknown_name_falls_back_to_the_help(feed, session):
    await feed(text_update("/route Казбеги"))
    assert "координат" in texts(session)[-1]

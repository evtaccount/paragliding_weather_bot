"""Команды сохранённых маршрутов."""
import datetime as dt

import pytest

import forecast
import route
import routes
from fixtures import om_route
from tg import buttons, callback_update, keyboards, text_update, texts

BODY = ("/route\n"
        "42.4776, 44.4787, старт\n"
        "42.1176, 44.4787, финиш")
PTS = [route.Point(42.4776, 44.4787, "старт"), route.Point(42.1176, 44.4787, "финиш")]


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
    assert routes.get("Гудаури") is not None
    assert "Гудаури" in texts(session)[-1]


async def test_saveroute_needs_a_name(feed, session, api):
    await feed(text_update(BODY))
    await feed(text_update("/saveroute"))
    assert routes.list_all() == {}


async def test_saveroute_refuses_a_name_that_breaks_buttons(feed, session, api):
    await feed(text_update(BODY))
    await feed(text_update("/saveroute " + "я" * 40))
    assert routes.list_all() == {}
    assert "❌" in texts(session)[-1]


async def test_routes_lists_what_is_saved(feed, session):
    routes.save("Гудаури", PTS)
    await feed(text_update("/routes"))
    out = texts(session)[-1]
    assert "Гудаури" in out and "км" in out


async def test_routes_offers_a_button_per_route(feed, session):
    routes.save("Гудаури", PTS)
    await feed(text_update("/routes"))
    assert [b.callback_data for b in buttons(keyboards(session)[-1])] == ["rr|Гудаури"]


async def test_routes_when_empty_points_at_saveroute(feed, session):
    await feed(text_update("/routes"))
    assert "/saveroute" in texts(session)[-1]


async def test_the_button_computes_the_saved_route(feed, session, api):
    routes.save("Гудаури", PTS)
    await feed(callback_update("rr|Гудаури"))
    assert any("Гудаури" in t for t in texts(session))


async def test_delroute_removes_it(feed, session):
    routes.save("Гудаури", PTS)
    await feed(text_update("/delroute Гудаури"))
    assert routes.list_all() == {}


async def test_delroute_of_an_unknown_name_lists_the_known_ones(feed, session):
    routes.save("Гудаури", PTS)
    await feed(text_update("/delroute Казбеги"))
    assert "Гудаури" in texts(session)[-1]


async def test_route_by_saved_name(feed, session, api):
    routes.save("Гудаури", PTS)
    await feed(text_update("/route Гудаури"))
    assert any("🗺" in t for t in texts(session))


async def test_route_by_saved_name_with_date_and_time(feed, session, api):
    routes.save("Гудаури", PTS)
    await feed(text_update("/route Гудаури завтра 11:30"))
    card = next(t for t in texts(session) if "🗺" in t)
    assert "11:30" in card
    assert (dt.date.today() + dt.timedelta(days=1)).strftime("%d") in card


async def test_a_multi_word_name_still_resolves(feed, session, api):
    """Имя из нескольких слов — обычное дело: «Гудаури Пасанаури»."""
    routes.save("Гудаури Пасанаури", PTS)
    await feed(text_update("/route Гудаури Пасанаури завтра"))
    assert any("🗺" in t for t in texts(session))


async def test_an_unknown_name_falls_back_to_the_help(feed, session):
    await feed(text_update("/route Казбеги"))
    assert "координат" in texts(session)[-1]

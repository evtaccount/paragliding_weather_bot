"""Кнопки под карточкой маршрута и токен, который их обслуживает."""
import pytest

import bot as botmod
import forecast
import route
from fixtures import om_route
from tg import (buttons, callback_update, cb_answers, keyboards, photos,
                text_update, texts)

BODY = ("/route\n"
        "42.4776, 44.4787, старт\n"
        "42.1176, 44.4787, финиш")


def _n(url):
    return url.split("latitude=")[1].split("&")[0].count(",") + 1


@pytest.fixture()
def api(monkeypatch):
    calls = {"weather": 0, "terrain": 0}

    async def fake_weather(url):
        calls["weather"] += 1
        return om_route(_n(url))

    async def fake_terrain(coords):
        calls["terrain"] += 1
        return [1000.0] * len(coords)

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)
    return calls


def _last_token():
    return next(reversed(botmod._route_cache))


async def test_card_comes_with_a_keyboard(feed, session, api):
    await feed(text_update(BODY))
    assert keyboards(session), "под карточкой маршрута нет кнопок"


async def test_keyboard_has_point_buttons_and_actions(feed, session, api):
    await feed(text_update(BODY))
    labels = [b.text for b in buttons(keyboards(session)[-1])]
    assert any("△" in t for t in labels)
    assert any("⚑" in t for t in labels)
    assert any("Разрез" in t for t in labels)
    assert any("Другое время" in t for t in labels)


async def test_every_callback_data_fits_telegram(feed, session, api):
    await feed(text_update(BODY))
    for b in buttons(keyboards(session)[-1]):
        assert len(b.callback_data.encode("utf-8")) <= 64


async def test_the_token_remembers_the_request_not_the_answer(feed, api):
    await feed(text_update(BODY))
    entry = botmod._route_cache[_last_token()]
    assert set(entry) == {"points", "name", "date", "departure"}
    assert all(isinstance(p, route.Point) for p in entry["points"])


async def test_the_cache_has_a_ceiling(feed, api):
    for _ in range(botmod._ROUTE_CACHE_MAX + 3):
        await feed(text_update(BODY))
    assert len(botmod._route_cache) == botmod._ROUTE_CACHE_MAX


async def test_the_analysis_button_is_hidden_without_a_key(feed, session, api):
    """Кнопка, которая всегда отвечает «недоступно», хуже отсутствующей кнопки."""
    await feed(text_update(BODY))
    labels = [b.text for b in buttons(keyboards(session)[-1])]
    assert not any("Разбор" in t for t in labels)


async def test_the_analysis_button_appears_with_a_key(feed, session, api, monkeypatch):
    monkeypatch.setattr(botmod.analysis, "available", lambda: True)
    await feed(text_update(BODY))
    labels = [b.text for b in buttons(keyboards(session)[-1])]
    assert any("Разбор" in t for t in labels)


# ---------------------------------------------------------------- карточка точки
async def test_a_point_button_answers_with_the_point_card(feed, session, api):
    await feed(text_update(BODY))
    await feed(callback_update(f"rt|{_last_token()}|pt|0"))
    assert any("📍" in t for t in texts(session))


async def test_the_point_card_costs_no_new_api_calls(feed, api):
    """Погода уже в кэше: кнопка не должна ходить в open-meteo заново."""
    await feed(text_update(BODY))
    before = dict(api)
    await feed(callback_update(f"rt|{_last_token()}|pt|0"))
    assert api == before


async def test_a_lost_token_says_so_instead_of_going_quiet(feed, session, api):
    await feed(callback_update("rt|неттакого|pt|0"))
    assert cb_answers(session)
    assert "устарел" in cb_answers(session)[-1].text


async def test_an_unknown_kilometre_is_reported(feed, session, api):
    await feed(text_update(BODY))
    await feed(callback_update(f"rt|{_last_token()}|pt|999"))
    assert "не найдена" in texts(session)[-1]


# ---------------------------------------------------------------- разрез
async def test_the_section_button_sends_a_photo(feed, session, api):
    await feed(text_update(BODY))
    await feed(callback_update(f"rt|{_last_token()}|sec"))
    assert photos(session)


async def test_the_section_costs_no_new_api_calls(feed, api):
    """Погода уже в кэше: кнопка не должна ходить в open-meteo заново."""
    await feed(text_update(BODY))
    before = dict(api)
    await feed(callback_update(f"rt|{_last_token()}|sec"))
    assert api == before


async def test_without_terrain_the_button_explains_itself(feed, session, monkeypatch):
    async def fake_weather(url):
        return om_route(_n(url))

    async def no_terrain(coords):
        return None

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", no_terrain)
    await feed(text_update(BODY))
    await feed(callback_update(f"rt|{_last_token()}|sec"))
    assert "рельеф" in texts(session)[-1].lower()
    assert not photos(session)


async def test_a_lost_token_on_the_section_button_says_so(feed, session, api):
    await feed(callback_update("rt|неттакого|sec"))
    assert "устарел" in texts(session)[-1]


# ---------------------------------------------------------------- время вылета
async def test_the_departure_button_offers_times(feed, session, api):
    await feed(text_update(BODY))
    await feed(callback_update(f"rt|{_last_token()}|dep"))
    labels = [b.text for b in buttons(keyboards(session)[-1])]
    assert any(":" in t for t in labels)


async def test_picking_a_time_recomputes_the_card(feed, session, api):
    await feed(text_update(BODY))
    await feed(callback_update(f"rt|{_last_token()}|dep|13:00"))
    card = [t for t in texts(session) if "🗺" in t][-1]
    assert "13:00" in card


async def test_the_recomputed_card_keeps_its_buttons(feed, session, api):
    await feed(text_update(BODY))
    await feed(callback_update(f"rt|{_last_token()}|dep|13:00"))
    assert any("Разрез" in b.text for b in buttons(keyboards(session)[-1]))


async def test_the_time_list_is_capped(feed, session, api):
    """Скан даёт два десятка вариантов; клавиатура из двадцати кнопок нечитаема."""
    await feed(text_update(BODY))
    await feed(callback_update(f"rt|{_last_token()}|dep"))
    assert len(buttons(keyboards(session)[-1])) <= botmod._DEPARTURE_BUTTONS


async def test_completable_times_are_marked(feed, session, api):
    await feed(text_update(BODY))
    await feed(callback_update(f"rt|{_last_token()}|dep"))
    labels = [b.text for b in buttons(keyboards(session)[-1])]
    assert any("🟢" in t or "·" in t for t in labels)


async def test_a_lost_token_on_the_departure_button_says_so(feed, session, api):
    await feed(callback_update("rt|неттакого|dep"))
    assert "устарел" in cb_answers(session)[-1].text

"""Показ ИИ-разбора маршрута."""
import pytest

import analysis
import bot as botmod
import forecast
import route
from fixtures import om_route
from tg import callback_update, text_update, texts

BODY = ("/route\n"
        "42.4776, 44.4787, старт\n"
        "42.1176, 44.4787, финиш")

ANSWER = {"points": [{"km": 0.0, "comment": "старт чистый, день открывается"}],
          "summary": {"verdict": "Маршрут проходится.",
                      "bottleneck_note": "Перевал на 20 км.",
                      "tactical_note": ""}}


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
    monkeypatch.setattr(analysis, "available", lambda: True)


def _last_token():
    return next(reversed(botmod._route_cache))


# ---------------------------------------------------------------- отрисовка текста
def test_render_puts_the_verdict_first():
    text = route.render_analysis(ANSWER)
    assert text.index("Маршрут проходится") < text.index("Перевал")


def test_render_skips_empty_summary_fields():
    """«Тактика: —» читается как совет, которого нет, а не как его отсутствие."""
    assert "Тактика" not in route.render_analysis(ANSWER)


def test_render_lists_point_comments_with_kilometres():
    assert "0 км · старт чистый" in route.render_analysis(ANSWER)


def test_render_of_an_empty_answer_does_not_crash():
    assert route.render_analysis({"points": [], "summary": {}})


def test_render_shows_the_tactical_note_when_there_is_one():
    a = {"points": [], "summary": {"verdict": "в", "bottleneck_note": None,
                                   "tactical_note": "вылетать раньше"}}
    assert "Тактика: вылетать раньше" in route.render_analysis(a)


# ---------------------------------------------------------------- кнопка
async def test_the_button_shows_the_analysis(feed, session, api, monkeypatch):
    monkeypatch.setattr(analysis, "analyze_route", lambda facts: ANSWER)
    await feed(text_update(BODY))
    await feed(callback_update(f"rt|{_last_token()}|ai"))
    assert any("🤖" in t for t in texts(session))


async def test_the_model_gets_the_computed_block(feed, api, monkeypatch):
    seen = {}

    def capture(facts):
        seen.update(facts)
        return ANSWER

    monkeypatch.setattr(analysis, "analyze_route", capture)
    await feed(text_update(BODY))
    await feed(callback_update(f"rt|{_last_token()}|ai"))
    assert all("computed" in p for p in seen["points"])


async def test_a_gemini_failure_leaves_the_card_alone(feed, session, api, monkeypatch):
    def boom(facts):
        raise RuntimeError("все модели Gemini недоступны")

    monkeypatch.setattr(analysis, "analyze_route", boom)
    await feed(text_update(BODY))
    await feed(callback_update(f"rt|{_last_token()}|ai"))
    assert "не получился" in texts(session)[-1]
    assert any("🗺" in t for t in texts(session))


async def test_a_broken_answer_is_reported_not_shown(feed, session, api, monkeypatch):
    monkeypatch.setattr(analysis, "analyze_route", lambda facts: "не json")
    await feed(text_update(BODY))
    await feed(callback_update(f"rt|{_last_token()}|ai"))
    assert "не получился" in texts(session)[-1]


async def test_a_wrong_sign_comment_never_reaches_the_pilot(feed, session, api,
                                                            monkeypatch):
    """Сквозная проверка: карточка показана, а опасный комментарий отсеян."""
    async def get_route_capture(points, name, date, departure_h=None):
        p = await orig(points, name, date, departure_h)
        p["points"][0]["wind_along_kmh"] = -12.0    # встречный на старте
        return p

    orig = forecast.get_route
    monkeypatch.setattr(forecast, "get_route", get_route_capture)
    monkeypatch.setattr(analysis, "analyze_route", lambda facts: {
        "points": [{"km": 0.0, "comment": "попутный поможет добить плечо"}],
        "summary": {"verdict": "вердикт", "bottleneck_note": "",
                    "tactical_note": ""}})
    await feed(text_update(BODY))
    await feed(callback_update(f"rt|{_last_token()}|ai"))
    assert not any("попутный" in t for t in texts(session))


async def test_without_a_key_the_button_says_so(feed, session, monkeypatch):
    async def fake_weather(url):
        return om_route(_n(url))

    async def fake_terrain(coords):
        return [1000.0] * len(coords)

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)
    monkeypatch.setattr(analysis, "available", lambda: True)
    await feed(text_update(BODY))
    token = _last_token()
    monkeypatch.setattr(analysis, "available", lambda: False)
    await feed(callback_update(f"rt|{token}|ai"))
    assert "GEMINI_API_KEY" in texts(session)[-1]


async def test_a_lost_token_on_the_analysis_button_says_so(feed, session, api):
    await feed(callback_update("rt|неттакого|ai"))
    assert "устарел" in texts(session)[-1]

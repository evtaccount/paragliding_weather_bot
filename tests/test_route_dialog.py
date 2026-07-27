"""Команда /route: текстовый ввод, разбор даты и времени, ошибки."""
import datetime as dt

import pytest

import forecast
from tg import text_update, texts


@pytest.fixture()
def route_calls(monkeypatch):
    calls = []

    async def fake(points, name, date, departure_h=None):
        calls.append((len(points), name, date, departure_h))
        return {"route": {"name": name or "Маршрут", "date": date, "departure": "11:00",
                          "total_km": 40.0, "sample_step_km": 10.0, "sample_count": 5,
                          "model": "Auto", "avg_route_speed_kmh": 25.0,
                          "wind_correction_enabled": True},
                "points": [], "notes": []}

    monkeypatch.setattr(forecast, "get_route", fake)
    monkeypatch.setattr("route.render_card", lambda p: "КАРТОЧКА МАРШРУТА")
    return calls


async def test_text_route_is_parsed_and_sent(feed, session, route_calls):
    await feed(text_update("/route\n42.4776, 44.4787\n42.2104, 44.6890"))
    assert route_calls[0][0] == 2
    assert "КАРТОЧКА МАРШРУТА" in texts(session)[-1]


async def test_tomorrow_keyword(feed, route_calls):
    await feed(text_update("/route завтра\n42.4776, 44.4787\n42.2104, 44.6890"))
    assert route_calls[0][2] == (dt.date.today() + dt.timedelta(days=1)).isoformat()


async def test_explicit_date_and_time(feed, route_calls):
    await feed(text_update("/route 2026-07-28 11:30\n42.4776, 44.4787\n42.2104, 44.6890"))
    assert route_calls[0][2] == "2026-07-28"
    assert route_calls[0][3] == pytest.approx(11.5)


async def test_bad_line_is_reported_with_its_number(feed, session, route_calls):
    await feed(text_update("/route\n42.4776, 44.4787\nсюда попал текст"))
    assert not route_calls
    assert "строка 3" in texts(session)[-1]


async def test_route_without_points_explains_the_format(feed, session, route_calls):
    await feed(text_update("/route"))
    assert not route_calls
    assert "42." in texts(session)[-1]     # в подсказке есть пример


async def test_forecast_error_is_shown_to_the_user(feed, session, monkeypatch):
    async def failing(points, name, date, departure_h=None):
        raise forecast.ForecastError("Прогноз доступен с ... по ...")

    monkeypatch.setattr(forecast, "get_route", failing)
    await feed(text_update("/route\n42.4776, 44.4787\n42.2104, 44.6890"))
    assert "Прогноз доступен" in texts(session)[-1]

"""Команда /route: текстовый ввод, разбор даты и времени, ошибки."""
import datetime as dt

import pytest
from aiogram import Bot

import forecast
from tg import document_update, text_update, texts


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


# ---------------------------------------------------------------- файлы маршрутов
GPX = ('<gpx><rte><name>тур</name>'
       '<rtept lat="42.4776" lon="44.4787"/>'
       '<rtept lat="42.1176" lon="44.4787"/></rte></gpx>')
KML = ("<kml><Document><name>тур</name><Placemark><LineString><coordinates>"
       "44.4787,42.4776 44.4787,42.1176</coordinates></LineString>"
       "</Placemark></Document></kml>")


@pytest.fixture()
def downloads(monkeypatch):
    """Подменяет скачивание файла: Telegram отдаёт file_id, а не содержимое."""
    payload = {"data": b""}

    async def fake_download(self, file, destination=None, **kw):
        destination.write(payload["data"])

    monkeypatch.setattr(Bot, "download", fake_download)
    return payload


async def test_a_gpx_document_is_parsed(feed, session, downloads, route_calls):
    downloads["data"] = GPX.encode()
    await feed(document_update("route.gpx"))
    assert route_calls[0][0] == 2


async def test_a_kml_document_is_parsed(feed, session, downloads, route_calls):
    """KML-файл маршрута обрабатывается так же, как GPX."""
    downloads["data"] = KML.encode()
    await feed(document_update("route.kml"))
    assert route_calls[0][:2] == (2, "тур")


async def test_a_document_caption_carries_date_and_time(feed, downloads, route_calls):
    downloads["data"] = KML.encode()
    await feed(document_update("route.kml", caption="завтра 11:30"))
    assert route_calls[0][3] == pytest.approx(11.5)


async def test_a_kmz_document_is_refused_with_advice(feed, session, downloads):
    await feed(document_update("route.kmz"))
    assert ".kml" in texts(session)[-1]


async def test_an_unknown_extension_names_both_formats(feed, session, downloads):
    await feed(document_update("route.txt"))
    assert "GPX" in texts(session)[-1] and "KML" in texts(session)[-1]


async def test_an_oversized_document_is_refused_before_download(feed, session, downloads):
    import route as route_mod
    await feed(document_update("route.kml", file_size=route_mod.MAX_GPX_BYTES + 1))
    assert "КБ" in texts(session)[-1]


async def test_a_broken_document_is_reported(feed, session, downloads, route_calls):
    downloads["data"] = b"<kml><Document>"
    await feed(document_update("route.kml"))
    assert not route_calls
    assert "❌" in texts(session)[-1]

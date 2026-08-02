"""Потолок тела запроса: большое тело не оплачивается памятью процесса.

FastAPI решает Depends(current_user) уже после того, как прочитал тело
целиком, поэтому без потолка неавторизованный POST стоит серверу ровно
столько, сколько прислали, — и только потом уходит 401. Замерено на живом
сервере (финальное ревью ветки, безопасность, I1): 800 МБ JSON без заголовка
Authorization подняли RSS процесса с 38 до 635 МБ; multipart на 600 МБ
вырастил временный файл до 594 МБ. Процесс один на чат и HTTP (app.py), так
что это уносит и бота в чате.
"""
import api
import route
from tma import header


def _oversized() -> bytes:
    return b"x" * (api.MAX_BODY_BYTES + 1)


async def test_body_over_the_cap_is_413_without_authorization(client):
    """Отказ ДО проверки подписи — в этом весь смысл: посторонний не должен
    получать возможность занять память процесса ценой одного запроса."""
    r = await client.post("/api/routes", content=_oversized(),
                          headers={"content-type": "application/json"})
    assert r.status_code == 413


async def test_an_oversized_body_is_not_read_into_the_process(client):
    """Content-Length разбирается ДО чтения тела: сервер отвечает, не приняв
    ни байта. Проверяется тем, что генератор тела так и не был прокручен.

    Тело собирается по кускам, а не одним куском: httpx на генераторе не
    ставит Content-Length вовсе (Transfer-Encoding: chunked) — и это второй
    путь, которым сюда приходят: у chunked-тела заявленного размера нет, и
    ловит его только счётчик в обёртке receive.
    """
    chunk = b"x" * 65536
    sent = []

    async def body():
        for _ in range((api.MAX_BODY_BYTES // len(chunk)) * 4):
            sent.append(len(chunk))
            yield chunk

    r = await client.post("/api/routes", content=body(),
                          headers={"content-type": "application/json"})
    assert r.status_code == 413
    # Потолок плюс один кусок: обрыв на первом же куске сверх потолка.
    assert sum(sent) <= api.MAX_BODY_BYTES + len(chunk), sum(sent)


async def test_an_oversized_upload_is_413(client):
    """Тот же потолок для multipart: Starlette кладёт файловую часть в
    SpooledTemporaryFile без всякого потолка (max_part_size сторожит только
    нефайловые поля), то есть большое тело уходит на диск — туда же, где
    лежит SQLite."""
    r = await client.post("/api/route/parse",
                          files={"file": ("big.gpx", _oversized(), "application/gpx+xml")},
                          headers=header())
    assert r.status_code == 413


async def test_a_legal_gpx_upload_still_fits_under_the_cap(client):
    """Потолок не должен резать законную загрузку: route.MAX_GPX_BYTES — это
    то, что приложение принимает у пилота, и файл такого размера обязан
    доехать до разбора (и получить свой честный 400 про формат), а не 413.
    """
    payload = b"<gpx>" + b" " * (route.MAX_GPX_BYTES - 16) + b"</gpx>"
    assert len(payload) <= route.MAX_GPX_BYTES
    r = await client.post("/api/route/parse",
                          files={"file": ("big.gpx", payload, "application/gpx+xml")},
                          headers=header())
    assert r.status_code == 400, r.status_code


async def test_the_cap_leaves_room_for_the_biggest_legal_upload():
    """Потолок тела считается ОТ MAX_GPX_BYTES, а не совпадает с ним: у
    multipart есть обвязка (границы частей, заголовки), и потолок вровень с
    файлом резал бы файл максимального размера."""
    assert api.MAX_BODY_BYTES > route.MAX_GPX_BYTES


async def test_a_normal_request_is_untouched(client):
    """Обёртка стоит на пути КАЖДОГО запроса, включая те, у которых тела нет
    вовсе."""
    assert (await client.get("/api/prefs", headers=header())).status_code == 200

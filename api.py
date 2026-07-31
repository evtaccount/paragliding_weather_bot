"""HTTP-поверхность мини-приложения.

Домен тот же, что у бота, — другой только источник `user_id`: бот берёт его из
апдейта, api из подписанной initData. Расчётов здесь нет: разбор запроса,
резолв личных настроек, вызов forecast и перевод исключений в коды.
"""
import dataclasses
import logging
import os
import sqlite3

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import engine
import forecast
import guards
import route
import store
import webauth

log = logging.getLogger("pgbot.api")

# Схема наружу не публикуется: единственный клиент — наше же приложение,
# а открытый /docs на публичном домене показывает всю поверхность чужим.
app = FastAPI(title="pgbot mini app", docs_url=None, redoc_url=None, openapi_url=None)
router = APIRouter(prefix="/api")


async def current_user(authorization: str = Header(default="")) -> webauth.TelegramUser:
    """Пилот за этим запросом. Каждый запрос проверяется заново — сессий нет.

    Причина отказа уходит в лог, а не в ответ: подробность вида «просрочено»
    против «подпись не сошлась» помогает подбирать подпись.
    """
    scheme, _, raw = authorization.partition(" ")
    if scheme.lower() != "tma" or not raw:
        raise HTTPException(401, "нужна авторизация Telegram Mini App")
    try:
        user = webauth.verify(raw, os.environ.get("BOT_TOKEN", ""))
    except webauth.AuthError as e:
        log.info("initData отклонена: %s", e)
        raise HTTPException(401, "initData не прошла проверку") from None

    allowed = guards.allowed_ids()
    if allowed and user.id not in allowed:
        raise HTTPException(
            403, f"Это личный бот, доступ по списку. Твой Telegram ID: {user.id} — "
                 "пришли его владельцу бота, чтобы тебя добавили.")
    return user


# ------------------------------------------------------------------ ошибки
@app.exception_handler(forecast.ForecastError)
async def _forecast_error(_request, exc: forecast.ForecastError):
    """400 с текстом как есть: сообщения ForecastError уже написаны пилоту."""
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(route.RouteError)
async def _route_error(_request, exc: route.RouteError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(httpx.HTTPError)
async def _upstream_error(_request, exc: httpx.HTTPError):
    """502. Текст наружу не отдаём: в нём бывает URL запроса целиком."""
    log.warning("upstream: %s", exc)
    return JSONResponse({"detail": "Метеосервис недоступен, попробуй позже."},
                        status_code=502)


# ------------------------------------------------------------------ настройки
def _prefs_payload(uid: int) -> dict:
    p = store.prefs(uid)
    return {"avg_route_speed_kmh": p.avg_route_speed_kmh,
            "wind_correction_enabled": p.wind_correction_enabled,
            "model_key": p.model_key,
            # Список моделей едет вместе с настройками, а не отдельным
            # эндпоинтом: выбиралка без подписей показала бы пилоту ключи.
            "models": [{"key": k, "label": engine.model_label(k)} for k in engine.MODELS]}


class PrefsPatch(BaseModel):
    """Все поля необязательные: приложение меняет один тумблер и не обязано
    присылать остальные, иначе оно молча затрёт их дефолтами."""
    avg_route_speed_kmh: float | None = None
    wind_correction_enabled: bool | None = None
    model_key: str | None = None


@router.get("/prefs")
async def read_prefs(user: webauth.TelegramUser = Depends(current_user)):
    return _prefs_payload(user.id)


@router.patch("/prefs")
async def update_prefs(body: PrefsPatch,
                       user: webauth.TelegramUser = Depends(current_user)):
    """Порядок операций держит запрос неделимым: 400 означает, что не
    сохранилось НИЧЕГО.

    Проверка ключа модели идёт первой и ничего не пишет. `set_speed` —
    единственная запись, способная бросить исключение, поэтому она вторая:
    к моменту, когда пишутся остальные поля, упасть уже нечему. Порядок
    «пишем по мере разбора» сохранял бы скорость и уходил с 400 из-за
    модели — ответ говорил бы «не принято», а половина настроек уже
    поменялась.
    """
    # Список моделей — знание домена: store ключ не проверяет намеренно.
    if body.model_key is not None and body.model_key not in engine.MODELS:
        raise HTTPException(400, f"неизвестная модель: {body.model_key}")
    if body.avg_route_speed_kmh is not None:
        try:
            store.set_speed(user.id, body.avg_route_speed_kmh)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
    if body.wind_correction_enabled is not None:
        store.set_wind_correction(user.id, body.wind_correction_enabled)
    if body.model_key is not None:
        store.set_model(user.id, body.model_key)
    return _prefs_payload(user.id)


# ------------------------------------------------------------------ старты
class SiteIn(BaseModel):
    """Поля повторяют колонки store._SITE_COLUMNS, кроме added_by — его
    подставляет сервер из подписи, а не клиент из тела запроса."""
    name: str
    lat: float
    lon: float
    elevation_m: int
    aspect: str | None = None
    aspect_deg: float | None = None
    slope_deg: float | None = None
    route_top_m: float | None = None
    aliases: list[str] = []
    notes: str = ""


class Coords(BaseModel):
    lat: float
    lon: float


@router.get("/sites")
async def list_sites(_user: webauth.TelegramUser = Depends(current_user)):
    """Библиотека общая, поэтому ответ не зависит от пилота. Зависимость
    оставлена: неавторизованный запрос не должен получать список стартов."""
    return store.load_sites()


@router.get("/sites/{name}")
async def read_site(name: str, _user: webauth.TelegramUser = Depends(current_user)):
    site = store.find_site(name)
    if site is None:
        raise HTTPException(404, f"старт не найден: {name}")
    return site


@router.post("/sites", status_code=201)
async def create_site(body: SiteIn, user: webauth.TelegramUser = Depends(current_user)):
    site = body.model_dump()
    # Правило одно на оба адаптера: см. store.name_error
    bad = store.name_error(site["name"])
    if bad:
        raise HTTPException(400, bad)
    if store.find_site(site["name"]) is not None:
        raise HTTPException(409, f"Старт «{site['name']}» уже есть.")
    try:
        store.add_site(site, added_by=user.id)
    except sqlite3.IntegrityError:
        # Гонка двух добавлений одного имени: проверка выше не атомарна.
        # Сообщение своё, а не str(e): текст SQLite («UNIQUE constraint failed:
        # sites.name») написан для разработчика и наружу не идёт — ровно по той
        # же причине, по которой обработчик httpx не отдаёт текст ошибки.
        raise HTTPException(409, f"Старт «{site['name']}» уже есть.") from None
    return store.find_site(site["name"])


@router.delete("/sites/{name}", status_code=204)
async def delete_site(name: str, _user: webauth.TelegramUser = Depends(current_user)):
    site = store.find_site(name)
    if site is None:
        # 204 на опечатку соврал бы: пилот решил бы, что удалил старт
        raise HTTPException(404, f"старт не найден: {name}")
    store.remove_site(site["name"])
    return None


@router.post("/elevation")
async def elevation(body: Coords, _user: webauth.TelegramUser = Depends(current_user)):
    """Высота точки — для формы добавления старта."""
    return {"elevation_m": await forecast.fetch_elevation(body.lat, body.lon)}


# ------------------------------------------------------------------ прогноз
def _model_for(uid: int, override: str | None) -> str:
    """Эффективная модель: разовый выбор из query, иначе постоянная настройка.

    Разрешается ЗДЕСЬ и передаётся домену явно: forecast обязан получать
    model= параметром, угадывать он не имеет права (см. фазу 2).
    """
    if override is None:
        return store.prefs(uid).model_key
    if override not in engine.MODELS:
        raise HTTPException(400, f"неизвестная модель: {override}")
    return override


def _site_or_404(name: str) -> dict:
    """Старт существует, или 404 до похода в сеть.

    Резолвит ТОЙ ЖЕ функцией, что и домен: `store.find_site` в одиночку
    отдал бы 404 на законную разовую точку по координатам, потому что она
    живёт в adhoc, а не в библиотеке стартов.
    """
    site = forecast.site_by_name(name)
    if site is None:
        raise HTTPException(404, f"старт не найден: {name}")
    return site


@router.get("/forecast")
async def read_forecast(site: str, range: str, date: str | None = None,
                        model: str | None = None,
                        user: webauth.TelegramUser = Depends(current_user)):
    """Факты, а не картинка: приложение рисует графики само."""
    _site_or_404(site)
    return await forecast.get_facts(site, range, date, model=_model_for(user.id, model))


@router.get("/forecast/wind-grid")
async def read_wind_grid(site: str, date: str, model: str | None = None,
                         user: webauth.TelegramUser = Depends(current_user)):
    _site_or_404(site)
    return await forecast.wind_grid_data(site, date, model=_model_for(user.id, model))


@router.get("/scan")
async def read_scan(model: str | None = None,
                    user: webauth.TelegramUser = Depends(current_user)):
    return await forecast.scan_week(model=_model_for(user.id, model))


# ------------------------------------------------------------------ разбор и маршрут
class AnalysisIn(BaseModel):
    site: str
    range: str
    date: str | None = None
    deep: bool = False
    model: str | None = None


class RouteIn(BaseModel):
    """`points` — строки [lat, lon, name?], тот же формат, в котором маршруты
    лежат в store: приложение получает их из /api/routes и шлёт обратно
    без перекладывания."""
    points: list[list]
    name: str | None = None
    date: str
    departure: str | None = None
    model: str | None = None


def _hours(hhmm: str | None) -> float | None:
    """«11:30» → 11.5. None означает «пусть домен выберет начало окна»."""
    if hhmm is None:
        return None
    try:
        h, m = hhmm.split(":")
        return int(h) + int(m) / 60.0
    except (ValueError, AttributeError):
        raise HTTPException(400, f"время вылета не понято: {hhmm}") from None


def _cfg_for(uid: int, override: str | None) -> store.Prefs:
    """Личные настройки с разовой подменой модели.

    Возвращается Prefs целиком: get_route берёт из него и скорость, и учёт
    ветра, и модель — собирать их по одному значит однажды забыть одно.
    """
    p = store.prefs(uid)
    if override is None:
        return p
    if override not in engine.MODELS:
        raise HTTPException(400, f"неизвестная модель: {override}")
    return dataclasses.replace(p, model_key=override)


def _points_or_400(rows: list[list]) -> list:
    """Строки [[lat, lon, name?], ...] → точки.

    `points_from_rows` исключений не бросает: на битой записи и нехватке точек
    он возвращает None, потому что писался для чтения из хранилища, где
    уронить бота хуже, чем показать маршрут отсутствующим. На входе из сети
    это, наоборот, ошибка запроса, и её надо назвать.

    Потолок числа точек он тоже не проверяет — только нижнюю границу, — а
    пятьдесят одна точка означает пятьдесят одну выборку погоды.
    """
    points = route.points_from_rows(rows)
    if points is None:
        raise HTTPException(400, f"Нужно минимум {route.MIN_POINTS} точки "
                                 "в формате [широта, долгота, имя].")
    if len(points) > route.MAX_POINTS:
        raise HTTPException(400, f"Слишком много точек: {len(points)}, "
                                 f"потолок {route.MAX_POINTS}.")
    return points


@router.post("/analysis")
async def read_analysis(body: AnalysisIn,
                        user: webauth.TelegramUser = Depends(current_user)):
    """Текст от Gemini. Ответ строкой, а не разметкой: она в приложении своя."""
    _site_or_404(body.site)
    text = await forecast.get_analysis(body.site, body.range, body.date, body.deep,
                                       model=_model_for(user.id, body.model))
    return {"text": text}


@router.post("/route")
async def read_route(body: RouteIn, user: webauth.TelegramUser = Depends(current_user)):
    return await forecast.get_route(_points_or_400(body.points), body.name, body.date,
                                    _hours(body.departure),
                                    cfg=_cfg_for(user.id, body.model))


@router.post("/route/analysis")
async def read_route_analysis(body: RouteIn,
                              user: webauth.TelegramUser = Depends(current_user)):
    text = await forecast.get_route_analysis(_points_or_400(body.points), body.name,
                                             body.date, _hours(body.departure),
                                             cfg=_cfg_for(user.id, body.model))
    return {"text": text}


app.include_router(router)

"""HTTP-поверхность мини-приложения.

Домен тот же, что у бота, — другой только источник `user_id`: бот берёт его из
апдейта, api из подписанной initData. Расчётов здесь нет: разбор запроса,
резолв личных настроек, вызов forecast и перевод исключений в коды.
"""
import logging
import os

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
    if body.avg_route_speed_kmh is not None:
        try:
            store.set_speed(user.id, body.avg_route_speed_kmh)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
    if body.wind_correction_enabled is not None:
        store.set_wind_correction(user.id, body.wind_correction_enabled)
    if body.model_key is not None:
        # Список моделей — знание домена: store ключ не проверяет намеренно.
        if body.model_key not in engine.MODELS:
            raise HTTPException(400, f"неизвестная модель: {body.model_key}")
        store.set_model(user.id, body.model_key)
    return _prefs_payload(user.id)


app.include_router(router)

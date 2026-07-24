"""Access control and rate limiting for the bot.

WhitelistMiddleware — only Telegram user IDs from ALLOWED_USER_IDS may use the
bot; strangers get one polite refusal (with their ID, so they can ask the owner
to add them). If ALLOWED_USER_IDS is empty/unset the bot stays open, with a
loud warning in the log.

ThrottleMiddleware — applies only to handlers flagged `forecast` (the ones that
hit open-meteo/Gemini): per-user cooldown of COOLDOWN_SEC seconds and at most
one in-flight request per user.
"""
import logging
import math
import os
import time

from aiogram import BaseMiddleware
from aiogram.dispatcher.flags import get_flag

log = logging.getLogger("pgbot.guards")

_REFUSAL_COOLDOWN = 60  # seconds between refusal replies to the same stranger


def _allowed_ids() -> frozenset[int]:
    raw = os.environ.get("ALLOWED_USER_IDS", "")
    ids = frozenset(int(p) for p in raw.replace(";", ",").split(",") if p.strip())
    if not ids:
        log.warning("ALLOWED_USER_IDS не задан — бот открыт для ВСЕХ пользователей")
    return ids


class WhitelistMiddleware(BaseMiddleware):
    def __init__(self):
        self.allowed = _allowed_ids()
        self._refused_at: dict[int, float] = {}

    async def __call__(self, handler, event, data):
        if not self.allowed or (event.from_user and event.from_user.id in self.allowed):
            return await handler(event, data)
        uid = event.from_user.id if event.from_user else 0
        now = time.monotonic()
        if now - self._refused_at.get(uid, -math.inf) >= _REFUSAL_COOLDOWN:
            self._refused_at[uid] = now
            log.info("refused user %s (%s)", uid, getattr(event.from_user, "username", None))
            await event.answer(
                "🔒 Это личный бот. Доступ по списку.\n"
                f"Твой Telegram ID: {uid} — пришли его владельцу бота, чтобы тебя добавили."
            )
        return None


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self):
        self.cooldown = float(os.environ.get("COOLDOWN_SEC", "10"))
        self._last: dict[int, float] = {}
        self._inflight: set[int] = set()

    async def __call__(self, handler, event, data):
        if not get_flag(data, "forecast") or not event.from_user:
            return await handler(event, data)
        uid = event.from_user.id
        if uid in self._inflight:
            return await event.answer("⏳ Уже готовлю прогноз — дождись ответа.")
        now = time.monotonic()
        wait = self._last.get(uid, -math.inf) + self.cooldown - now
        if wait > 0:
            return await event.answer(f"⏳ Не так часто: подожди {math.ceil(wait)} сек.")
        self._last[uid] = now
        self._inflight.add(uid)
        try:
            return await handler(event, data)
        finally:
            self._inflight.discard(uid)

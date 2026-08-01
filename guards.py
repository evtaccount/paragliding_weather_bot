"""Access control and rate limiting for the bot.

WhitelistMiddleware — only Telegram user IDs from ALLOWED_USER_IDS may use the
bot; strangers get one polite refusal (with their ID, so they can ask the owner
to add them). If ALLOWED_USER_IDS is empty/unset the bot stays open, with a
loud warning in the log.

ThrottleMiddleware — applies only to handlers flagged `forecast` (the ones that
hit open-meteo/Gemini). Two guards:
  • in-flight: at most one request per user at a time — always on.
  • cooldown (COOLDOWN_SEC): only for typed commands. Inline-button presses
    (day picker, "разбор от ИИ", …) are deliberate follow-ups on a result the
    bot already delivered, not spam, so they skip the cooldown — you can pick a
    day right after an overview, or ask for analysis right after a forecast.
"""
import logging
import math
import os
import time

from aiogram import BaseMiddleware
from aiogram.dispatcher.flags import get_flag
from aiogram.types import CallbackQuery

log = logging.getLogger("pgbot.guards")

_REFUSAL_COOLDOWN = 60  # seconds between refusal replies to the same stranger


_warned_open = False


def allowed_ids() -> frozenset[int]:
    """Кому можно — общий список для чата и приложения.

    Публичная: зовут три модуля (middleware, bootstrap хранилища, HTTP-слой),
    и подчёркивание в чужом импорте означало бы, что граница проведена не там.

    Предупреждение об открытом режиме печатается один раз за процесс: HTTP-слой
    зовёт эту функцию на каждый запрос, и построчный вой в логе утопил бы всё
    остальное.
    """
    global _warned_open
    raw = os.environ.get("ALLOWED_USER_IDS", "")
    ids = frozenset(int(p) for p in raw.replace(";", ",").split(",") if p.strip())
    if not ids and not _warned_open:
        _warned_open = True
        log.warning("ALLOWED_USER_IDS не задан — бот открыт для ВСЕХ пользователей")
    return ids


class WhitelistMiddleware(BaseMiddleware):
    def __init__(self):
        self.allowed = allowed_ids()
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


class InFlight:
    """Кто из пилотов прямо сейчас чего-то ждёт.

    Общий на чат и приложение намеренно: гарантия сформулирована про пилота,
    а не про поверхность, и открыть приложение, пока бот считает тот же
    прогноз, — это второй запрос того же человека.

    Множество, а не счётчик: параллельных запросов одного пилота не бывает
    по определению, а счётчик пришлось бы чинить после каждого падения.
    """

    def __init__(self):
        self._busy: set[int] = set()

    def acquire(self, uid: int) -> bool:
        """True — слот занят нами. False — пилот уже что-то ждёт."""
        if uid in self._busy:
            return False
        self._busy.add(uid)
        return True

    def busy(self, uid: int) -> bool:
        """Ждёт ли пилот чего-то прямо сейчас. Ничего не занимает.

        Отдельно от `acquire` намеренно: в чате проверка занятости стоит
        раньше проверки паузы, а захват — позже неё. Слитые в один вызов,
        они держали бы слот на время ответа «не так часто», то есть на всё
        сетевое обращение к Telegram.
        """
        return uid in self._busy

    def release(self, uid: int) -> None:
        self._busy.discard(uid)

    def clear(self) -> None:
        """Только для тестов: реестр процессный и переживает тест."""
        self._busy.clear()


INFLIGHT = InFlight()


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self):
        self.cooldown = float(os.environ.get("COOLDOWN_SEC", "10"))
        self._last: dict[int, float] = {}

    async def __call__(self, handler, event, data):
        if not get_flag(data, "forecast") or not event.from_user:
            return await handler(event, data)
        uid = event.from_user.id
        if INFLIGHT.busy(uid):
            return await event.answer("⏳ Уже готовлю — дождись ответа.")
        # follow-up button presses aren't spam — only typed commands get the cooldown.
        # Проверка стоит ДО acquire: отказ по паузе — это await event.answer(...),
        # настоящее сетевое обращение, и держать слот на это время значило бы
        # отвечать 429 в приложении пилоту, который в этот момент ничего не считает.
        if not isinstance(event, CallbackQuery):
            now = time.monotonic()
            wait = self._last.get(uid, -math.inf) + self.cooldown - now
            if wait > 0:
                return await event.answer(f"⏳ Не так часто: подожди {math.ceil(wait)} сек.")
            self._last[uid] = now
        INFLIGHT.acquire(uid)
        try:
            return await handler(event, data)
        finally:
            INFLIGHT.release(uid)

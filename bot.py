"""Paragliding forecast Telegram bot — command-driven, no LLM.

Commands:
  /forecast <site> <range>   — range: 1d | 3d | week | 2weeks
  /today [site]              — detailed forecast for today
  /tomorrow [site]           — detailed forecast for tomorrow
  /threedays [site]          — 3-day overview
  /week [site]               — 7-day overview
  /twoweeks [site]           — 14-day overview
  /sites                     — list saved launches
  /help, /start

If a site is omitted and only one launch is saved, it's used automatically.
Forecast + charts come from the deterministic engine (open-meteo).
"""
import asyncio
import datetime as dt
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BotCommand, FSInputFile, InputMediaPhoto, Message
from dotenv import load_dotenv

import forecast

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pgbot")

dp = Dispatcher()

RANGE_ALIASES = {
    "1d": "1d", "day": "1d", "день": "1d",
    "3d": "3d", "3days": "3d", "3дня": "3d",
    "week": "week", "7d": "week", "неделя": "week", "неделю": "week",
    "2weeks": "2weeks", "14d": "2weeks", "2недели": "2weeks",
}

HELP = (
    "🪂 Прогноз погоды для параплана\n\n"
    "Команды:\n"
    "/today [старт] — подробно на сегодня\n"
    "/tomorrow [старт] — подробно на завтра\n"
    "/threedays [старт] — обзор на 3 дня\n"
    "/week [старт] — обзор на неделю\n"
    "/twoweeks [старт] — обзор на 2 недели\n"
    "/forecast <старт> <диапазон> — вручную (1d · 3d · week · 2weeks)\n"
    "/sites — список стартов\n\n"
    "Если старт не указан, а он один — берётся автоматически.\n"
    "Источник: open-meteo. Прогноз далеко вперёд — пересними за 1–2 суток."
)

BOT_COMMANDS = [
    BotCommand(command="today", description="Прогноз на сегодня"),
    BotCommand(command="tomorrow", description="Прогноз на завтра"),
    BotCommand(command="threedays", description="Обзор на 3 дня"),
    BotCommand(command="week", description="Обзор на неделю"),
    BotCommand(command="twoweeks", description="Обзор на 2 недели"),
    BotCommand(command="forecast", description="Прогноз: <старт> <диапазон>"),
    BotCommand(command="sites", description="Список стартов"),
    BotCommand(command="help", description="Справка"),
]


def resolve_site(arg: str | None) -> str | None:
    """Return the site name to use: the given arg, or the sole saved site, else None."""
    if arg and arg.strip():
        return arg.strip()
    names = forecast.known_sites()
    return names[0] if len(names) == 1 else None


async def send_forecast(message: Message, site: str, rng: str, date: str | None = None):
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    try:
        text, pngs = await forecast.get_forecast(site, rng, date)
    except forecast.ForecastError as e:
        await message.answer(f"⚠️ {e}\n\nСписок стартов: /sites")
        return
    except Exception as e:  # noqa: BLE001 — surface any unexpected failure to the user
        log.exception("forecast failed")
        await message.answer(f"⚠️ Ошибка: {e}")
        return

    await message.answer(text)
    if len(pngs) == 1:
        await message.answer_photo(FSInputFile(pngs[0]))
    elif pngs:
        media = [InputMediaPhoto(media=FSInputFile(p)) for p in pngs]
        await message.answer_media_group(media)


async def _shortcut(message: Message, command: CommandObject, rng: str, date: str | None):
    site = resolve_site(command.args)
    if not site:
        await message.answer("Укажи старт: например /week Laliskuri\n/sites — список.")
        return
    await send_forecast(message, site, rng, date)


@dp.message(CommandStart())
@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP)


@dp.message(Command("sites"))
async def cmd_sites(message: Message):
    names = forecast.known_sites()
    await message.answer("Сохранённые старты:\n" + "\n".join(f"• {n}" for n in names))


@dp.message(Command("today"))
async def cmd_today(message: Message, command: CommandObject):
    await _shortcut(message, command, "1d", dt.date.today().isoformat())


@dp.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message, command: CommandObject):
    await _shortcut(message, command, "1d", (dt.date.today() + dt.timedelta(days=1)).isoformat())


@dp.message(Command("threedays"))
async def cmd_threedays(message: Message, command: CommandObject):
    await _shortcut(message, command, "3d", None)


@dp.message(Command("week"))
async def cmd_week(message: Message, command: CommandObject):
    await _shortcut(message, command, "week", None)


@dp.message(Command("twoweeks"))
async def cmd_twoweeks(message: Message, command: CommandObject):
    await _shortcut(message, command, "2weeks", None)


@dp.message(Command("forecast"))
async def cmd_forecast(message: Message, command: CommandObject):
    parts = (command.args or "").split()
    if not parts:
        await message.answer("Формат: /forecast <старт> <диапазон>\nНапример: /forecast Laliskuri week")
        return
    if parts[-1].lower() in RANGE_ALIASES:
        rng = RANGE_ALIASES[parts[-1].lower()]
        site = " ".join(parts[:-1])
    else:
        rng = "week"
        site = " ".join(parts)
    site = resolve_site(site)
    if not site:
        await message.answer("Не указан старт. /sites — список.")
        return
    await send_forecast(message, site, rng)


async def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN не задан (см. .env.example)")
    bot = Bot(token=token)
    await bot.set_my_commands(BOT_COMMANDS)
    log.info("bot started, sites: %s", forecast.known_sites())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

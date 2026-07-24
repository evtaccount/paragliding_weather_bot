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

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (BotCommand, BufferedInputFile, CallbackQuery,
                           InlineKeyboardButton, InlineKeyboardMarkup,
                           InputMediaPhoto, Message)
from aiogram.utils.chat_action import ChatActionSender
from dotenv import load_dotenv

load_dotenv()  # before guards/forecast read their env vars

import engine  # noqa: E402
import forecast  # noqa: E402
import guards  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pgbot")

dp = Dispatcher(storage=MemoryStorage())  # in-memory FSM for the interactive /add
# guards on both messages and inline-button callbacks. Separate throttle instances
# so pressing the analysis button right after a command isn't blocked by the command
# cooldown, while button spam is still throttled on its own.
dp.message.outer_middleware(guards.WhitelistMiddleware())
dp.message.middleware(guards.ThrottleMiddleware())
dp.callback_query.outer_middleware(guards.WhitelistMiddleware())
dp.callback_query.middleware(guards.ThrottleMiddleware())


class AddSite(StatesGroup):
    """Interactive /add flow: coordinates → name → aspect → notes."""
    coords = State()
    name = State()
    aspect = State()
    notes = State()


class AdHoc(StatesGroup):
    """"По координатам": ask coordinates for a one-off forecast."""
    coords = State()

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
    BotCommand(command="add", description="Добавить старт: <имя> <lat> <lon> <эксп>"),
    BotCommand(command="removesite", description="Удалить старт: <имя>"),
    BotCommand(command="help", description="Справка"),
]


def _chunks(text: str, size: int = 4096):
    """Split into Telegram-sized pieces (LLM output can exceed the 4096 limit)."""
    for i in range(0, len(text), size):
        yield text[i:i + size]


def resolve_site(arg: str | None) -> str | None:
    """Return the site name to use: the given arg, or the sole saved site, else None."""
    if arg and arg.strip():
        return arg.strip()
    names = forecast.known_sites()
    return names[0] if len(names) == 1 else None


_WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _day_picker_kb(site: str, rng: str) -> InlineKeyboardMarkup:
    """Buttons for each day of an overview period → detailed 1-day forecast.

    An overview is fetched with forecast_days=N, so the period is always
    today … today+(N-1) in the site's timezone.
    """
    today = dt.date.today()
    rows, row = [], []
    for i in range(engine.RANGE_DAYS[rng]):
        d = today + dt.timedelta(days=i)
        label = f"{_WD[d.weekday()]} {d.day:02d}.{d.month:02d}"
        row.append(InlineKeyboardButton(text=label, callback_data=f"pd|{site}|{d.isoformat()}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_forecast(message: Message, site: str, rng: str, date: str | None = None):
    if rng == "1d" and not date:
        date = dt.date.today().isoformat()
    try:
        # keeps the "typing…" status alive while forecast/analysis runs (>5 s)
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            card, pngs = await forecast.get_forecast(site, rng, date)
    except forecast.ForecastError as e:
        await message.answer(f"⚠️ {e}\n\nСписок стартов: /sites")
        return
    except Exception as e:  # noqa: BLE001 — surface any unexpected failure to the user
        log.exception("forecast failed")
        await message.answer(f"⚠️ Ошибка: {e}")
        return

    for chunk in _chunks(card):
        await message.answer(chunk)
    files = [BufferedInputFile(p, filename=f"chart{i}.png") for i, p in enumerate(pngs, 1)]
    if len(files) == 1:
        await message.answer_photo(files[0])
    elif files:
        await message.answer_media_group([InputMediaPhoto(media=f) for f in files])
    # LLM analysis is off by default — offer it on demand.
    row = [InlineKeyboardButton(text="🧠 Разбор от ИИ", callback_data=f"llm|{site}|{rng}|{date or ''}")]
    if rng == "1d":  # deep analysis (surrounding points + previous day) — 1-day only
        row.append(InlineKeyboardButton(text="📊 Глубокий разбор", callback_data=f"deep|{site}|{rng}|{date or ''}"))
    await message.answer("Нужен разбор от ИИ?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[row]))
    if rng != "1d":  # overview → let the user drill into a single day
        await message.answer("📅 Подробно по дню:", reply_markup=_day_picker_kb(site, rng))


async def ask_location(message: Message, rng: str, date: str | None):
    """No site given → offer saved sites + a "по координатам" option as inline buttons."""
    rows = [[InlineKeyboardButton(text=n, callback_data=f"pk|{rng}|{date or ''}|{n}")]
            for n in forecast.known_sites()]
    rows.append([InlineKeyboardButton(text="📍 По координатам", callback_data=f"pc|{rng}|{date or ''}")])
    await message.answer("Для какой точки?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def _shortcut(message: Message, command: CommandObject, rng: str, date: str | None):
    if command.args and command.args.strip():
        await send_forecast(message, command.args.strip(), rng, date)
    else:
        await ask_location(message, rng, date)


@dp.message(CommandStart())
@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP)


@dp.message(Command("sites"))
async def cmd_sites(message: Message):
    names = forecast.known_sites()
    await message.answer("Сохранённые старты:\n" + "\n".join(f"• {n}" for n in names))


async def _finish_add(message: Message, name: str, lat: float, lon: float,
                      aspect_deg: float, notes: str = ""):
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    elev = await forecast.fetch_elevation(lat, lon)
    site = {"name": name, "aliases": [name.lower()], "lat": lat, "lon": lon,
            "elevation_m": elev, "aspect": engine.card(aspect_deg),
            "aspect_deg": aspect_deg, "notes": notes}
    try:
        engine.add_site(site)
    except ValueError as e:
        await message.answer(f"⚠️ {e}")
        return
    await message.answer(
        f"✅ Старт добавлен: {name}\n"
        f"📍 {lat}, {lon} · {elev} м · экспозиция {engine.card(aspect_deg)} ({round(aspect_deg)}°)\n"
        f"Прогноз: /forecast {name} week")


@dp.message(Command("add"))
async def cmd_add(message: Message, command: CommandObject, state: FSMContext):
    parts = (command.args or "").split()
    if len(parts) >= 4:  # one-shot: /add <Имя> <lat> <lon> <экспозиция>
        *name_parts, lat_s, lon_s, aspect_s = parts
        name = " ".join(name_parts)
        try:
            lat, lon = float(lat_s), float(lon_s)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError
        except ValueError:
            await message.answer("Координаты неверные. Формат: /add <Имя> <lat> <lon> <экспозиция>")
            return
        try:
            aspect_deg = engine.parse_aspect(aspect_s)
        except ValueError as e:
            await message.answer(f"⚠️ {e}")
            return
        await _finish_add(message, name, lat, lon, aspect_deg)
        return
    # data missing → ask step by step: coordinates → name → aspect
    await state.set_state(AddSite.coords)
    await message.answer("Добавляю старт. Пришли координаты — широта, долгота\n"
                         "Напр.: 42.47, 44.48\n(/cancel — отмена)")


@dp.message(AddSite.coords, F.text, ~F.text.startswith("/"))
async def add_coords(message: Message, state: FSMContext):
    raw = message.text.replace(",", " ").split()
    try:
        lat, lon = float(raw[0]), float(raw[1])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError
    except (ValueError, IndexError):
        await message.answer("Не понял координаты. Пришли «широта, долгота», напр.: 42.47, 44.48")
        return
    await state.update_data(lat=lat, lon=lon)
    await state.set_state(AddSite.name)
    await message.answer("Название старта?")


@dp.message(AddSite.name, F.text, ~F.text.startswith("/"))
async def add_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Пустое название. Введи имя старта.")
        return
    await state.update_data(name=name)
    await state.set_state(AddSite.aspect)
    await message.answer("Экспозиция — куда смотрит склон: С/СВ/В/ЮВ/Ю/ЮЗ/З/СЗ или градусы 0–359")


@dp.message(AddSite.aspect, F.text, ~F.text.startswith("/"))
async def add_aspect(message: Message, state: FSMContext):
    try:
        aspect_deg = engine.parse_aspect(message.text)
    except ValueError as e:
        await message.answer(f"{e}\nПопробуй ещё раз.")
        return
    await state.update_data(aspect_deg=aspect_deg)
    await state.set_state(AddSite.notes)
    await message.answer("Заметка к старту? (напр. «южный бриз, SIV-сайт») — или «-», чтобы пропустить")


@dp.message(AddSite.notes, F.text, ~F.text.startswith("/"))
async def add_notes(message: Message, state: FSMContext):
    notes = message.text.strip()
    if notes in ("-", "—", "нет", "skip"):
        notes = ""
    data = await state.get_data()
    await state.clear()
    await _finish_add(message, data["name"], data["lat"], data["lon"], data["aspect_deg"], notes)


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if await state.get_state() is None:
        return
    await state.clear()
    await message.answer("Отменено.")


@dp.message(Command("removesite"))
async def cmd_removesite(message: Message, command: CommandObject):
    name = (command.args or "").strip()
    if not name:
        await message.answer("Формат: /removesite <Имя>. Список: /sites")
        return
    try:
        engine.remove_site(name)
    except ValueError as e:
        await message.answer(f"⚠️ {e}")
        return
    await message.answer(f"🗑️ Старт удалён: {name}")


@dp.message(Command("today"), flags={"forecast": True})
async def cmd_today(message: Message, command: CommandObject):
    await _shortcut(message, command, "1d", dt.date.today().isoformat())


@dp.message(Command("tomorrow"), flags={"forecast": True})
async def cmd_tomorrow(message: Message, command: CommandObject):
    await _shortcut(message, command, "1d", (dt.date.today() + dt.timedelta(days=1)).isoformat())


@dp.message(Command("threedays"), flags={"forecast": True})
async def cmd_threedays(message: Message, command: CommandObject):
    await _shortcut(message, command, "3d", None)


@dp.message(Command("week"), flags={"forecast": True})
async def cmd_week(message: Message, command: CommandObject):
    await _shortcut(message, command, "week", None)


@dp.message(Command("twoweeks"), flags={"forecast": True})
async def cmd_twoweeks(message: Message, command: CommandObject):
    await _shortcut(message, command, "2weeks", None)


@dp.message(Command("forecast"), flags={"forecast": True})
async def cmd_forecast(message: Message, command: CommandObject):
    parts = (command.args or "").split()
    if parts and parts[-1].lower() in RANGE_ALIASES:
        rng = RANGE_ALIASES[parts[-1].lower()]
        parts = parts[:-1]
    else:
        rng = "week"
    site = " ".join(parts).strip()
    if not site:
        await ask_location(message, rng, None)
        return
    await send_forecast(message, site, rng)


@dp.callback_query(F.data.startswith(("llm|", "deep|")), flags={"forecast": True})
async def cb_analysis(cb: CallbackQuery):
    try:
        kind, site, rng, date = cb.data.split("|", 3)
    except ValueError:
        await cb.answer()
        return
    deep = kind == "deep"
    await cb.answer("Считаю глубокий разбор…" if deep else "Считаю разбор…")
    try:
        async with ChatActionSender.typing(bot=cb.message.bot, chat_id=cb.message.chat.id):
            text = await forecast.get_analysis(site, rng, date or None, deep=deep)
    except forecast.ForecastError as e:
        await cb.message.answer(f"⚠️ {e}")
        return
    except Exception as e:  # noqa: BLE001 — surface any unexpected failure to the user
        log.exception("analysis failed")
        await cb.message.answer(f"⚠️ Ошибка: {e}")
        return
    for chunk in _chunks(text):
        await cb.message.answer(chunk)
    # keep the buttons — the user may want the other mode too


@dp.callback_query(F.data.startswith("pd|"), flags={"forecast": True})
async def cb_pick_day(cb: CallbackQuery):
    """A day button from an overview → detailed 1-day forecast for that date."""
    try:
        _, site, date = cb.data.split("|", 2)
    except ValueError:
        await cb.answer()
        return
    await cb.answer(f"Прогноз на {date}…")
    # keep the picker in place — the user may want another day too
    await send_forecast(cb.message, site, "1d", date)


@dp.callback_query(F.data.startswith("pk|"), flags={"forecast": True})
async def cb_pick_site(cb: CallbackQuery):
    try:
        _, rng, date, name = cb.data.split("|", 3)
    except ValueError:
        await cb.answer()
        return
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)  # collapse the picker
    except Exception:  # noqa: BLE001
        pass
    await send_forecast(cb.message, name, rng, date or None)


@dp.callback_query(F.data.startswith("pc|"))
async def cb_pick_coords(cb: CallbackQuery, state: FSMContext):
    try:
        _, rng, date = cb.data.split("|", 2)
    except ValueError:
        await cb.answer()
        return
    await cb.answer()
    await state.set_state(AdHoc.coords)
    await state.update_data(rng=rng, date=date)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await cb.message.answer("Пришли координаты — широта, долгота (напр. 42.47, 44.48)\n(/cancel — отмена)")


@dp.message(AdHoc.coords, F.text, ~F.text.startswith("/"))
async def adhoc_coords(message: Message, state: FSMContext):
    raw = message.text.replace(",", " ").split()
    try:
        lat, lon = float(raw[0]), float(raw[1])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError
    except (ValueError, IndexError):
        await message.answer("Не понял координаты. Пришли «широта, долгота», напр.: 42.47, 44.48")
        return
    data = await state.get_data()
    await state.clear()
    rng, date = data.get("rng", "week"), (data.get("date") or None)
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    elev = await forecast.fetch_elevation(lat, lon)
    name = forecast.register_adhoc(lat, lon, elev)
    await send_forecast(message, name, rng, date)


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

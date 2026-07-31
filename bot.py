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
import html
import io
import itertools
import logging
import math
import os
import re
from collections import OrderedDict

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

import analysis  # noqa: E402
import engine  # noqa: E402
import forecast  # noqa: E402
import guards  # noqa: E402
import route  # noqa: E402
import store  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pgbot")

dp = Dispatcher(storage=MemoryStorage())  # in-memory FSM for the interactive /add
# guards on both messages and inline-button callbacks. Separate throttle instances;
# the cooldown applies to typed commands only — button presses are follow-ups on an
# already-delivered result and skip it (see ThrottleMiddleware), keeping the in-flight
# guard so one request runs at a time.
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


class SettingsSpeed(StatesGroup):
    """/settings → «Ввести свою»: ждём число средней маршрутной скорости."""
    value = State()

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
    "/scan — лётные дни на неделю по всем стартам\n"
    "/forecast <старт> <диапазон> — вручную (1d · 3d · week · 2weeks)\n"
    "/route [дата] [ЧЧ:ММ] — погода по маршруту (список координат, GPX или KML)\n"
    "/route <имя> [дата] [ЧЧ:ММ] — посчитать сохранённый маршрут\n"
    "/routes — сохранённые маршруты\n"
    "/saveroute <имя> — сохранить последний посчитанный маршрут\n"
    "/delroute <имя> — удалить сохранённый маршрут\n"
    "/settings — средняя маршрутная скорость и учёт ветра\n"
    "/model — метеомодель (auto · ecmwf · gfs · icon)\n"
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
    BotCommand(command="scan", description="Лётные дни на неделю по всем стартам"),
    BotCommand(command="forecast", description="Прогноз: <старт> <диапазон>"),
    BotCommand(command="route", description="Погода по маршруту: список координат, GPX или KML"),
    BotCommand(command="routes", description="Сохранённые маршруты"),
    BotCommand(command="saveroute", description="Сохранить последний маршрут: <имя>"),
    BotCommand(command="delroute", description="Удалить сохранённый маршрут: <имя>"),
    BotCommand(command="settings", description="Настройки маршрута"),
    BotCommand(command="model", description="Метеомодель: /model <auto|ecmwf|gfs|icon>"),
    BotCommand(command="sites", description="Список стартов"),
    BotCommand(command="add", description="Добавить старт: <имя> <lat> <lon> <эксп>"),
    BotCommand(command="removesite", description="Удалить старт: <имя>"),
    BotCommand(command="help", description="Справка"),
]


def _chunks(text: str, size: int = 4096):
    """Split into Telegram-sized pieces (LLM output can exceed the 4096 limit)."""
    for i in range(0, len(text), size):
        yield text[i:i + size]


def _analysis_html(text: str) -> str:
    """LLM analysis uses **bold** markdown, which Telegram renders raw unless we ask
    it to. Escape HTML specials first (so a literal `>` in «ветер >7» is safe), then
    turn **...** into <b>...</b>. Send the result with parse_mode="HTML"."""
    esc = html.escape(text, quote=False)  # & < >  — leaves ** untouched
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc, flags=re.S)


def _btn(text: str, data: str) -> InlineKeyboardButton | None:
    """Inline button, or None (with a warning) when callback_data exceeds Telegram's
    64-byte limit — otherwise Telegram rejects the WHOLE message with the keyboard."""
    if len(data.encode("utf-8")) > 64:
        log.warning("callback_data > 64 bytes, кнопка пропущена: %r", data)
        return None
    return InlineKeyboardButton(text=text, callback_data=data)


def _model_sfx(model: str | None) -> str:
    """Хвост callback_data с кодом разовой модели. Пусто без разового выбора —
    обычный путь не должен терять запас длины у имён стартов."""
    return f"|{engine.model_code(model)}" if model else ""


def _split_cb(data: str, n: int):
    """Разбор callback_data на n полей плюс необязательный код модели последним.

    Полный split, а не maxsplit: с ограничением дописанный код попал бы в поле
    даты. Символ «|» в именах стартов запрещён при /add, поэтому полей ровно
    столько, сколько положено. Возвращает (None, None) при неверном числе полей.
    """
    parts = data.split("|")
    if len(parts) == n:
        return parts, None
    if len(parts) == n + 1:
        return parts[:n], engine.model_for_code(parts[n])
    return None, None


_COORD_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def parse_coords(text: str) -> tuple[float, float] | None:
    """Extract exactly (lat, lon) from free-form text. Decimal commas supported:
    «42,47 44,48» → (42.47, 44.48). Anything but exactly two numbers → None —
    re-ask instead of silently taking the first two of four."""
    nums = _COORD_RE.findall(text)
    if len(nums) != 2:
        return None
    lat, lon = (float(n.replace(",", ".")) for n in nums)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


async def cb_message(cb: CallbackQuery) -> Message | None:
    """The callback's source message if still accessible. Telegram stops exposing
    messages older than ~48h — our buttons stay in the chat forever, so a stale
    press must get an explicit answer, not an AttributeError."""
    if isinstance(cb.message, Message):
        return cb.message
    await cb.answer("Кнопка устарела — запроси прогноз заново.", show_alert=True)
    return None


_WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _day_picker_kb(site: str, rng: str, model: str | None = None, *,
                   effective) -> InlineKeyboardMarkup | None:
    """Buttons for each day of an overview period → detailed 1-day forecast.

    Dates come from the cached overview facts (site-local, straight from the
    open-meteo response) — the server's own "today" can differ from the site's
    around midnight. Cold cache → fall back to server-local dates.

    `effective` — модель, которой посчитан показанный обзор: по ней ищется запись
    в кэше, и она же уходит в cached_dates. `model` — разовый выбор пользователя,
    он едет только в callback_data кнопок, а не в поиск по кэшу: единственный
    вызывающий (`send_forecast`) всегда передаёт настоящий `eff` в `effective`.
    """
    dates = forecast.cached_dates(site, rng, model=effective)
    if dates is None:
        today = dt.date.today()
        dates = [(today + dt.timedelta(days=i)).isoformat() for i in range(engine.RANGE_DAYS[rng])]
    sfx = _model_sfx(model)
    rows, row = [], []
    for iso in dates:
        d = dt.date.fromisoformat(iso)
        btn = _btn(f"{_WD[d.weekday()]} {d.day:02d}.{d.month:02d}", f"pd|{site}|{iso}{sfx}")
        if btn is None:
            continue
        row.append(btn)
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _scan_message(result: dict) -> tuple[str, InlineKeyboardMarkup | None]:
    """Render scan_week() output → (text, keyboard). One pd|-button per (site, day)."""
    if not result["sites"]:
        lines = ["🔎 На этой неделе лётных окон нет по всем стартам."]
        if result["failed"]:
            lines.append(f"⚠️ Не удалось получить: {', '.join(result['failed'])}.")
        return "\n".join(lines), None
    lines = ["🔎 Лётные дни на неделю — по стартам", ""]
    rows: list[list[InlineKeyboardButton]] = []
    for s in result["sites"]:
        head = f"🪂 {s['name']}" + (f" ({engine.card(s['aspect'])})" if s["aspect"] is not None else "")
        lines.append(head)
        for r in s["days"]:
            d = dt.date.fromisoformat(r["date"])
            day = f"{_WD[d.weekday()]} {d.day:02d}.{d.month:02d}"
            lines.append(f"  {r['emoji']} {day} · {round(r['score'])}/100 · до {r['wmax']:.0f}, "
                         f"порыв {r['gmax']:.0f} м/с · {engine.card(r['dom'])} · "
                         f"{engine.WMO.get(r['wc'], '')}"
                         + (f" {r['precip']:.1f}мм" if r["precip"] > engine.RAIN_DAY else "")
                         + (f" · ограничивает {r['limiting']}" if r.get("limiting") else ""))
            btn = _btn(f"{r['emoji']} {day} · {s['name']}", f"pd|{s['name']}|{r['date']}")
            if btn is not None:
                rows.append([btn])
        lines.append("")
    if result["empty"]:
        lines.append("Без лётных дней: " + ", ".join(result["empty"]) + ".")
    if result["failed"]:
        lines.append(f"⚠️ Не удалось получить: {', '.join(result['failed'])}.")
    kb = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    return "\n".join(lines).rstrip(), kb


def _model_short(k: str) -> str:
    return "Auto" if k == "auto" else engine.model_label(k)


def _model_switch_keyboard(site: str, rng: str, date: str | None,
                           current: str) -> InlineKeyboardMarkup | None:
    """Row of model buttons under a forecast; tapping re-renders it with that model.
    An over-long site name overflows callback_data → _btn drops that button (with a warning).

    `current` — модель, которой посчитан ПОКАЗАННЫЙ прогноз, а не глобальная:
    после разового переключения галочка должна стоять на том, что на экране.
    """
    row = []
    for k in engine.MODELS:
        btn = _btn(f"{_model_short(k)}{' ✓' if k == current else ''}", f"mf|{k}|{site}|{rng}|{date or ''}")
        if btn is not None:
            row.append(btn)
    return InlineKeyboardMarkup(inline_keyboard=[row]) if row else None


def _model_switch_caption(model: str | None, permanent: str) -> str:
    """Подпись ряда моделей. При разовом выборе называет и постоянную модель —
    иначе непонятно, куда вернётся бот на следующем запросе."""
    if model is None:
        return "🌐 Другая модель (разово):"
    return (f"🌐 Модель: {engine.model_label(model)} — разово. "
            f"Постоянная: {engine.model_label(permanent)} (/model)")


async def send_forecast(message: Message, site: str, rng: str, date: str | None = None,
                        model: str | None = None, prefs: "store.Prefs | None" = None):
    """`model` — разовый выбор кнопкой; едет во все кнопки этого же сообщения,
    чтобы разбор и ветер по высотам считались по показанной модели.

    `prefs` приходит параметром, а не читается из `message`: у сообщения под
    кнопкой автор — сам бот, и `message.from_user.id` там не тот, кто нажал.
    """
    prefs = prefs or store.DEFAULT_PREFS
    # Считаем по разовому выбору, если он есть, иначе по постоянной модели пилота.
    # В кнопки (`sfx`, подпись ряда моделей) едет по-прежнему сырой `model`:
    # там «разово» значит «пользователь нажал», а не «чем посчитано».
    eff = model or prefs.model_key
    if rng == "1d" and not date:
        date = dt.date.today().isoformat()
    try:
        # keeps the "typing…" status alive while forecast/analysis runs (>5 s)
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            card, pngs = await forecast.get_forecast(site, rng, date, model=eff)
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
    sfx = _model_sfx(model)
    row = [_btn("🧠 Разбор от ИИ", f"llm|{site}|{rng}|{date or ''}{sfx}")]
    if rng == "1d":  # deep analysis (surrounding points + previous day) — 1-day only
        row.append(_btn("📊 Глубокий разбор", f"deep|{site}|{rng}|{date or ''}{sfx}"))
    row = [b for b in row if b is not None]
    kb_rows = [row] if row else []
    if rng == "1d":  # wind aloft grid (altitude × hour) — 1-day only
        wg = _btn("🌬 Ветер по высотам", f"wg|{site}|{date or ''}{sfx}")
        if wg is not None:
            kb_rows.append([wg])
    if kb_rows:
        await message.answer("Ещё:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    if rng != "1d":  # overview → let the user drill into a single day
        kb = _day_picker_kb(site, rng, model, effective=eff)
        if kb is not None:
            await message.answer("📅 Подробно по дню:", reply_markup=kb)
    mkb = _model_switch_keyboard(site, rng, date, eff)  # let the user re-run in another model
    if mkb is not None:
        await message.answer(_model_switch_caption(model, prefs.model_key), reply_markup=mkb)


async def ask_location(message: Message, rng: str, date: str | None):
    """No site given → offer saved sites + a "по координатам" option as inline buttons."""
    rows = [[b] for n in forecast.known_sites()
            if (b := _btn(n, f"pk|{rng}|{date or ''}|{n}")) is not None]
    rows.append([InlineKeyboardButton(text="📍 По координатам", callback_data=f"pc|{rng}|{date or ''}")])
    await message.answer("Для какой точки?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def _shortcut(message: Message, command: CommandObject, rng: str, date: str | None):
    if command.args and command.args.strip():
        await send_forecast(message, command.args.strip(), rng, date,
                            prefs=store.prefs(message.from_user.id))
    else:
        await ask_location(message, rng, date)


@dp.message(CommandStart())
@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP)


@dp.message(Command("sites"))
async def cmd_sites(message: Message):
    names = forecast.known_sites()
    if not names:
        await message.answer("Сохранённых стартов нет. Добавить: /add")
        return
    await message.answer("Сохранённые старты:\n" + "\n".join(f"• {n}" for n in names))


def _model_options() -> str:
    return " · ".join(f"{k} ({engine.model_label(k)})" for k in engine.MODELS)


def _model_keyboard(current: str) -> InlineKeyboardMarkup:
    """One button per model (current marked ✓); tapping sets it via an md| callback."""
    rows = []
    for k in engine.MODELS:
        btn = _btn(f"{engine.model_label(k)}{' ✓' if k == current else ''}", f"md|{k}")
        if btn is not None:
            rows.append([btn])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(Command("model"))
async def cmd_model(message: Message, command: CommandObject):
    """No argument → a button picker; /model <ключ> sets directly.
    Not a forecast request → no cooldown flag."""
    uid = message.from_user.id
    key = (command.args or "").strip().lower()
    if not key:
        cur = store.prefs(uid).model_key
        await message.answer(f"Текущая модель: {engine.model_label(cur)}. Выбери модель:",
                             reply_markup=_model_keyboard(cur))
        return
    if key not in engine.MODELS:  # список моделей — знание домена, а не хранилища
        await message.answer(f"⚠️ Неизвестная модель «{key}».\nДоступно: {_model_options()}")
        return
    try:
        store.set_model(uid, key)
    except Exception as e:  # noqa: BLE001 — отказ записи не должен молчать
        log.exception("set_model: write failed")
        await message.answer(f"⚠️ Не удалось сохранить выбор модели.\n({e})")
        return
    await message.answer(f"✅ Модель: {engine.model_label(key)} ({key}). "
                         f"Кэш обновится при следующем запросе.")


@dp.callback_query(F.data.startswith("md|"))
async def cb_pick_model(cb: CallbackQuery):
    """A model button from /model → set the global model, refresh the picker."""
    msg = await cb_message(cb)
    if msg is None:
        return
    try:
        _, key = cb.data.split("|", 1)
    except ValueError:
        await cb.answer()
        return
    if key not in engine.MODELS:
        await cb.answer("Неизвестная модель.", show_alert=True)
        return
    try:
        store.set_model(cb.from_user.id, key)
    except Exception as e:  # noqa: BLE001 — отказ записи не должен молчать
        log.exception("set_model: write failed")
        await cb.answer()
        await msg.answer(f"⚠️ Не удалось сохранить выбор модели.\n({e})")
        return
    await cb.answer(f"Модель: {engine.model_label(key)}")
    try:  # confirm + move the ✓ to the chosen model
        await msg.edit_text(f"✅ Модель: {engine.model_label(key)} ({key}). "
                            f"Кэш обновится при следующем запросе.",
                            reply_markup=_model_keyboard(key))
    except Exception:  # noqa: BLE001 — a stale-message edit can fail; not critical
        pass


@dp.callback_query(F.data.startswith("mf|"), flags={"forecast": True})
async def cb_switch_model(cb: CallbackQuery):
    """A model button under a forecast → re-render that forecast in that model.

    Выбор РАЗОВЫЙ: постоянная модель пилота не пишется. Её меняет только /model —
    иначе взгляд на альтернативную модель молча переопределял бы все дальнейшие
    прогнозы, включая те, что пользователь запросит завтра.
    """
    msg = await cb_message(cb)
    if msg is None:
        return
    parts = cb.data.split("|")
    if len(parts) != 5:
        await cb.answer()
        return
    _, key, site, rng, date = parts
    if key not in engine.MODELS:
        await cb.answer("Неизвестная модель.", show_alert=True)
        return
    await cb.answer(f"{engine.model_label(key)} — разово, пересчитываю…")
    await send_forecast(msg, site, rng, date or None, model=key,
                        prefs=store.prefs(cb.from_user.id))


def _settings_text(cfg: "store.Prefs") -> str:
    wind = "включён" if cfg.wind_correction_enabled else "выключен"
    return ("⚙️ Настройки\n\n"
            f"Средняя маршрутная скорость: {cfg.avg_route_speed_kmh:.0f} км/ч\n"
            f"Учёт ветра во времени прилёта: {wind}")


def _settings_keyboard(cfg: "store.Prefs") -> InlineKeyboardMarkup:
    speeds = [InlineKeyboardButton(text=f"{v}", callback_data=f"sp|{v}") for v in (20, 25, 30)]
    speeds.append(InlineKeyboardButton(text="Ввести свою", callback_data="sp|custom"))
    toggle = InlineKeyboardButton(
        text="Выключить учёт ветра" if cfg.wind_correction_enabled else "Включить учёт ветра",
        callback_data=f"sw|{0 if cfg.wind_correction_enabled else 1}")
    return InlineKeyboardMarkup(inline_keyboard=[speeds, [toggle]])


async def _show_settings(message: Message, uid: int):
    cfg = store.prefs(uid)
    await message.answer(_settings_text(cfg), reply_markup=_settings_keyboard(cfg))


@dp.message(Command("settings"))
async def cmd_settings(message: Message):
    await _show_settings(message, message.from_user.id)


@dp.callback_query(F.data.startswith("sp|"))
async def cb_set_speed(cb: CallbackQuery, state: FSMContext):
    value = cb.data.split("|", 1)[1]
    msg = await cb_message(cb)
    if value == "custom":
        await state.set_state(SettingsSpeed.value)
        if msg:
            await msg.answer("Введи среднюю маршрутную скорость в км/ч "
                             f"({store.SPEED_MIN:.0f}–{store.SPEED_MAX:.0f}):")
        return await cb.answer()
    store.set_speed(cb.from_user.id, float(value))
    if msg:
        await _show_settings(msg, cb.from_user.id)
    await cb.answer()


@dp.callback_query(F.data.startswith("sw|"))
async def cb_toggle_wind(cb: CallbackQuery):
    store.set_wind_correction(cb.from_user.id, cb.data.split("|", 1)[1] == "1")
    msg = await cb_message(cb)
    if msg:
        await _show_settings(msg, cb.from_user.id)
    await cb.answer()


@dp.message(SettingsSpeed.value)
async def settings_speed_value(message: Message, state: FSMContext):
    uid = message.from_user.id
    try:
        store.set_speed(uid, float((message.text or "").replace(",", ".").strip()))
    except ValueError as e:
        detail = str(e) if str(e).startswith("средняя") else (
            "Нужно число, например 25. Это средняя по маршруту с учётом наборов "
            "в термиках, а не скорость крыла.")
        return await message.answer(detail)
    await state.clear()
    await _show_settings(message, uid)


async def _finish_add(message: Message, name: str, lat: float, lon: float,
                      aspect_deg: float, notes: str = ""):
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    elev = await forecast.fetch_elevation(lat, lon)
    site = {"name": name, "aliases": [name.lower()], "lat": lat, "lon": lon,
            "elevation_m": elev, "aspect": engine.card(aspect_deg),
            "aspect_deg": aspect_deg, "notes": notes}
    try:
        store.add_site(site, added_by=message.from_user.id)
    except ValueError as e:
        await message.answer(f"⚠️ {e}")
        return
    except Exception as e:  # noqa: BLE001 — отказ записи не должен молчать
        # БД только на чтение бросает sqlite3.OperationalError, а он НЕ наследник
        # OSError — ловить его отдельно тут смысла не было (issubclass(...) is
        # False), поэтому берём широкий except, как уже сделано в cmd_model/
        # cb_pick_model.
        log.exception("add_site: write failed")
        await message.answer("⚠️ Не удалось сохранить старт — нет доступа к базе на запись.\n"
                             f"({e})")
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
        if err := store.name_error(name):
            await message.answer(f"⚠️ {err}")
            return
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


async def _add_got_coords(message: Message, state: FSMContext, lat: float, lon: float):
    await state.update_data(lat=lat, lon=lon)
    await state.set_state(AddSite.name)
    await message.answer("Название старта?")


@dp.message(AddSite.coords, F.location)
async def add_coords_pin(message: Message, state: FSMContext):
    await _add_got_coords(message, state, message.location.latitude, message.location.longitude)


@dp.message(AddSite.coords, F.text, ~F.text.startswith("/"))
async def add_coords(message: Message, state: FSMContext):
    coords = parse_coords(message.text)
    if coords is None:
        await message.answer("Не понял координаты. Пришли «широта, долгота» (напр. 42.47, 44.48) "
                             "или геоточку с карты. (/cancel — отмена)")
        return
    await _add_got_coords(message, state, *coords)


@dp.message(AddSite.name, F.text, ~F.text.startswith("/"))
async def add_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Пустое название. Введи имя старта.")
        return
    if err := store.name_error(name):
        await message.answer(f"{err}\nДругое имя?")
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
        await message.answer("Нечего отменять.")
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
        store.remove_site(name)
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
    await send_forecast(message, site, rng, prefs=store.prefs(message.from_user.id))


@dp.message(Command("scan"), flags={"forecast": True})
async def cmd_scan(message: Message):
    if not forecast.known_sites():
        await message.answer("Сохранённых стартов нет. Добавить: /add")
        return
    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            result = await forecast.scan_week(model=store.prefs(message.from_user.id).model_key)
    except Exception as e:  # noqa: BLE001 — surface any unexpected failure to the user
        log.exception("scan failed")
        await message.answer(f"⚠️ Ошибка: {e}")
        return
    text, kb = _scan_message(result)
    chunks = list(_chunks(text))
    for i, chunk in enumerate(chunks):  # keyboard rides the last chunk
        await message.answer(chunk, reply_markup=kb if i == len(chunks) - 1 else None)


@dp.callback_query(F.data.startswith(("llm|", "deep|")), flags={"forecast": True})
async def cb_analysis(cb: CallbackQuery):
    msg = await cb_message(cb)
    if msg is None:
        return
    parts, model = _split_cb(cb.data, 4)
    if parts is None:
        await cb.answer()
        return
    kind, site, rng, date = parts
    deep = kind == "deep"
    eff = model or store.prefs(cb.from_user.id).model_key
    await cb.answer("Считаю глубокий разбор…" if deep else "Считаю разбор…")
    try:
        async with ChatActionSender.typing(bot=msg.bot, chat_id=msg.chat.id):
            text = await forecast.get_analysis(site, rng, date or None, deep=deep, model=eff)
    except forecast.ForecastError as e:
        await msg.answer(f"⚠️ {e}")
        return
    except Exception as e:  # noqa: BLE001 — surface any unexpected failure to the user
        log.exception("analysis failed")
        await msg.answer(f"⚠️ Ошибка: {e}")
        return
    for chunk in _chunks(text):
        await msg.answer(_analysis_html(chunk), parse_mode="HTML")
    # keep the buttons — the user may want the other mode too


@dp.callback_query(F.data.startswith("pd|"), flags={"forecast": True})
async def cb_pick_day(cb: CallbackQuery, state: FSMContext):
    """A day button from an overview → detailed 1-day forecast for that date."""
    msg = await cb_message(cb)
    if msg is None:
        return
    parts, model = _split_cb(cb.data, 3)
    if parts is None:
        await cb.answer()
        return
    _, site, date = parts
    try:
        day = dt.date.fromisoformat(date)
    except ValueError:
        await cb.answer()
        return
    # the picker stays in the chat for days — a pressed date may be long gone
    # (−1 day of slack: the server's "today" can trail the site's timezone)
    if day < dt.date.today() - dt.timedelta(days=1):
        await cb.answer("Эта дата уже прошла — запроси свежий обзор.", show_alert=True)
        return
    if await state.get_state() == AdHoc.coords.state:
        await state.clear()  # передумал вводить координаты — выбрал день
    await cb.answer(f"Прогноз на {date}…")
    # keep the picker in place — the user may want another day too
    await send_forecast(msg, site, "1d", date, model=model,
                        prefs=store.prefs(cb.from_user.id))


@dp.callback_query(F.data.startswith("wg|"), flags={"forecast": True})
async def cb_wind_grid(cb: CallbackQuery):
    """A "ветер по высотам" button → PNG grid (altitude × hour) for that day."""
    msg = await cb_message(cb)
    if msg is None:
        return
    parts, model = _split_cb(cb.data, 3)
    if parts is None:
        await cb.answer()
        return
    _, site, date = parts
    try:
        day = dt.date.fromisoformat(date)
    except ValueError:
        await cb.answer()
        return
    if day < dt.date.today() - dt.timedelta(days=1):
        await cb.answer("Эта дата уже прошла — запроси свежий прогноз.", show_alert=True)
        return
    eff = model or store.prefs(cb.from_user.id).model_key
    await cb.answer("Считаю ветер по высотам…")
    try:
        async with ChatActionSender.typing(bot=msg.bot, chat_id=msg.chat.id):
            png = await forecast.get_wind_grid(site, date, model=eff)
    except forecast.ForecastError as e:
        await msg.answer(f"⚠️ {e}")
        return
    except Exception as e:  # noqa: BLE001 — surface any unexpected failure to the user
        log.exception("wind grid failed")
        await msg.answer(f"⚠️ Ошибка: {e}")
        return
    await msg.answer_photo(BufferedInputFile(png, filename="windgrid.png"))


@dp.callback_query(F.data.startswith("pk|"), flags={"forecast": True})
async def cb_pick_site(cb: CallbackQuery, state: FSMContext):
    msg = await cb_message(cb)
    if msg is None:
        return
    try:
        _, rng, date, name = cb.data.split("|", 3)
    except ValueError:
        await cb.answer()
        return
    if await state.get_state() == AdHoc.coords.state:
        await state.clear()  # передумал вводить координаты — выбрал сохранённый старт
    await cb.answer()
    try:
        await msg.edit_reply_markup(reply_markup=None)  # collapse the picker
    except Exception:  # noqa: BLE001
        pass
    await send_forecast(msg, name, rng, date or None,
                        prefs=store.prefs(cb.from_user.id))


@dp.callback_query(F.data.startswith("pc|"))
async def cb_pick_coords(cb: CallbackQuery, state: FSMContext):
    msg = await cb_message(cb)
    if msg is None:
        return
    try:
        _, rng, date = cb.data.split("|", 2)
    except ValueError:
        await cb.answer()
        return
    await cb.answer()
    await state.set_state(AdHoc.coords)
    await state.update_data(rng=rng, date=date)
    try:
        await msg.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await msg.answer("Пришли координаты — широта, долгота (напр. 42.47, 44.48) "
                     "или геоточку с карты.\n(/cancel — отмена)")


async def _adhoc_got_coords(message: Message, state: FSMContext, lat: float, lon: float):
    data = await state.get_data()
    await state.clear()
    rng, date = data.get("rng", "week"), (data.get("date") or None)
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    elev = await forecast.fetch_elevation(lat, lon)
    name = forecast.register_adhoc(lat, lon, elev)
    await send_forecast(message, name, rng, date,
                        prefs=store.prefs(message.from_user.id))


@dp.message(AdHoc.coords, F.location)
async def adhoc_coords_pin(message: Message, state: FSMContext):
    await _adhoc_got_coords(message, state, message.location.latitude, message.location.longitude)


@dp.message(AdHoc.coords, F.text, ~F.text.startswith("/"))
async def adhoc_coords(message: Message, state: FSMContext):
    coords = parse_coords(message.text)
    if coords is None:
        await message.answer("Не понял координаты. Пришли «широта, долгота» (напр. 42.47, 44.48) "
                             "или геоточку с карты. (/cancel — отмена)")
        return
    await _adhoc_got_coords(message, state, *coords)


ROUTE_HELP = ("Пришли маршрут списком координат — по точке на строку:\n\n"
              "/route завтра 11:30\n"
              "42.4776, 44.4787, старт\n"
              "42.2104, 44.6890, финиш\n\n"
              "Дата и время вылета необязательны: без времени берётся начало "
              "термического окна в первой точке. Файл GPX или KML тоже подойдёт.")


def _parse_when(args: str):
    """«завтра 11:30» → (дата, час вылета). Нераспознанные слова игнорируются."""
    date, departure = dt.date.today().isoformat(), None
    for token in (args or "").split():
        low = token.lower()
        if low == "сегодня":
            date = dt.date.today().isoformat()
        elif low == "завтра":
            date = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", token):
            date = token
        elif re.fullmatch(r"\d{1,2}:\d{2}", token):
            h, m = token.split(":")
            departure = int(h) + int(m) / 60.0
    return date, departure


_ROUTE_CACHE_PER_USER = 8
_route_cache: "OrderedDict[str, dict]" = OrderedDict()
_route_token = itertools.count(1)


def _remember_route(uid, points, name, date, departure):
    """Положить ЗАПРОС в кэш и вернуть короткий токен для callback_data.

    Хранится запрос, а не готовый профиль. Погода уже лежит в forecast._rcache,
    поэтому пересчёт профиля по нажатию кнопки — чистый процессор и ноль
    обращений к API. Взамен «другое время вылета» становится тем же вызовом
    get_route с другим departure, а не отдельной веткой кода, и расхождений
    между показанной карточкой и данными кнопки быть не может.

    `uid` — чей это маршрут. Кэш общий на процесс, но принадлежность записи
    хранится явно: без неё /saveroute брал последнюю запись вообще и в командном
    боте сохранял маршрут соседа, если тот посчитал свой между твоими /route и
    /saveroute.
    """
    token = format(next(_route_token), "x")
    _route_cache[token] = {"user_id": uid, "points": points, "name": name,
                           "date": date, "departure": departure}
    # Квота на пилота, а не на процесс: при общем потолке активный сосед вытеснял
    # чужие записи, и кнопки под ещё живой карточкой отвечали «маршрут устарел».
    mine = [t for t, e in _route_cache.items() if e["user_id"] == uid]
    for stale in mine[:-_ROUTE_CACHE_PER_USER]:
        del _route_cache[stale]
    return token


def _last_route_of(uid):
    """Последний маршрут, посчитанный ЭТИМ пилотом. None, если он ещё не считал."""
    for entry in reversed(_route_cache.values()):
        if entry["user_id"] == uid:
            return entry
    return None


def _route_keyboard(token, profile):
    """Кнопки под карточкой: характерные точки, разрез, разбор, другое время."""
    rows = []
    marks = [_btn(f"{k['mark']} {k['km']:.0f}", f"rt|{token}|pt|{k['km']:.0f}")
             for k in route.key_points(profile)]
    marks = [b for b in marks if b]
    if marks:
        rows.append(marks)
    actions = [_btn("📈 Разрез", f"rt|{token}|sec")]
    if analysis.available():
        actions.append(_btn("🤖 Разбор", f"rt|{token}|ai"))
    if profile.get("departure_scan"):
        actions.append(_btn("🕐 Другое время", f"rt|{token}|dep"))
    actions = [b for b in actions if b]
    if actions:
        rows.append(actions)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def _send_route(message: Message, points, name, date, departure, *, cfg, uid):
    """`cfg` — настройки пилота; как и у send_forecast, приходят параметром, потому
    что у сообщения под кнопкой автор — бот, а не тот, кто нажал.

    Обязателен и keyword-only: пропуск должен падать TypeError'ом здесь, а не
    AttributeError'ом в глубине скоринга.
    """
    try:
        profile = await forecast.get_route(points, name, date, departure, cfg=cfg)
    except forecast.ForecastError as e:
        return await message.answer(str(e))
    token = _remember_route(uid, points, name, date, departure)
    chunks = list(_chunks(route.render_card(profile)))
    for chunk in chunks[:-1]:
        await message.answer(chunk)
    await message.answer(chunks[-1], reply_markup=_route_keyboard(token, profile))


def _saved_route_from_args(uid: int, args):
    """«Гудаури Пасанаури завтра 11:30» → (точки, имя, остаток строки).

    Имя примеряется целиком, потом без последнего слова, и так далее: иначе
    маршрут с именем из нескольких слов вызвать было бы нельзя. Не нашлось —
    (None, None, исходные аргументы).
    """
    words = (args or "").split()
    for cut in range(len(words), 0, -1):
        name = " ".join(words[:cut])
        pts = route.points_from_rows(store.route_rows(uid, name))
        if pts:
            return pts, name, " ".join(words[cut:])
    return None, None, args or ""


@dp.message(Command("route"), flags={"forecast": True})
async def cmd_route(message: Message, command: CommandObject):
    uid = message.from_user.id
    cfg = store.prefs(uid)
    body = "\n".join((message.text or "").splitlines()[1:])
    if not body.strip():
        pts, name, rest = _saved_route_from_args(uid, command.args)
        if pts is None:
            return await message.answer(ROUTE_HELP)
        date, departure = _parse_when(rest)
        return await _send_route(message, pts, name, date, departure, cfg=cfg, uid=uid)
    date, departure = _parse_when(command.args or "")
    try:
        points = route.parse_text(body, first_line_no=2)  # первая строка — сама команда
    except route.RouteError as e:
        return await message.answer(f"❌ {e}")
    await _send_route(message, points, None, date, departure, cfg=cfg, uid=uid)


@dp.message(Command("saveroute"), flags={"forecast": True})
async def cmd_saveroute(message: Message, command: CommandObject):
    name = (command.args or "").strip()
    if not name:
        return await message.answer("Как назвать маршрут? /saveroute <имя>")
    err = store.name_error(name)
    if err:
        return await message.answer(f"❌ {err}")
    uid = message.from_user.id
    entry = _last_route_of(uid)
    if entry is None:
        return await message.answer("Сначала посчитай маршрут через /route.")
    pts = entry["points"]
    if len(pts) > route.MAX_POINTS:
        await message.answer(f"⚠️ слишком много точек: {len(pts)}, "
                             f"максимум {route.MAX_POINTS}")
        return
    # routes_list() пропускает битые записи (порченый JSON в points), поэтому
    # "name in routes_list(uid)" сказал бы "нет" про уже занятое имя с битой
    # записью и бот отчитался бы "Сохранил" вместо "Перезаписал".
    existed = store.route_exists(uid, name)
    try:
        store.route_save(uid, name, [[p.lat, p.lon, p.name] for p in pts])
    except ValueError as e:
        return await message.answer(f"❌ {e}")
    n = len(pts)
    await message.answer(("Перезаписал" if existed else "Сохранил") +
                         f" маршрут «{name}»: {n} "
                         f"{route.plural(n, 'точка', 'точки', 'точек')}.")


def _local_date(iso: str | None) -> str:
    """Дата сохранения в часовом поясе бота.

    store пишет UTC (однозначно и сортируемо), а пилот живёт в TZ старта:
    между 20:00 и полуночью по Тбилиси UTC-дата — это ещё вчера, и /routes
    показывал бы маршрут сохранённым «вчера» сразу после сохранения.
    """
    if not iso:
        return "—"
    try:
        return dt.datetime.fromisoformat(iso).astimezone().date().isoformat()
    except ValueError:
        # чужой формат в старой записи: лучше показать как есть, чем упасть
        return iso.split("T", 1)[0]


@dp.message(Command("routes"), flags={"forecast": True})
async def cmd_routes(message: Message):
    uid = message.from_user.id
    saved = store.routes_list(uid)
    if not saved:
        return await message.answer(
            "Сохранённых маршрутов нет. Посчитай маршрут через /route "
            "и сохрани: /saveroute <имя>")
    lines, rows = [], []
    for name in sorted(saved):
        pts = route.points_from_rows(store.route_rows(uid, name)) or []
        n = len(pts)
        # saved_at — полный ISO-таймстамп (store._now()), в UTC; показываем
        # дату в местном поясе бота, без времени, которое пилоту не нужно.
        saved_at = _local_date(saved[name].get("saved"))
        lines.append(f"• {name} — {route.total_km(pts):.0f} км, {n} "
                     f"{route.plural(n, 'точка', 'точки', 'точек')}, "
                     f"{saved_at}")
        btn = _btn(name, f"rr|{name}")
        if btn:
            rows.append([btn])
    await message.answer(
        "🗂 Сохранённые маршруты:\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None)


@dp.message(Command("delroute"), flags={"forecast": True})
async def cmd_delroute(message: Message, command: CommandObject):
    uid = message.from_user.id
    name = (command.args or "").strip()
    if store.route_delete(uid, name):
        return await message.answer(f"Удалил маршрут «{name}».")
    known = ", ".join(sorted(store.routes_list(uid))) or "пусто"
    await message.answer(f"Нет такого маршрута. Сохранённые: {known}")


async def _profile_from_token(cb: CallbackQuery, token: str, departure=None):
    """Пересчитать профиль по токену. None (и ответ пользователю), если токена нет."""
    entry = _route_cache.get(token)
    if entry is None:
        await cb.answer("Маршрут устарел, посчитай заново: /route", show_alert=True)
        return None
    dep = entry["departure"] if departure is None else departure
    return await forecast.get_route(entry["points"], entry["name"], entry["date"], dep,
                                    cfg=store.prefs(cb.from_user.id))


@dp.callback_query(F.data.regexp(r"^rt\|[^|]+\|pt\|"))
async def cb_route_point(cb: CallbackQuery):
    _prefix, token, _action, km = cb.data.split("|", 3)
    profile = await _profile_from_token(cb, token)
    if profile is None:
        return
    await cb.answer()
    msg = await cb_message(cb)
    if msg is None:
        return
    text = route.render_point_card(profile, float(km))
    await msg.answer(text or "Точка не найдена — посчитай маршрут заново.")


@dp.callback_query(F.data.regexp(r"^rt\|[^|]+\|sec$"))
async def cb_route_section(cb: CallbackQuery):
    _prefix, token, _action = cb.data.split("|")
    await cb.answer()
    msg = await cb_message(cb)
    if msg is None:
        return
    entry = _route_cache.get(token)
    if entry is None:
        return await msg.answer("Маршрут устарел, посчитай заново: /route")
    try:
        png = await forecast.get_route_section(
            entry["points"], entry["name"], entry["date"], entry["departure"],
            cfg=store.prefs(cb.from_user.id))
    except forecast.ForecastError as e:
        return await msg.answer(str(e))
    await msg.answer_photo(BufferedInputFile(png, filename="route_section.png"))


@dp.callback_query(F.data.regexp(r"^rt\|[^|]+\|ai$"))
async def cb_route_analysis(cb: CallbackQuery):
    _prefix, token, _action = cb.data.split("|")
    await cb.answer()
    msg = await cb_message(cb)
    if msg is None:
        return
    entry = _route_cache.get(token)
    if entry is None:
        return await msg.answer("Маршрут устарел, посчитай заново: /route")
    async with ChatActionSender.typing(bot=msg.bot, chat_id=msg.chat.id):
        try:
            text = await forecast.get_route_analysis(
                entry["points"], entry["name"], entry["date"], entry["departure"],
                cfg=store.prefs(cb.from_user.id))
        except forecast.ForecastError as e:
            return await msg.answer(str(e))
    for chunk in _chunks(text):
        await msg.answer(chunk)


_DEPARTURE_BUTTONS = 12     # клавиатура из двух десятков времён нечитаема


def _departure_keyboard(token, scan):
    """Времена вылета из скана, прорежённые до читаемого числа кнопок."""
    step = max(1, math.ceil(len(scan) / _DEPARTURE_BUTTONS))
    rows, row = [], []
    for e in scan[::step][:_DEPARTURE_BUTTONS]:
        mark = "🟢" if e["feasibility"] == "completable" else "·"
        btn = _btn(f"{mark} {e['departure']}", f"rt|{token}|dep|{e['departure']}")
        if btn is None:
            continue
        row.append(btn)
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


@dp.callback_query(F.data.regexp(r"^rt\|[^|]+\|dep$"))
async def cb_route_departures(cb: CallbackQuery):
    _prefix, token, _action = cb.data.split("|")
    profile = await _profile_from_token(cb, token)
    if profile is None:
        return
    await cb.answer()
    msg = await cb_message(cb)
    if msg is None:
        return
    scan = profile.get("departure_scan") or []
    if not scan:
        return await msg.answer("Скан времён вылета пуст — "
                                "термическое окно не открывается.")
    await msg.answer("Во сколько вылетаем?",
                     reply_markup=_departure_keyboard(token, scan))


@dp.callback_query(F.data.regexp(r"^rt\|[^|]+\|dep\|"))
async def cb_route_departure_pick(cb: CallbackQuery):
    _prefix, token, _action, hhmm = cb.data.split("|", 3)
    entry = _route_cache.get(token)
    if entry is None:
        return await cb.answer("Маршрут устарел, посчитай заново: /route",
                               show_alert=True)
    await cb.answer()
    msg = await cb_message(cb)
    if msg is None:
        return
    h, m = hhmm.split(":")
    await _send_route(msg, entry["points"], entry["name"], entry["date"],
                      int(h) + int(m) / 60.0, cfg=store.prefs(cb.from_user.id),
                      uid=cb.from_user.id)


@dp.callback_query(F.data.startswith("rr|"))
async def cb_saved_route(cb: CallbackQuery):
    name = cb.data.split("|", 1)[1]
    await cb.answer()
    msg = await cb_message(cb)
    if msg is None:
        return
    uid = cb.from_user.id
    pts = route.points_from_rows(store.route_rows(uid, name))
    if not pts:
        return await msg.answer("Маршрут не читается — сохрани его заново.")
    await _send_route(msg, pts, name, dt.date.today().isoformat(), None,
                      cfg=store.prefs(uid), uid=uid)


@dp.message(F.document, flags={"forecast": True})
async def route_document(message: Message):
    doc = message.document
    fname = (doc.file_name or "").lower()
    # Разборщик по расширению — знание route.parse_upload; здесь только фильтр
    # «файл вообще похож на маршрут», чтобы неизвестное расширение отвечало
    # своей репликой, а не текстом RouteError из route.py.
    if not fname.endswith((".gpx", ".kml", ".kmz")):
        return await message.answer("Я понимаю маршруты в форматах GPX и KML.")
    if (doc.file_size or 0) > route.MAX_GPX_BYTES:
        return await message.answer(
            f"❌ файл больше {route.MAX_GPX_BYTES // 1024} КБ — пришли маршрут покороче")
    buf = io.BytesIO()
    await message.bot.download(doc, destination=buf)
    try:
        points, name = route.parse_upload(fname, buf.getvalue())
    except route.RouteError as e:
        return await message.answer(f"❌ {e}")
    date, departure = _parse_when(message.caption or "")
    await _send_route(message, points, name, date, departure,
                      cfg=store.prefs(message.from_user.id),
                      uid=message.from_user.id)


@dp.message()
async def unhandled(message: Message):
    """Whatever no handler matched: random text, stickers, or a message typed into an
    FSM dialog the bot forgot after a restart (MemoryStorage). Silence looks broken —
    point at /help instead."""
    await message.answer("Не понял. Список команд: /help")


def _bootstrap_store() -> dict:
    """Схема, миграция, засев — плюс громкий отчёт о том, что не перенеслось.

    Старые JSON ищем и в каталоге БД, и в корне репозитория: под Docker они
    лежали в примонтированном томе (DB_PATH указывает туда же), а на
    systemd-пути бот запускается из корня репозитория, и старые дефолты
    ROUTES_FILE / SETTINGS_FILE / MODEL_FILE клали файлы рядом с кодом —
    при поиске только по каталогу БД маршруты и настройки такой установки
    не нашлись бы никогда.
    """
    repo_root = os.path.dirname(os.path.abspath(engine.__file__))
    data_dir = os.path.dirname(store.DB_PATH) or "."
    report = store.bootstrap(data_dir, guards.allowed_ids(),
                             os.path.join(repo_root, "sites.json"),
                             extra_dirs=(repo_root,),
                             valid_model_keys=set(engine.MODELS))
    log.info("store: %s", report)
    dropped = report.get("dropped") or []
    if dropped:
        # файлы к этому моменту уже переименованы в *.migrated: без этой строки
        # оператор никогда не узнает, что запись пропала и где её искать
        log.warning("МИГРАЦИЯ ПРОПУСТИЛА %d ЗАПИСЕЙ, в БД они не попали. "
                    "Исходные данные остались в файлах *.migrated. Причины: %s",
                    len(dropped), "; ".join(dropped))
    return report


def bootstrap() -> dict:
    """Всё, что должно случиться ДО первого запроса, с любой поверхности."""
    if not os.environ.get("BOT_TOKEN"):
        raise SystemExit("BOT_TOKEN не задан (см. .env.example)")
    return _bootstrap_store()


async def run_polling() -> None:
    """Long polling. Хранилище должно быть готово — см. bootstrap()."""
    bot = Bot(token=os.environ["BOT_TOKEN"])
    await bot.set_my_commands(BOT_COMMANDS)
    log.info("bot started, db: %s, sites: %s", store.DB_PATH, forecast.known_sites())
    await dp.start_polling(bot)


async def main():
    """Только чат — для запуска без HTTP-слоя (`python bot.py`)."""
    bootstrap()
    await run_polling()


if __name__ == "__main__":
    asyncio.run(main())

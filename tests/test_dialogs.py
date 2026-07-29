"""Dialog-branch tests: every command, FSM step, and inline-button route of the bot,
including the dead-end guards (stale buttons, lost state, bad input re-asks).
Network and LLM are patched out; routing/FSM/middleware are the real thing.
"""
import datetime as dt
import time

import pytest

import engine
import forecast
import store
import bot as botmod
from conftest import TEST_USER_ID, write_sites, DEFAULT_SITES
from tg import (buttons, callback_update, cb_answers, dice_update, kb_for,
                keyboards, location_update, markup_edits, media_groups, photos,
                text_update, texts)

TODAY = dt.date.today().isoformat()


# ---------------------------------------------------------------- basics

async def test_help_and_start(feed, session):
    await feed(text_update("/help"))
    await feed(text_update("/start"))
    assert texts(session) == [botmod.HELP, botmod.HELP]


async def test_sites_list(feed, session):
    await feed(text_update("/sites"))
    out = texts(session)[0]
    assert "Гудаури" in out and "Лалискури" in out


async def test_sites_empty_hints_add(feed, session):
    write_sites([])
    await feed(text_update("/sites"))
    assert "Сохранённых стартов нет" in texts(session)[0]
    assert "/add" in texts(session)[0]


async def test_unknown_text_and_nontext_get_catchall(feed, session):
    await feed(text_update("привет"))
    await feed(text_update("/foobar"))
    await feed(dice_update())
    assert texts(session) == ["Не понял. Список команд: /help"] * 3


# ---------------------------------------------------------------- /add one-shot

async def test_add_oneshot_ok(feed, session, elevation):
    await feed(text_update("/add Тест 42.5 44.5 Ю"))
    assert any("✅ Старт добавлен: Тест" in t for t in texts(session))
    assert store.find_site("Тест")["aspect_deg"] == 180


async def test_add_oneshot_bad_coords(feed, session):
    await feed(text_update("/add Тест 95 44.5 Ю"))
    assert "Координаты неверные" in texts(session)[0]


async def test_add_oneshot_bad_aspect(feed, session):
    await feed(text_update("/add Тест 42.5 44.5 ЮЮЮ"))
    assert "экспозиция" in texts(session)[0]


async def test_add_oneshot_name_too_long(feed, session):
    await feed(text_update(f"/add {'Д' * 25} 42.5 44.5 Ю"))
    assert "Слишком длинное имя" in texts(session)[0]


async def test_add_oneshot_name_with_pipe(feed, session):
    await feed(text_update("/add А|Б 42.5 44.5 Ю"))
    assert "«|»" in texts(session)[0]


async def test_add_oneshot_duplicate_name(feed, session):
    await feed(text_update("/add ГУДАУРИ 42.5 44.5 Ю"))
    assert "уже есть" in texts(session)[0]


async def test_add_oneshot_name_shadowed_by_alias(feed, session):
    await feed(text_update("/add гуда 42.5 44.5 Ю"))
    assert "псевдоним" in texts(session)[0]


# ---------------------------------------------------------------- /add interactive

async def test_add_interactive_happy_path_decimal_comma(feed, session, elevation):
    await feed(text_update("/add"))
    assert "Пришли координаты" in texts(session)[0]
    await feed(text_update("42,47, 44,48"))  # decimal commas → 42.47, 44.48
    assert "Название старта?" in texts(session)[-1]
    await feed(text_update("Новый"))
    assert "Экспозиция" in texts(session)[-1]
    await feed(text_update("Ю"))
    assert "Заметка" in texts(session)[-1]
    await feed(text_update("-"))
    assert any("✅ Старт добавлен: Новый" in t for t in texts(session))
    site = store.find_site("Новый")
    assert site["lat"] == 42.47 and site["lon"] == 44.48 and site["notes"] == ""


async def test_add_interactive_location_pin_and_notes(feed, session, elevation):
    await feed(text_update("/add"))
    await feed(location_update(41.0, 43.0))
    assert "Название старта?" in texts(session)[-1]
    await feed(text_update("Пин"))
    await feed(text_update("180"))
    await feed(text_update("юг, лучше утром"))
    site = store.find_site("Пин")
    assert site["lat"] == 41.0 and site["notes"] == "юг, лучше утром"


async def test_add_interactive_bad_coords_reask(feed, session, elevation):
    await feed(text_update("/add"))
    await feed(text_update("тут красиво"))
    assert "Не понял координаты" in texts(session)[-1]
    await feed(text_update("42 47 44 48"))  # 4 числа — переспросить, не брать первые два
    assert "Не понял координаты" in texts(session)[-1]
    await feed(text_update("42.47 44.48"))  # диалог жив, валидный ввод продолжает его
    assert "Название старта?" in texts(session)[-1]


async def test_add_interactive_long_name_reask(feed, session, elevation):
    await feed(text_update("/add"))
    await feed(text_update("42.47 44.48"))
    await feed(text_update("Д" * 25))
    assert "Слишком длинное имя" in texts(session)[-1]
    await feed(text_update("Коротко"))
    assert "Экспозиция" in texts(session)[-1]


async def test_add_interactive_bad_aspect_reask(feed, session, elevation):
    await feed(text_update("/add"))
    await feed(text_update("42.47 44.48"))
    await feed(text_update("Старт"))
    await feed(text_update("вбок"))
    assert "Попробуй ещё раз" in texts(session)[-1]
    await feed(text_update("225"))
    assert "Заметка" in texts(session)[-1]


async def test_add_interactive_commands_still_work_mid_dialog(feed, session):
    await feed(text_update("/add"))
    await feed(text_update("/sites"))  # команда не должна съедаться шагом координат
    assert any("Гудаури" in t for t in texts(session))


async def test_cancel_mid_dialog_and_idle(feed, session):
    await feed(text_update("/add"))
    await feed(text_update("/cancel"))
    assert "Отменено." in texts(session)[-1]
    await feed(text_update("42.47 44.48"))  # состояние сброшено — это уже не координаты
    assert texts(session)[-1] == "Не понял. Список команд: /help"
    await feed(text_update("/cancel"))  # вне диалога
    assert "Нечего отменять." in texts(session)[-1]


# ---------------------------------------------------------------- /removesite

async def test_removesite_branches(feed, session):
    await feed(text_update("/removesite"))
    assert "Формат:" in texts(session)[-1]
    await feed(text_update("/removesite Нету"))
    assert "не найден" in texts(session)[-1]
    await feed(text_update("/removesite Лалискури"))
    assert "удалён" in texts(session)[-1]
    assert [s["name"] for s in store.load_sites()] == ["Гудаури"]


# ---------------------------------------------------------------- forecast commands

async def test_today_with_site_sends_card_and_two_analysis_buttons(feed, session, fc_calls):
    await feed(text_update("/today Гудаури"))
    assert fc_calls == [("Гудаури", "1d", TODAY, None)]
    assert f"CARD Гудаури 1d {TODAY}" in texts(session)
    kb = kb_for(session, "Ещё:")
    datas = [b.callback_data for b in buttons(kb)]
    assert datas == [f"llm|Гудаури|1d|{TODAY}", f"deep|Гудаури|1d|{TODAY}", f"wg|Гудаури|{TODAY}"]
    assert kb_for(session, "📅 Подробно по дню:") is None  # day picker — только для обзоров


async def test_single_png_goes_as_photo(feed, session, fc_calls):
    await feed(text_update("/today Гудаури"))
    assert len(photos(session)) == 1 and not media_groups(session)


async def test_many_pngs_go_as_media_group(feed, session, monkeypatch):
    async def fake(site, rng, date=None, model=None):
        return "CARD", [b"a", b"b", b"c"]
    monkeypatch.setattr(forecast, "get_forecast", fake)
    await feed(text_update("/tomorrow Гудаури"))
    assert len(media_groups(session)) == 1 and not photos(session)


async def test_no_pngs_no_photo_messages(feed, session, monkeypatch):
    async def fake(site, rng, date=None, model=None):
        return "CARD", []
    monkeypatch.setattr(forecast, "get_forecast", fake)
    await feed(text_update("/today Гудаури"))
    assert not photos(session) and not media_groups(session)


async def test_overview_has_single_analysis_button_and_day_picker(feed, session, fc_calls):
    await feed(text_update("/week Гудаури"))
    assert fc_calls == [("Гудаури", "week", None, None)]
    kb = kb_for(session, "Ещё:")
    assert [b.callback_data for b in buttons(kb)] == ["llm|Гудаури|week|"]  # без deep
    picker = kb_for(session, "📅 Подробно по дню:")
    assert len(buttons(picker)) == 7  # холодный кэш → фолбэк на серверные даты


async def test_day_picker_uses_cached_site_local_dates(feed, session, fc_calls):
    start = dt.date.today() + dt.timedelta(days=1)  # смещённые даты, как из чужой таймзоны
    dates = [(start + dt.timedelta(days=i)).isoformat() for i in range(3)]
    _site, _date, key = forecast._resolve("Гудаури", "3d", None)
    forecast._fcache[key] = (time.monotonic() + 999, "c", [],
                             {"days_daytime": [{"date": d} for d in dates]}, "f", [], None)
    await feed(text_update("/threedays Гудаури"))
    picker = kb_for(session, "📅 Подробно по дню:")
    assert [b.callback_data for b in buttons(picker)] == [f"pd|Гудаури|{d}" for d in dates]


# ---------------------------------------------------------------- /scan


@pytest.fixture()
def fake_scan(monkeypatch):
    """Patch forecast.scan_week; set holder['result'] to the structure to return."""
    holder = {}

    async def fake():
        return holder["result"]

    monkeypatch.setattr(forecast, "scan_week", fake)
    return holder


async def test_scan_lists_sites_with_day_buttons(feed, session, fake_scan):
    d0, d1 = TODAY, (dt.date.today() + dt.timedelta(days=1)).isoformat()
    fake_scan["result"] = {
        "sites": [
            {"name": "Гудаури", "aspect": 180.0, "days": [
                {"date": d0, "emoji": "✅", "label": "лётный", "score": 90,
                 "wmax": 5, "gmax": 8, "dom": 180, "precip": 0.0, "wc": 0, "tmax": 20}]},
            {"name": "Лалискури", "aspect": 225.0, "days": [
                {"date": d1, "emoji": "⚠️", "label": "с оговорками", "score": 60,
                 "wmax": 7, "gmax": 10, "dom": 200, "precip": 0.0, "wc": 3, "tmax": 18}]},
        ],
        "empty": [], "failed": [],
    }
    await feed(text_update("/scan"))
    body = "\n".join(texts(session))
    assert "Гудаури" in body and "Лалискури" in body
    kb = keyboards(session)[-1]
    assert [b.callback_data for b in buttons(kb)] == [f"pd|Гудаури|{d0}", f"pd|Лалискури|{d1}"]


async def test_scan_button_routes_to_pick_day(feed, session, fc_calls):
    # a scan day button IS a pd| callback → the existing cb_pick_day handler
    await feed(callback_update(f"pd|Гудаури|{TODAY}"))
    assert fc_calls == [("Гудаури", "1d", TODAY, None)]


async def test_scan_no_flyable_days_message(feed, session, fake_scan):
    fake_scan["result"] = {"sites": [], "empty": ["Гудаури", "Лалискури"], "failed": []}
    await feed(text_update("/scan"))
    assert any("лётных окон нет" in t for t in texts(session))
    assert keyboards(session) == []  # no buttons when nothing is flyable


async def test_scan_no_sites_hints_add(feed, session):
    write_sites([])
    await feed(text_update("/scan"))
    assert any("/add" in t for t in texts(session))


async def test_scan_reports_failed_sites(feed, session, fake_scan):
    fake_scan["result"] = {
        "sites": [{"name": "Гудаури", "aspect": 180.0, "days": [
            {"date": TODAY, "emoji": "✅", "label": "лётный", "score": 90,
             "wmax": 5, "gmax": 8, "dom": 180, "precip": 0.0, "wc": 0, "tmax": 20}]}],
        "empty": [], "failed": ["Лалискури"],
    }
    await feed(text_update("/scan"))
    assert any("Не удалось получить" in t and "Лалискури" in t for t in texts(session))


async def test_forecast_command_parsing(feed, session, fc_calls):
    await feed(text_update("/forecast Гудаури 3дня"))
    assert fc_calls[-1] == ("Гудаури", "3d", None, None)
    await feed(text_update("/forecast Гудаури"))  # без диапазона → week
    assert fc_calls[-1] == ("Гудаури", "week", None, None)
    await feed(text_update("/forecast week"))  # только диапазон → выбор точки
    await feed(text_update("/forecast"))
    assert texts(session).count("Для какой точки?") == 2


async def test_shortcut_without_site_offers_sites_and_coords(feed, session):
    await feed(text_update("/today"))
    kb = kb_for(session, "Для какой точки?")
    datas = [b.callback_data for b in buttons(kb)]
    assert datas == [f"pk|1d|{TODAY}|Гудаури", f"pk|1d|{TODAY}|Лалискури", f"pc|1d|{TODAY}"]


async def test_forecast_error_reaches_user(feed, session, monkeypatch):
    async def fake(site, rng, date=None, model=None):
        raise forecast.ForecastError("Старт не найден: Х. /sites — список.")
    monkeypatch.setattr(forecast, "get_forecast", fake)
    await feed(text_update("/week Х"))
    assert "⚠️ Старт не найден: Х" in texts(session)[0]
    assert "/sites" in texts(session)[0]


async def test_unexpected_error_reaches_user(feed, session, monkeypatch):
    async def fake(site, rng, date=None, model=None):
        raise RuntimeError("boom")
    monkeypatch.setattr(forecast, "get_forecast", fake)
    await feed(text_update("/week Гудаури"))
    assert "⚠️ Ошибка: boom" in texts(session)[0]


# ---------------------------------------------------------------- legacy long site names

async def test_existing_long_name_drops_buttons_but_sends_card(feed, session, fc_calls):
    long_name = "Д" * 30  # 60 байт UTF-8 — callback_data не влезает
    write_sites(DEFAULT_SITES + [
        {"name": long_name, "aliases": [], "lat": 41.0, "lon": 43.0,
         "elevation_m": 100, "aspect": "Ю", "aspect_deg": 180.0, "notes": ""}])
    await feed(text_update(f"/week {long_name}"))
    assert f"CARD {long_name} week None" in texts(session)  # карточка дошла
    assert kb_for(session, "Ещё:") is None  # кнопка молча пропущена
    assert kb_for(session, "📅 Подробно по дню:") is None
    # и пикер точек не ломается целиком — длинное имя просто выпадает из списка
    session.requests.clear()
    await feed(text_update("/today"))
    labels = [b.text for b in buttons(kb_for(session, "Для какой точки?"))]
    assert long_name not in labels and "Гудаури" in labels and "📍 По координатам" in labels


# ---------------------------------------------------------------- analysis callbacks

async def test_llm_button_runs_fast_analysis(feed, session, an_calls):
    await feed(callback_update(f"llm|Гудаури|1d|{TODAY}"))
    assert an_calls == [("Гудаури", "1d", TODAY, False, None)]
    assert "АНАЛИЗ ГОТОВ" in texts(session)
    assert any(a.text and "Считаю разбор" in a.text for a in cb_answers(session))


async def test_deep_button_runs_deep_analysis(feed, session, an_calls):
    await feed(callback_update(f"deep|Гудаури|1d|{TODAY}"))
    assert an_calls == [("Гудаури", "1d", TODAY, True, None)]
    assert any(a.text and "глубокий" in a.text for a in cb_answers(session))


async def test_overview_llm_button_passes_no_date(feed, session, an_calls):
    await feed(callback_update("llm|Гудаури|week|"))
    assert an_calls == [("Гудаури", "week", None, False, None)]


async def test_analysis_forecast_error_reaches_user(feed, session, monkeypatch):
    async def fake(site, rng, date=None, deep=False, model=None):
        raise forecast.ForecastError("нет данных")
    monkeypatch.setattr(forecast, "get_analysis", fake)
    await feed(callback_update("llm|Гудаури|week|"))
    assert "⚠️ нет данных" in texts(session)


async def test_analysis_unexpected_error_reaches_user(feed, session, monkeypatch):
    async def fake(site, rng, date=None, deep=False, model=None):
        raise RuntimeError("llm down")
    monkeypatch.setattr(forecast, "get_analysis", fake)
    await feed(callback_update("llm|Гудаури|week|"))
    assert "⚠️ Ошибка: llm down" in texts(session)


async def test_malformed_callback_is_acked_silently(feed, session, an_calls):
    await feed(callback_update("llm|обрывок"))
    assert not texts(session) and not an_calls
    assert len(cb_answers(session)) == 1


async def test_adhoc_point_survives_a_restart(feed, session, an_calls):
    """Точка по координатам лежит в хранилище, а не в памяти процесса, поэтому
    кнопка под старым сообщением работает и после рестарта бота."""
    forecast.register_adhoc(42.47, 44.48, 1234)
    await feed(callback_update("llm|42.4700, 44.4800|week|"))
    assert an_calls == [("42.4700, 44.4800", "week", None, False, None)]


async def test_an_unknown_point_says_the_site_is_not_found(feed, session):
    # get_analysis НЕ патчим: _resolve падает до сети
    await feed(callback_update("llm|42.4700, 44.4800|week|"))
    assert any("не найден" in t for t in texts(session))


# ---------------------------------------------------------------- day picker callbacks

async def test_pick_day_sends_1d_forecast(feed, session, fc_calls):
    await feed(callback_update(f"pd|Гудаури|{TODAY}"))
    assert fc_calls == [("Гудаури", "1d", TODAY, None)]
    assert any(a.text and "Прогноз на" in a.text for a in cb_answers(session))


async def test_pick_day_past_date_is_rejected(feed, session, fc_calls):
    old = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    await feed(callback_update(f"pd|Гудаури|{old}"))
    assert not fc_calls
    alert = cb_answers(session)[0]
    assert "уже прошла" in alert.text and alert.show_alert


async def test_pick_day_yesterday_allowed_for_timezone_slack(feed, session, fc_calls):
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    await feed(callback_update(f"pd|Гудаури|{yesterday}"))
    assert fc_calls == [("Гудаури", "1d", yesterday, None)]


async def test_pick_day_malformed_date_is_acked_silently(feed, session, fc_calls):
    await feed(callback_update("pd|Гудаури|не-дата"))
    assert not fc_calls and not texts(session)


# ---------------------------------------------------------------- site picker callbacks

async def test_pick_site_collapses_picker_and_sends_forecast(feed, session, fc_calls):
    await feed(callback_update("pk|week||Гудаури"))
    assert fc_calls == [("Гудаури", "week", None, None)]
    assert len(markup_edits(session)) == 1  # пикер свёрнут


async def test_pick_site_with_date(feed, session, fc_calls):
    await feed(callback_update(f"pk|1d|{TODAY}|Лалискури"))
    assert fc_calls == [("Лалискури", "1d", TODAY, None)]


# ---------------------------------------------------------------- ad-hoc coordinates flow

async def test_adhoc_flow_text_coords(feed, session, fc_calls, elevation):
    await feed(callback_update("pc|week|"))
    assert "Пришли координаты" in texts(session)[-1]
    await feed(text_update("41,1234 43,9876"))  # decimal commas
    assert fc_calls == [("41.1234, 43.9876", "week", None, None)]
    assert store.adhoc_get("41.1234, 43.9876")["elevation_m"] == 1234


async def test_adhoc_flow_location_pin(feed, session, fc_calls, elevation):
    await feed(callback_update(f"pc|1d|{TODAY}"))
    await feed(location_update(41.5, 43.5))
    assert fc_calls == [("41.5000, 43.5000", "1d", TODAY, None)]


async def test_adhoc_bad_coords_reask_then_ok(feed, session, fc_calls, elevation):
    await feed(callback_update("pc|week|"))
    await feed(text_update("тут"))
    assert "Не понял координаты" in texts(session)[-1]
    assert "/cancel" in texts(session)[-1]
    await feed(text_update("41.5 43.5"))
    assert fc_calls == [("41.5000, 43.5000", "week", None, None)]


async def test_adhoc_state_cleared_by_site_pick(feed, session, fc_calls):
    await feed(callback_update("pc|week|"))  # вошёл в режим координат…
    await feed(callback_update("pk|week||Гудаури"))  # …но передумал и выбрал старт
    assert fc_calls == [("Гудаури", "week", None, None)]
    await feed(text_update("какой-то текст"))  # состояние сброшено — не парсится как координаты
    assert texts(session)[-1] == "Не понял. Список команд: /help"


async def test_adhoc_state_cleared_by_day_pick(feed, session, fc_calls):
    await feed(callback_update("pc|week|"))
    await feed(callback_update(f"pd|Гудаури|{TODAY}"))
    assert fc_calls == [("Гудаури", "1d", TODAY, None)]
    await feed(text_update("42 43"))
    assert texts(session)[-1] == "Не понял. Список команд: /help"


# ---------------------------------------------------------------- stale buttons

async def test_stale_buttons_answered_with_alert(feed, session, fc_calls, an_calls):
    for data in (f"llm|Гудаури|1d|{TODAY}", f"pd|Гудаури|{TODAY}",
                 "pk|week||Гудаури", "pc|week|"):
        await feed(callback_update(data, accessible=False))
    assert not fc_calls and not an_calls and not texts(session)
    alerts = cb_answers(session)
    assert len(alerts) == 4
    assert all("Кнопка устарела" in a.text and a.show_alert for a in alerts)


# ---------------------------------------------------------------- wind grid


@pytest.fixture()
def wg_calls(monkeypatch):
    """Patch forecast.get_wind_grid; returns recorded (site, date) calls."""
    calls = []

    async def fake(site, date, model=None):
        calls.append((site, date, model))
        return b"PNGBYTES"

    monkeypatch.setattr(forecast, "get_wind_grid", fake)
    return calls


async def test_today_offers_wind_grid_button(feed, session, fc_calls):
    await feed(text_update("/today Гудаури"))
    kb = kb_for(session, "Ещё:")
    datas = [b.callback_data for b in buttons(kb)]
    assert f"wg|Гудаури|{TODAY}" in datas


async def test_overview_has_no_wind_grid_button(feed, session, fc_calls):
    await feed(text_update("/week Гудаури"))
    kb = kb_for(session, "Ещё:")
    datas = [b.callback_data for b in buttons(kb)]
    assert not any(d.startswith("wg|") for d in datas)


async def test_wind_grid_button_sends_photo(feed, session, wg_calls):
    await feed(callback_update(f"wg|Гудаури|{TODAY}"))
    assert wg_calls == [("Гудаури", TODAY, None)]
    assert len(photos(session)) == 1
    assert any(a.text and "высот" in a.text for a in cb_answers(session))


async def test_wind_grid_past_date_rejected(feed, session, wg_calls):
    old = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    await feed(callback_update(f"wg|Гудаури|{old}"))
    assert not wg_calls
    alert = cb_answers(session)[0]
    assert "уже прошла" in alert.text and alert.show_alert


async def test_wind_grid_stale_button_answered(feed, session, wg_calls):
    await feed(callback_update(f"wg|Гудаури|{TODAY}", accessible=False))
    assert not wg_calls
    alert = cb_answers(session)[0]
    assert "Кнопка устарела" in alert.text and alert.show_alert


async def test_wind_grid_malformed_callback_acked(feed, session, wg_calls):
    await feed(callback_update("wg|обрывок"))
    assert not wg_calls and not photos(session)
    assert len(cb_answers(session)) == 1


async def test_wind_grid_error_reaches_user(feed, session, monkeypatch):
    async def fake(site, date, model=None):
        raise forecast.ForecastError("нет данных по высотам")
    monkeypatch.setattr(forecast, "get_wind_grid", fake)
    await feed(callback_update(f"wg|Гудаури|{TODAY}"))
    assert any("нет данных по высотам" in t for t in texts(session))


# ---------------------------------------------------------------- /model


async def test_model_no_arg_shows_picker_buttons(feed, session):
    await feed(text_update("/model"))
    kb = keyboards(session)[-1]
    datas = [b.callback_data for b in buttons(kb)]
    assert datas == ["md|auto", "md|ecmwf", "md|gfs", "md|icon"]
    labels = [b.text for b in buttons(kb)]
    assert any("Auto" in l and "✓" in l for l in labels)  # current model marked


async def test_model_button_sets_and_confirms(feed, session):
    await feed(callback_update("md|gfs"))
    assert store.prefs(TEST_USER_ID).model_key == "gfs"
    assert any(a.text and "GFS" in a.text for a in cb_answers(session))  # answered


async def test_model_button_unknown_key_alerts(feed, session):
    await feed(callback_update("md|bogus"))
    assert store.prefs(TEST_USER_ID).model_key == "auto"  # unchanged
    alert = cb_answers(session)[-1]
    assert "Неизвестная" in alert.text and alert.show_alert


async def test_forecast_offers_model_switch_buttons(feed, session, fc_calls):
    await feed(text_update("/today Гудаури"))
    kb = kb_for(session, "🌐 Другая модель (разово):")
    datas = [b.callback_data for b in buttons(kb)]
    assert datas == [f"mf|auto|Гудаури|1d|{TODAY}", f"mf|ecmwf|Гудаури|1d|{TODAY}",
                     f"mf|gfs|Гудаури|1d|{TODAY}", f"mf|icon|Гудаури|1d|{TODAY}"]


async def test_overview_model_switch_has_empty_date(feed, session, fc_calls):
    await feed(text_update("/week Гудаури"))
    kb = kb_for(session, "🌐 Другая модель (разово):")
    assert [b.callback_data for b in buttons(kb)][0] == "mf|auto|Гудаури|week|"


async def test_model_switch_button_does_not_change_the_permanent_model(feed, session, fc_calls):
    """Кнопка под прогнозом — разовый выбор. Постоянную модель меняет только
    /model: иначе один взгляд на альтернативную модель молча переопределял бы
    все последующие прогнозы, включая автоматические."""
    store.set_model(TEST_USER_ID, "auto")
    await feed(callback_update(f"mf|gfs|Гудаури|1d|{TODAY}"))
    assert store.prefs(TEST_USER_ID).model_key == "auto"    # постоянная не тронута
    assert fc_calls == [("Гудаури", "1d", TODAY, "gfs")]    # пересчёт в выбранной


async def test_model_switch_marks_the_one_off_model_and_names_the_permanent(feed, session, fc_calls):
    store.set_model(TEST_USER_ID, "auto")
    await feed(callback_update(f"mf|ecmwf|Гудаури|1d|{TODAY}"))
    caption = [t for t in texts(session) if t.startswith("🌐")][-1]
    assert "ECMWF" in caption and "разово" in caption
    assert "Auto" in caption and "/model" in caption        # где менять постоянную
    labels = [b.text for b in buttons(kb_for(session, caption))]
    assert any("ECMWF" in l and "✓" in l for l in labels)   # галочка на показанной
    assert not any("Auto" in l and "✓" in l for l in labels)


async def test_model_switch_unknown_key_alerts_and_does_not_render(feed, session, fc_calls):
    await feed(callback_update(f"mf|plasma|Гудаури|1d|{TODAY}"))
    alert = cb_answers(session)[-1]
    assert "Неизвестная" in alert.text and alert.show_alert
    assert fc_calls == []


async def test_model_switch_persists(feed, session):
    await feed(text_update("/model gfs"))
    assert any("GFS" in t for t in texts(session))
    assert store.prefs(TEST_USER_ID).model_key == "gfs"


async def test_model_invalid_key_lists_options(feed, session):
    await feed(text_update("/model plasma"))
    out = texts(session)[-1]
    assert "plasma" not in engine.MODELS
    assert "ecmwf" in out and "gfs" in out  # error lists valid keys
    assert store.prefs(TEST_USER_ID).model_key == "auto"  # unchanged


# ---------------------------------------------------------------- analysis HTML formatting


async def test_analysis_rendered_as_html_bold(feed, session, monkeypatch):
    from aiogram.methods import SendMessage

    async def fake(site, rng, date=None, deep=False, model=None):
        return "**Вердикт:** ок\nветер >7 м/с"

    monkeypatch.setattr(forecast, "get_analysis", fake)
    await feed(callback_update(f"llm|Гудаури|1d|{TODAY}"))
    sent = [m for m in session.requests if isinstance(m, SendMessage)]
    msg = sent[-1]
    assert msg.parse_mode == "HTML"          # rendered natively, not raw
    assert "<b>Вердикт:</b>" in msg.text     # **bold** → <b>
    assert "**" not in msg.text              # no raw markdown left
    assert "&gt;7" in msg.text               # literal > escaped, safe under HTML


# ---------------------------------------------------------------- разовая модель в кнопках


async def test_one_off_model_travels_to_every_button(feed, session, fc_calls):
    """ИИ-разбор и ветер по высотам должны считаться по той же модели, что
    показана: иначе разбор описывает не ту карточку, которую видит пользователь."""
    await feed(callback_update(f"mf|ecmwf|Гудаури|1d|{TODAY}"))
    more = [b.callback_data for b in buttons(kb_for(session, "Ещё:"))]
    assert f"llm|Гудаури|1d|{TODAY}|e" in more
    assert f"deep|Гудаури|1d|{TODAY}|e" in more
    assert f"wg|Гудаури|{TODAY}|e" in more


async def test_without_one_off_model_callbacks_are_unchanged(feed, session, fc_calls):
    """Обычный путь остаётся байт-в-байт: код дописывается только при разовом
    выборе, иначе он съедал бы запас длины у имён стартов."""
    await feed(text_update("/today Гудаури"))
    more = [b.callback_data for b in buttons(kb_for(session, "Ещё:"))]
    assert f"llm|Гудаури|1d|{TODAY}" in more
    assert not any(d.endswith("|e") or d.endswith("|a") for d in more)


async def test_analysis_button_carries_the_one_off_model(feed, session, an_calls):
    await feed(callback_update(f"llm|Гудаури|1d|{TODAY}|e"))
    assert an_calls == [("Гудаури", "1d", TODAY, False, "ecmwf")]


async def test_wind_grid_button_carries_the_one_off_model(feed, session, monkeypatch):
    seen = {}

    async def fake(site, date, model=None):
        seen["model"] = model
        return b"png"

    monkeypatch.setattr(forecast, "get_wind_grid", fake)
    await feed(callback_update(f"wg|Гудаури|{TODAY}|i"))
    assert seen["model"] == "icon"


async def test_day_picker_carries_the_one_off_model(feed, session, fc_calls):
    await feed(callback_update(f"pd|Гудаури|{TODAY}|g"))
    assert fc_calls == [("Гудаури", "1d", TODAY, "gfs")]


async def test_unknown_model_code_falls_back_to_the_permanent_model(feed, session, an_calls):
    """Устаревшая кнопка из старого сообщения не должна ронять обработчик."""
    await feed(callback_update(f"llm|Гудаури|1d|{TODAY}|z"))
    assert an_calls == [("Гудаури", "1d", TODAY, False, None)]


def test_every_model_button_fits_the_callback_limit():
    """Код модели съедает 2 байта из 64. Проверяем на реальных именах стартов."""
    for site in [s["name"] for s in store.load_sites()]:
        for code in engine.MODEL_CODES.values():
            for data in (f"llm|{site}|2weeks|2026-07-29|{code}",
                         f"deep|{site}|2weeks|2026-07-29|{code}",
                         f"wg|{site}|2026-07-29|{code}",
                         f"pd|{site}|2026-07-29|{code}"):
                assert len(data.encode("utf-8")) <= 64, data

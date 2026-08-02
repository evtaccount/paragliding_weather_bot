#!/usr/bin/env python3
"""Настоящие ответы API в файлы, без сети.

Типы фронтенда и моки его тестов должны описывать то, что домен отдаёт на
самом деле. Написанные по памяти, они расходятся с бэкендом молча: экран
читает поле, которого нет, и показывает пустоту вместо числа.

Каждая фикстура снимается ВЫЗОВОМ домена (engine.facts_1day, engine.wind_grid,
engine.overview_rows, forecast.scan_week, api.list_routes), а не собирается
литералом здесь. Форма ответа — знание домена; вторая копия, записанная в этом
скрипте руками, расходится с ним молча, и tests/test_api_fixtures_fresh.py её
не ловит: он перезапускает ЭТОТ скрипт и сравнивает результат с самим собой,
а для литерала это тавтология, а не проверка. Так и вышло дважды (финальное
ревью ветки, C1): /api/routes отдаёт ключ `saved` с полным таймстампом, а
фикстура писала `saved_at` с одной датой; /api/scan отдаёт экспозицию в
градусах, а фикстура писала румб «Ю».

Данные берутся из tests/fixtures.py — тех же, на которых стоят тесты домена.
Сеть подменяется на самом краю (forecast._fetch_main/_fetch_ceiling), чтобы
весь остальной путь — кэш, разбор, оценка, сборка ответа — оставался
настоящим.

    python scripts/dump_api_fixtures.py
"""
import asyncio
import datetime as dt
import json
import os
import pathlib
import sys
import tempfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# store читает DB_PATH на импорте, и снятие routes.json пишет настоящий
# маршрут настоящим store.route_save. Без этой строки скрипт добавлял бы
# служебный маршрут в рабочую базу бота (data/pgbot.db) — и в базу тестов,
# если запущен из pytest (tests/conftest.py выставляет DB_PATH). Присвоение,
# а не setdefault, именно поэтому.
os.environ["DB_PATH"] = os.path.join(
    tempfile.mkdtemp(prefix="pgbot_fixtures_"), "fixtures.db")

import api  # noqa: E402
import engine  # noqa: E402
import forecast  # noqa: E402
import store  # noqa: E402
import webauth  # noqa: E402
from tests import fixtures as fx  # noqa: E402

OUT = ROOT / "webapp" / "test" / "fixtures"

SITE = {"name": "Гудаури", "lat": 42.47, "lon": 44.48, "elevation_m": 2200,
        "aspect": "Ю", "aspect_deg": 180.0, "slope_deg": 25.0, "route_top_m": 3000.0,
        "aliases": ["gudauri"], "notes": ""}

# Старт без размеченной экспозиции — Facts.site.aspect/aspect_deg реально бывают
# null (engine.py: facts_1day — `card(aspect) if aspect is not None else None`).
SITE_NO_ASPECT = {"name": "Плато", "lat": 42.30, "lon": 44.20, "elevation_m": 1800,
                  "aspect": None, "aspect_deg": None, "slope_deg": None, "route_top_m": None,
                  "aliases": [], "notes": "экспозиция не размечена"}

# Настоящие координаты Гудаури, но склон смотрит на север — реальный старт бота
# зимой, не искусственная широта.
SITE_NORTH = {"name": "Гудаури-Север", "lat": 42.47, "lon": 44.48, "elevation_m": 2200,
             "aspect": "С", "aspect_deg": 0.0, "slope_deg": 25.0, "route_top_m": 3000.0,
             "aliases": [], "notes": ""}

# Ещё два старта библиотеки — только для скана: он ходит по ВСЕЙ библиотеке
# (forecast.scan_week: store.load_sites()), и без соседей у него не бывает ни
# "empty", ни "failed". Координаты настоящие (tests/conftest.py: DEFAULT_SITES,
# и Казбеги из tests/App).
SITE_WINDY = {"name": "Лалискури", "lat": 42.10, "lon": 45.30, "elevation_m": 900,
              "aspect": "ЮЗ", "aspect_deg": 225.0, "slope_deg": None, "route_top_m": None,
              "aliases": [], "notes": ""}
SITE_FAILING = {"name": "Казбеги", "lat": 42.66, "lon": 44.64, "elevation_m": 1750,
                "aspect": "З", "aspect_deg": 270.0, "slope_deg": None, "route_top_m": None,
                "aliases": [], "notes": ""}

WEEK_DATES = [f"2026-07-{d:02d}" for d in range(25, 32)]

FIXTURE_USER = webauth.TelegramUser(id=1)


class _StoppedClock:
    """Пространство имён datetime с остановленными часами.

    Подменяется в store только на время записи маршрута. Строку `saved`
    по-прежнему собирает сам store._now (store.py:88-89 — isoformat в UTC с
    точностью до секунды): заморожен ТОЛЬКО момент, формат остаётся доменным,
    иначе он оказался бы записан здесь второй копией — ровно тем, из-за чего
    приложение и приучилось к короткой дате вместо таймстампа. Замораживать
    нужно потому, что routes.json иначе менялся бы на каждый прогон и
    tests/test_api_fixtures_fresh.py краснел бы всегда, а не только когда
    домен поменял форму ответа.
    """
    timezone = dt.timezone

    class datetime:
        @staticmethod
        def now(tz=None):
            return dt.datetime(2026, 7, 25, 6, 33, 49, tzinfo=tz)


def _windy_day():
    """Задутый ветром обед + пропавший CIN утром + отсутствующий lifted_index.

    Даёт разом непустые assessment.warnings/vetoes_in_window/unchecked_vetoes,
    ключ "veto" в hourly_daytime (criteria.py:536-537 — compact() добавляет его
    только при непустых вето) и пропавший ключ в derived_peak_hour (engine.py:
    1070-1072 — словарь собирается через `if v is not None`, отсутствующий
    параметр не зануляется, а отсутствует). Пустые списки — тот же класс дыры
    в проверке типов, что never[]-совместимость массивов (см. task-3-report.md,
    Critical 2): без этого сценария assessment.warnings/vetoes_in_window/
    unchecked_vetoes в фикстурах всегда были бы [] и не ловили бы поломку типа.
    """
    n = 24
    wind = [2.0] * n
    gust = [4.0] * n
    cin = [60.0] * n
    for h in (12, 13, 14):          # обеденный порыв — вето gust_factor/gust_delta
        wind[h], gust[h] = 9.0, 16.0
    for h in (7, 8, 9, 10):         # CIN не пришёл — cape_cin уходит в unchecked
        cin[h] = None
    day = fx.om_1day(wind_speed_10m=wind, wind_gusts_10m=gust, convective_inhibition=cin)
    return fx.om_null(day, "lifted_index")   # параметр не посчитан — warnings: no_data:*


def _no_ceiling_day():
    """ECMWF (модель бота по умолчанию) не отдаёт boundary_layer_height и
    freezing_level_height — engine.py:_series_available видит пустой ряд, и
    facts_1day кладёт None в freezing_level_m/thermal_ceiling_m_agl/msl
    (engine.py:1005-1006,1050-1052)."""
    return fx.om_null(fx.om_1day(), "boundary_layer_height", "freezing_level_height")


def _december_day():
    """Декабрьский короткий день — солнце невысоко и в SITE_NORTH не набирается
    часов с нужной высотой: engine.sun_hours отдаёт термическое окно None
    (facts_1day кладёт его в thermal_window без проверки)."""
    return fx.om_1day(date="2026-12-15", sunrise="07:15", sunset="16:45")


def _windy_week():
    """Неделя, в которой лететь нельзя ни одного дня: 12 м/с у земли с порывами
    22 — вето по ветру (tests/test_engine_scan.py: те же 12/16 дают danger).
    Нужна, чтобы старт попал в scan.empty настоящим путём — через фильтр
    criteria.flyable в forecast.scan_week, а не строкой, дописанной руками."""
    return fx.om_overview(WEEK_DATES, wind_speed_10m=12.0, wind_gusts_10m=22.0,
                          wind_speed_10m_max=12.0, wind_gusts_10m_max=22.0)


async def _scan(sites: list[dict], bodies: dict[float, dict | None]) -> dict:
    """Настоящий forecast.scan_week на подставленных телах open-meteo.

    Подменяются только два края: поход в сеть (_fetch_main/_fetch_ceiling — та
    же заглушка, что у автоматической fixture tests/conftest.py) и библиотека
    стартов. Всё остальное — настоящее: фильтр лётных дней, engine.overview_rows,
    сборка {"sites"/"empty"/"failed"} и имена полей внутри (forecast.py:88-93).

    Тело выбирается по широте в URL (engine.build_url кладёт её как
    `latitude={site['lat']}`); None означает «open-meteo не ответил» — такой
    старт уходит в "failed" через asyncio.gather(return_exceptions=True).
    """
    async def fetch_main(url):
        for lat, body in bodies.items():
            if f"latitude={lat}&" in url:
                if body is None:
                    raise forecast.ForecastError("open-meteo: заглушка отказа")
                return body
        raise AssertionError(f"нет тела open-meteo для {url}")

    async def fetch_ceiling(url):
        return None

    forecast._fcache.clear()
    with mock.patch.object(forecast, "_fetch_main", fetch_main), \
         mock.patch.object(forecast, "_fetch_ceiling", fetch_ceiling), \
         mock.patch.object(forecast.store, "load_sites", lambda: sites):
        return await forecast.scan_week(model=engine.DEFAULT_MODEL_KEY)


async def _prefs() -> dict:
    """Настоящий GET /api/prefs: api.read_prefs поверх настоящего store.

    Раньше этот словарь собирался литералом — тем же способом, каким разошлись
    scan и routes (см. docstring скрипта): tests/test_api_fixtures_fresh.py
    перезапускает ЭТОТ скрипт и сравнивает результат с самим собой, поэтому
    литерал он не проверяет вовсе. Заметно это стало на поле ceiling_model
    (модель потолка термиков, финальное ревью ветки I1): дописанное в
    api._prefs_payload, оно обязано появиться в фикстуре само, а не второй
    рукописной копией рядом.

    Модель ставится явно, а не берётся дефолтом store ("auto"): фикстура
    описывает пилота, который выбор УЖЕ сделал, — иначе экраны тестировались
    бы только на «сервер решает сам». Скорость и поправка на ветер остаются
    дефолтами store (25 км/ч, включена) — это и есть их значения у нового
    пилота.
    """
    store.init()
    store.set_model(FIXTURE_USER.id, "ecmwf")
    return await api.read_prefs(user=FIXTURE_USER)


async def _routes() -> list:
    """Настоящий GET /api/routes: api.list_routes поверх настоящего store.

    Именно эндпоинт, а не store.routes_list: ключи ответа складывает
    api.py:list_routes (`{"name": name, **meta}`), и приложение читает их, а не
    словарь хранилища.
    """
    store.init()
    with mock.patch.object(store, "dt", _StoppedClock):
        store.route_save(FIXTURE_USER.id, "Гудаури — Коби",
                         [[42.47, 44.48, "старт"], [42.53, 44.51, "Коби"]])
    return await api.list_routes(user=FIXTURE_USER)


def write(name: str, payload) -> None:
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path.relative_to(ROOT))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    day = fx.om_1day()
    week = fx.om_overview(WEEK_DATES)

    write("facts_1d", engine.facts_1day(day, SITE))
    write("facts_1d_windy", engine.facts_1day(_windy_day(), SITE))
    write("facts_1d_no_ceiling", engine.facts_1day(_no_ceiling_day(), SITE_NO_ASPECT))
    write("facts_1d_no_window", engine.facts_1day(_december_day(), SITE_NORTH))
    # GET /api/forecast?range=3d|week|2weeks — ДРУГАЯ форма ответа, чем range=1d:
    # forecast.py:347-349 зовёт engine.facts_overview, а не facts_1day. Без этой
    # фикстуры экран обзора (задача 10) типизировал бы диапазонный ответ формой
    # однодневного — поля бы не совпали (site без "model", days_daytime вместо
    # hourly_daytime, другой набор ключей дня).
    write("forecast_3d", engine.facts_overview(week, SITE, "3d"))
    write("wind_grid", engine.wind_grid(day, SITE))
    write("overview_3d", engine.overview_rows(week, SITE))
    write("sites", [SITE])
    write("prefs", asyncio.run(_prefs()))
    write("scan", asyncio.run(_scan([SITE], {SITE["lat"]: week})))
    # Скан со стартом без лётных дней и стартом, который упал ошибкой — иначе
    # Scan.empty/Scan.failed всегда были бы [] и never[] тихо прошёл бы под
    # любой (в том числе неверный) тип элемента массива (см. Critical 2).
    write("scan_mixed", asyncio.run(_scan(
        [SITE, SITE_WINDY, SITE_FAILING],
        {SITE["lat"]: week, SITE_WINDY["lat"]: _windy_week(), SITE_FAILING["lat"]: None})))
    write("routes", asyncio.run(_routes()))


if __name__ == "__main__":
    main()

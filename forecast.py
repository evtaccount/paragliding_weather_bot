"""Forecast layer — open-meteo facts, with LLM analysis on demand.

Default path — get_forecast(): fetches open-meteo once, returns the factual card +
charts. NO LLM.

On demand — get_analysis(): runs Gemini over the SAME data that get_forecast already
fetched (cached facts) — no open-meteo re-request when the cache is warm. Falls back
to the deterministic rule text if Gemini is unavailable.

Gemini only reasons over real data; it never invents numbers.
"""
import asyncio
import copy
import datetime as dt
import logging
import os
import pathlib
import re
import shutil
import tempfile
import time

import httpx

import analysis
import criteria
import engine  # find_site, build_url, report_*, facts_*, RANGE_DAYS
import route
import settings

log = logging.getLogger("pgbot.forecast")

_TTL = float(os.environ.get("CACHE_TTL_MIN", "15")) * 60
# facts cache:    key -> (expires, card, png_bytes, facts, fallback_text)
# analysis cache: key -> (expires, text)   — so a repeat button press is free
_fcache: dict[tuple, tuple] = {}
_acache: dict[tuple, tuple[float, str]] = {}
# ad-hoc points from "по координатам" — resolved by name like saved sites, but not
# persisted; aspect is unknown (None), so the direction verdict is skipped.
_adhoc: dict[str, dict] = {}
# route caches: рельеф не меняется и живёт без срока, погода — по общему TTL
_terrain_cache: dict[tuple, list] = {}
_TERRAIN_CACHE_MAX = 64
_rcache: dict[tuple, tuple] = {}
ELEVATION_CHUNK = 100          # документированный потолок Elevation API
DEPARTURE_STEP_H = 0.5         # шаг скана времени вылета
ROUTE_HORIZON_DAYS = 15        # open-meteo отдаёт прогноз примерно на 16 суток вперёд


class ForecastError(Exception):
    """User-facing error (unknown site, bad range, upstream failure)."""


def known_sites():
    return [s["name"] for s in engine.load_sites()]


# День попадает в /scan, если его категория ≥ «удовлетворительная». Раньше фильтр
# сравнивал русские подписи, потому что эмодзи ⚠️ означал сразу два разных
# вердикта; теперь у каждой категории свой ключ, и сравнивать строки не нужно.


async def scan_week() -> dict:
    """Week overview across ALL saved sites, keeping only flyable days.

    Returns {"sites": [{"name", "aspect", "days": [row, ...]}], "empty": [name...],
    "failed": [name...]}. Each row is an engine.overview_rows() dict. Fetches run
    concurrently and reuse (warm) the same week cache /week uses.
    """
    sites = engine.load_sites()

    async def fetch(site):
        key = (site["name"], "week", None, engine.get_model_key())
        _c, _p, _f, _fb, rows, _grid = await _ensure(site, "week", None, key)
        return rows

    gathered = await asyncio.gather(*(fetch(s) for s in sites), return_exceptions=True)
    out: dict = {"sites": [], "empty": [], "failed": []}
    for site, res in zip(sites, gathered):
        if isinstance(res, Exception):
            log.warning("scan: %s failed: %s", site["name"], res)
            out["failed"].append(site["name"])
            continue
        fly = [r for r in res if criteria.flyable(r["category"])]
        if fly:
            out["sites"].append({"name": site["name"], "aspect": site.get("aspect_deg"), "days": fly})
        else:
            out["empty"].append(site["name"])
    return out


async def fetch_elevation(lat: float, lon: float) -> int:
    """Grid-cell elevation (m) for coordinates, from open-meteo. 0 on failure."""
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&current=temperature_2m")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url)
            r.raise_for_status()
            return round(float(r.json().get("elevation", 0)))
    except Exception as e:  # noqa: BLE001 — elevation is best-effort
        log.warning("elevation fetch failed: %s", e)
        return 0


def _daytime_summary(hourly: dict, lo: int = 9, hi: int = 18) -> dict:
    """Compact daytime wind summary from a light hourly block (no sunrise/sunset)."""
    t = hourly["time"]
    idx = [i for i, tt in enumerate(t) if lo <= int(tt[11:13]) <= hi] or list(range(len(t)))
    w = [hourly["wind_speed_10m"][i] for i in idx]
    g = [hourly["wind_gusts_10m"][i] for i in idx]
    p = hourly.get("precipitation", [0] * len(t))
    core = [i for i in idx if 11 <= int(t[i][11:13]) <= 16] or idx
    dom = engine.wind_from_avg([hourly["wind_direction_10m"][i] for i in core],
                               [max(hourly["wind_speed_10m"][i], 0.3) for i in core])
    return {"wind_ms": f"{min(w):.1f}–{max(w):.1f}", "gust_max_ms": round(max(g), 1),
            "wind_dir": f"{engine.card(dom)} ({round(dom)}°)",
            "precip_mm": round(sum(p[i] for i in idx), 1)}


async def _detail_context(site: dict, date: str) -> dict:
    """Extra data for the DEEP analysis: a 4-point ring around the launch (one
    multi-location request) + the previous day at the launch. Best-effort — a failed
    sub-fetch just omits that piece. This DOES query open-meteo (new data, by design)."""
    lat, lon, off = site["lat"], site["lon"], 0.05
    pts = [("старт", lat, lon), ("С", lat + off, lon), ("Ю", lat - off, lon),
           ("В", lat, lon + off), ("З", lat, lon - off)]
    ctx: dict = {}
    async with httpx.AsyncClient(timeout=30) as client:
        lats = ",".join(f"{p[1]:.4f}" for p in pts)
        lons = ",".join(f"{p[2]:.4f}" for p in pts)
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}"
               "&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m,precipitation"
               f"&wind_speed_unit=ms&timezone=auto&start_date={date}&end_date={date}")
        try:
            r = await client.get(url)
            r.raise_for_status()
            arr = r.json()
            if isinstance(arr, dict):  # a single location comes back as an object
                arr = [arr]
            ctx["surrounding_points_daytime"] = {
                name: _daytime_summary(obj["hourly"]) for (name, _, _), obj in zip(pts, arr)
            }
        except Exception as e:  # noqa: BLE001
            log.warning("deep context: surrounding points failed: %s", e)

        try:
            prev = (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()
            r = await client.get(engine.build_url(site, "1d", prev))
            r.raise_for_status()
            ctx["previous_day"] = engine.brief_1day(r.json(), site)
        except Exception as e:  # noqa: BLE001
            log.warning("deep context: previous day failed: %s", e)

    return ctx


_ADHOC_NAME_RE = re.compile(r"^-?\d+\.\d{4}, -?\d+\.\d{4}$")  # register_adhoc's name format


def register_adhoc(lat: float, lon: float, elev: int) -> str:
    """Register an ad-hoc point (unknown aspect) and return its lookup name."""
    name = f"{lat:.4f}, {lon:.4f}"
    _adhoc[name] = {"name": name, "aliases": [], "lat": lat, "lon": lon,
                    "elevation_m": elev, "aspect": None, "aspect_deg": None, "notes": ""}
    return name


def _resolve(site_name: str, rng: str, date: str | None):
    if rng not in engine.RANGE_DAYS:
        raise ForecastError(f"Неизвестный диапазон: {rng}")
    try:
        site = engine.find_site(site_name)
    except SystemExit:
        site = _adhoc.get(site_name)
        if site is None:
            if _ADHOC_NAME_RE.match(site_name):  # ad-hoc points don't survive a restart
                raise ForecastError("Эта точка по координатам больше не в памяти (бот перезапускался). "
                                    "Запроси её заново через «📍 По координатам».")
            raise ForecastError(f"Старт не найден: {site_name}. /sites — список.")
    if rng == "1d" and not date:
        date = dt.date.today().isoformat()
    return site, date, (site["name"], rng, date, engine.get_model_key())


def cached_dates(site_name: str, rng: str, date: str | None = None) -> list[str] | None:
    """Dates (site-local) of a cached overview — for the day-picker. None on a cold cache."""
    try:
        _site, _date, key = _resolve(site_name, rng, date)
    except ForecastError:
        return None
    entry = _fcache.get(key)
    if entry is None:
        return None
    days = entry[3].get("days_daytime") or []  # entry: (expires, card, pngs, facts, fallback)
    return [d["date"] for d in days] or None


def _purge(now: float):
    for cache in (_fcache, _acache, _rcache):
        for k in [k for k, v in cache.items() if v[0] <= now]:
            del cache[k]


async def _fetch_build(site: dict, rng: str, date: str | None):
    """Fetch open-meteo once and build (card, png_bytes, facts, fallback_text, rows, grid)."""
    url = engine.build_url(site, rng, date)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise ForecastError(f"Не удалось получить прогноз от open-meteo: {e}")
    if data.get("error"):
        raise ForecastError(f"open-meteo: {data.get('reason', 'ошибка запроса')}")

    out = tempfile.mkdtemp(prefix="pgfc_")
    try:
        if rng == "1d":
            # один расчёт лётности на карточку, графики и данные для LLM —
            # иначе три места считали бы его независимо и могли разойтись
            assessment = engine.assess_day(data, site)
            fallback, png_paths, card = engine.report_1day(data, site, out, assessment)
            facts = engine.facts_1day(data, site, assessment)
            rows = []
            grid = engine.wind_grid(data, site)
        else:
            fallback, png_paths, card = engine.report_overview(data, site, rng, out)
            facts = engine.facts_overview(data, site, rng)
            rows = engine.overview_rows(data, site)
            grid = None
        pngs = [pathlib.Path(p).read_bytes() for p in png_paths]
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return card, pngs, facts, fallback, rows, grid


async def _ensure(site: dict, rng: str, date: str | None, key: tuple):
    """Return (card, pngs, facts, fallback, rows, grid), fetching only on a cold cache."""
    now = time.monotonic()
    _purge(now)
    if key in _fcache:
        return _fcache[key][1:]
    card, pngs, facts, fallback, rows, grid = await _fetch_build(site, rng, date)
    _fcache[key] = (now + _TTL, card, pngs, facts, fallback, rows, grid)
    return card, pngs, facts, fallback, rows, grid


async def get_forecast(site_name: str, rng: str, date: str | None = None):
    """Factual card + charts. No LLM. rng: 1d | 3d | week | 2weeks."""
    site, date, key = _resolve(site_name, rng, date)
    card, pngs, _facts, _fallback, _rows, _grid = await _ensure(site, rng, date, key)
    return card, pngs


async def get_wind_grid(site_name: str, date: str) -> bytes:
    """PNG of the altitude × hour wind grid for a single day. Reuses the warm 1d cache
    (no re-fetch) and builds the image on demand — /today never pays for it unused."""
    site, date, key = _resolve(site_name, "1d", date)
    _card, _pngs, _facts, _fallback, _rows, grid = await _ensure(site, "1d", date, key)
    if not grid:
        raise ForecastError("Данные по высотам недоступны для этого дня.")
    out = tempfile.mkdtemp(prefix="pgwg_")
    try:
        import charts
        path = charts.wind_grid_png(grid, site, out)
        return pathlib.Path(path).read_bytes()
    finally:
        shutil.rmtree(out, ignore_errors=True)


# ---------------------------------------------------------------- маршрут
def _route_key(coords):
    return tuple((round(lat, 4), round(lon, 4)) for lat, lon in coords)


async def fetch_terrain(coords):
    """Высоты рельефа по списку координат порциями по 100. None при отказе.

    Copernicus DEM GLO-90, разрешение 90 м. Узкий перевал шириной 500 м может
    быть пропущен, острая вершина рядом с трассой — наоборот, дать ложное
    срабатывание ограничения по высоте.
    """
    out = []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for i in range(0, len(coords), ELEVATION_CHUNK):
                chunk = coords[i:i + ELEVATION_CHUNK]
                lats = ",".join(f"{lat:.4f}" for lat, _ in chunk)
                lons = ",".join(f"{lon:.4f}" for _, lon in chunk)
                r = await client.get("https://api.open-meteo.com/v1/elevation"
                                     f"?latitude={lats}&longitude={lons}")
                r.raise_for_status()
                out.extend(r.json()["elevation"])
    except Exception as e:  # noqa: BLE001 — рельеф best-effort, но молча не деградируем
        log.warning("route: elevation failed: %s", e)
        return None
    return out


async def _fetch_route_weather(url):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    return data if isinstance(data, list) else [data]


async def _ensure_terrain(grid):
    coords = [(lat, lon) for _km, lat, lon in grid]
    key = _route_key(coords)
    if key in _terrain_cache:
        return _terrain_cache[key]
    elev = await fetch_terrain(coords)
    if elev is not None:
        if len(_terrain_cache) >= _TERRAIN_CACHE_MAX:
            _terrain_cache.pop(next(iter(_terrain_cache)))
        _terrain_cache[key] = elev
    return elev


async def _ensure_route_weather(samples, date):
    """Погода по всем сэмплам одним запросом. Скорость и тумблер ветра в ключ не
    входят: они меняют только пересчёт времени, который дешёв и идёт поверх кэша."""
    coords = [(s.lat, s.lon) for s in samples]
    key = (_route_key(coords), date, engine.get_model_key())
    now = time.monotonic()
    _purge(now)
    if key in _rcache:
        return _rcache[key][1]
    tz = os.environ.get("TZ") or "Asia/Tbilisi"
    url = engine.route_weather_url(coords, date, tz)
    try:
        bodies = await _fetch_route_weather(url)
    except httpx.HTTPError as e:
        raise ForecastError(f"Не удалось получить прогноз от open-meteo: {e}")
    if len(bodies) != len(samples):
        raise ForecastError("open-meteo вернул другое число точек, чем запрошено")
    _rcache[key] = (now + _TTL, bodies)
    return bodies


def _hourly_facts(H, hour):
    """Срез почасовых переменных на дробный час прибытия."""
    out = {}
    for key in H:
        if key == "time":
            continue
        if key.startswith("precipitation"):
            out[key] = route.worst_of_hours(H[key], hour)
        else:
            out[key] = route.interp(H[key], hour)
    return out


def _check_date(date):
    today = dt.date.today()
    last = today + dt.timedelta(days=ROUTE_HORIZON_DAYS)
    try:
        want = dt.date.fromisoformat(date)
    except ValueError:
        raise ForecastError(f"Не понимаю дату: {date}") from None
    if not today <= want <= last:
        raise ForecastError(
            f"Прогноз доступен с {today.isoformat()} по {last.isoformat()}, "
            f"а запрошено {date}")


def _hhmm(hour):
    if hour is None:
        return None
    h, m = divmod(int(round(hour * 60)), 60)
    return f"{h % 24:02d}:{m:02d}"


def _nearest_site(sample, sites):
    """Сохранённый старт в радиусе SITE_MATCH_KM или None.

    Нужен ради экспозиции: у совпавшей точки начинает работать критерий
    направления ветра к склону, который для точки в воздухе не определён.
    """
    for site in sites.values():
        d, _ = route.haversine(route.Point(sample.lat, sample.lon),
                               route.Point(site["lat"], site["lon"]))
        if d / 1000.0 <= route.SITE_MATCH_KM:
            return site
    return None


def _elev_of(sample, body):
    """Высота для расчётов: рельеф из DEM, иначе высота грид-ячейки модели."""
    return sample.terrain_m if sample.terrain_m is not None else body.get("elevation", 0.0)


def _wind_at(sample, body, hour):
    """Ветер на рабочей высоте в точке на заданный час → (скорость км/ч, направление)."""
    H = body["hourly"]
    elev_m = _elev_of(sample, body)
    top = elev_m + (route.interp(H.get("boundary_layer_height"), hour) or 1500.0)
    ms, deg = engine.mean_wind_vector(H, int(hour), elev_m, elev_m + 500.0, top)
    return route.ms_to_kmh(ms), deg


def _ceiling_m(s):
    """Потолок термиков в метрах MSL: рельеф плюс глубина пограничного слоя.

    Берётся terrain_m (максимум по участку), а не terrain_point_m — тот же
    консервативный выбор, что уже сделан для working_band_m. Иначе потолок и
    рабочий коридор считались бы от разных отметок.
    """
    blh = (s.weather or {}).get("boundary_layer_height")
    if s.terrain_m is None or blh is None:
        return None
    return round(s.terrain_m + blh)


def _point_dict(s):
    return {
        "km": round(s.km, 1), "leg_length_km": round(s.leg_length_km, 1), "role": s.role,
        "lat": s.lat, "lon": s.lon, "name": s.name,
        "track_bearing_deg": round(s.track_bearing_deg),
        "eta": _hhmm(s.eta_h), "eta_fixed": _hhmm(s.eta_fixed_h),
        "terrain_m": None if s.terrain_m is None else round(s.terrain_m),
        "terrain_point_m": None if s.terrain_point_m is None else round(s.terrain_point_m),
        "is_terrain_peak": s.is_terrain_peak,
        "cloud_base_m": None if s.cloud_base_m is None else round(s.cloud_base_m),
        "working_band_m": None if s.working_band_m is None else round(s.working_band_m),
        "wind_along_kmh": None if s.wind_along_kmh is None else round(s.wind_along_kmh, 1),
        "wind_cross_kmh": None if s.wind_cross_kmh is None else round(s.wind_cross_kmh, 1),
        "wind_working_alt_kmh": None if s.wind_kmh is None else round(s.wind_kmh, 1),
        "wind_working_alt_dir": s.wind_dir_deg,
        "effective_ground_speed_kmh": None if s.gs_kmh is None else round(s.gs_kmh, 1),
        "crab_limited": s.crab_limited,
        "window": s.window,
        "time_margin_min": None if s.time_margin_min is None else round(s.time_margin_min),
        "w_star_ms": s.w_star_ms, "site_match": s.site_match, "weather": s.weather,
        "profile": s.role,
        "score": None if s.assessment is None else s.assessment.score,
        "category": None if s.assessment is None else s.assessment.category,
        "limiting": None if s.assessment is None else s.assessment.limiting_label,
        "vetoes": [] if s.assessment is None else criteria.veto_labels(s.assessment.vetoes),
        "storm_ahead": s.storm_ahead,
        "is_turnpoint": s.is_turnpoint,
        "thermal_ceiling_m": _ceiling_m(s),
        "subs": {} if s.assessment is None else s.assessment.subs,
        "groups": {} if s.assessment is None else s.assessment.groups,
    }


def _profile_for(sample):
    return criteria.PROFILES[sample.role]


def _raw_for(sample, body, date):
    """Входы критериев для одной точки.

    Срез погоды на момент прилёта уже посчитан спекой 1 (с интерполяцией и с
    «худшим из двух часов» для осадков). Из него собирается синтетический блок
    из одного часа, и по нему зовётся существующая engine.derive_hour — так ни
    одна формула производных величин не дублируется, а интерполяция не теряется.
    """
    synth = {k: [v] for k, v in sample.weather.items()}
    hour = int(sample.eta_h)
    synth["time"] = [f"{date}T{hour:02d}:00"]
    D = body["daily"]
    elev = _elev_of(sample, body)
    site = {"name": sample.name or "точка", "lat": sample.lat, "lon": sample.lon,
            "elevation_m": elev, "aspect_deg": sample.site_aspect_deg,
            "slope_deg": engine.SLOPE_DEG}
    ctx = {"date": date, "sunrise": D["sunrise"][0], "sunset": D["sunset"][0],
           "daylight_idx": [0], "thermal_window": sample.window}

    raw = engine.derive_hour(synth, 0, site, ctx)
    raw["wind_along"] = sample.wind_along_kmh
    raw["wind_cross"] = None if sample.wind_cross_kmh is None else abs(sample.wind_cross_kmh)
    raw["working_band"] = sample.working_band_m
    raw["time_margin"] = sample.time_margin_min
    raw["wind_working"] = None if sample.wind_kmh is None else sample.wind_kmh / route.MS_TO_KMH
    raw["ground_speed"] = sample.gs_kmh
    if sample.role == "enroute":
        # На маршруте вето по ветру проверяется по среднему ветру рабочего слоя,
        # а не по ветру на базе: пилот весь переход идёт именно в этом слое.
        raw["wind_at_base"] = raw["wind_working"]
    return raw


def _score_samples(samples, bodies, date):
    """Оценить каждую точку по профилю её роли и вернуть свёртку маршрута."""
    for s, body in zip(samples, bodies):
        s.assessment = (None if s.eta_h is None else
                        criteria.score_hour(_raw_for(s, body, date), int(s.eta_h),
                                            profile=_profile_for(s)))
    live = [s for s in samples if s.assessment is not None]
    scored = [{"km": s.km, "leg_length_km": s.leg_length_km,
               "eta": _hhmm(s.eta_h), "assessment": s.assessment} for s in live]
    if not scored:
        return criteria.RouteAssessment(None, *criteria.NO_DATA, feasibility="unknown")
    for s, ahead in zip(live, criteria.storm_ahead(scored)):
        s.storm_ahead = ahead
    return criteria.score_route(scored)


def _evaluate(samples, bodies, date, departure_h, cfg):
    """Времена прилёта, маршрутные величины и скоринг для ОДНОГО времени вылета.

    Работает на копии сэмплов: скан перебирает десятки вариантов, и мутировать
    общий список нельзя. Окна термической активности уже проставлены вызывающим
    и от времени вылета не зависят — они свойство точки, а не рейса.
    """
    work = copy.deepcopy(samples)
    notes = []
    speed = cfg["avg_route_speed_kmh"]

    def wind_for_segment(i, hour):
        pairs = []
        for s, body in ((work[i], bodies[i]), (work[i + 1], bodies[i + 1])):
            kmh, deg = _wind_at(s, body, hour)
            along, cross = route.wind_components(kmh, deg, work[i].track_bearing_deg)
            if along is not None:
                pairs.append((along, cross))
        if not pairs:
            return 0.0, 0.0
        return (sum(p[0] for p in pairs) / len(pairs),
                sum(p[1] for p in pairs) / len(pairs))

    route.fixed_eta(work, speed, departure_h)
    if cfg["wind_correction_enabled"]:
        route.march(work, speed, wind_for_segment, departure_h)
    else:
        for s in work:
            s.eta_h, s.gs_kmh = s.eta_fixed_h, speed

    # Данные запрошены на ОДИН день. Если прилёт уходит за полночь, дальше считать
    # нечем, и молчать об этом нельзя: пустая строка в таблице читалась бы как
    # «погода там неизвестна», а не как «расчёт оборвался».
    over = [s for s in work if s.eta_h is not None and s.eta_h >= 24.0]
    if over:
        notes.append(f"С {over[0].km:.0f} км прилёт выходит за сутки — "
                     "дальше не считаю, данные запрошены на один день")
        for s in over:
            s.eta_h = None

    for s, body in zip(work, bodies):
        if s.eta_h is None:
            continue
        H = body["hourly"]
        elev_m = _elev_of(s, body)
        s.weather = _hourly_facts(H, s.eta_h)
        s.cloud_base_m = route.cloud_base_m(s.terrain_m, s.weather.get("temperature_2m"),
                                            s.weather.get("dew_point_2m"))
        s.working_band_m = route.working_band_m(s.cloud_base_m, s.terrain_m)
        s.wind_kmh, s.wind_dir_deg = _wind_at(s, body, s.eta_h)
        s.wind_along_kmh, s.wind_cross_kmh = route.wind_components(
            s.wind_kmh, s.wind_dir_deg, s.track_bearing_deg)
        s.time_margin_min = route.time_margin_min(s.window, s.eta_h)
        s.w_star_ms = engine.w_star(s.weather.get("boundary_layer_height"),
                                    s.weather.get("shortwave_radiation"),
                                    s.weather.get("temperature_2m"), elev_m)

    verdict = _score_samples(work, bodies, date)
    return work, verdict, notes


def _departure_options(samples):
    """Времена вылета внутри термического окна первой точки, шагом полчаса."""
    w = samples[0].window
    if not w:
        return []
    n = int((w["end_hour"] - w["start_hour"]) / DEPARTURE_STEP_H) + 1
    return [w["start_hour"] + k * DEPARTURE_STEP_H for k in range(max(0, n))]


async def get_route(points, name, date, departure_h=None):
    """Профиль маршрута: два запроса, кэш, маршрутные величины, скоринг и вердикт."""
    _check_date(date)
    cfg = settings.get()
    samples, step = route.resample(points)
    total_km = samples[-1].km
    notes = []
    if step > route.SAMPLE_STEP_KM + 0.01:
        notes.append(f"Маршрут длинный: шаг увеличен до {step:.0f} км")

    grid = route.terrain_grid(points, total_km)
    elev = await _ensure_terrain(grid)
    if elev is None:
        notes.append("Рельеф недоступен — рабочий диапазон не посчитан")
    route.attach_terrain(samples, grid, elev, step_km=step)

    bodies = await _ensure_route_weather(samples, date)
    sites = {s["name"]: s for s in engine.load_sites()}

    # Окно термической активности и совпадение с сохранённым стартом не зависят
    # от времени вылета — считаются один раз, до перебора вариантов.
    for s, body in zip(samples, bodies):
        H, D = body["hourly"], body["daily"]
        s.window = route.thermal_window(date, s.lat, D["sunrise"][0], D["sunset"][0],
                                        H.get("boundary_layer_height"),
                                        H.get("shortwave_radiation"))
        matched = _nearest_site(s, sites)
        if matched is not None:
            s.site_match, s.site_aspect_deg = matched["name"], matched.get("aspect_deg")

    if departure_h is None:
        if not samples[0].window:
            raise ForecastError(
                "В первой точке термическое окно не открывается — задай время вылета "
                "вручную: /route <дата> ЧЧ:ММ")
        departure_h = float(samples[0].window["start_hour"])

    work, verdict, eval_notes = _evaluate(samples, bodies, date, departure_h, cfg)
    notes += eval_notes

    # Скан времени вылета и обратное направление считаются по УЖЕ полученным
    # данным: меняется только индексация по времени и порядок точек.
    scan = []
    for h in _departure_options(samples):
        _w, v, _n = _evaluate(samples, bodies, date, h, cfg)
        scan.append({"departure": _hhmm(h), "score": v.score, "feasibility": v.feasibility})
    completable = [e for e in scan if e["feasibility"] == "completable"]
    # Лучший из НЕПРОХОДИМЫХ не показывается намеренно: это предложение выбрать,
    # каким способом не долететь.
    best = max(completable, key=lambda e: e["score"] or 0) if completable else None

    rev_samples = route.reverse_samples(samples)
    _rw, rev_verdict, _rn = _evaluate(rev_samples, list(reversed(bodies)), date,
                                      departure_h, cfg)
    gain = (rev_verdict.score or 0) - (verdict.score or 0)

    return {
        "route": {
            "name": name, "date": date, "departure": _hhmm(departure_h),
            "timezone": os.environ.get("TZ") or "Asia/Tbilisi",
            "total_km": round(total_km, 1),
            "avg_route_speed_kmh": cfg["avg_route_speed_kmh"],
            "wind_correction_enabled": cfg["wind_correction_enabled"],
            "sample_step_km": round(step, 1), "sample_count": len(work),
            "model": engine.model_label(engine.get_model_key()),
        },
        "points": [_point_dict(s) for s in work],
        # Мелкая сетка рельефа отдаётся ЦЕЛИКОМ и со своим километражом.
        # terrain_grid делит каждое плечо на целое число равных частей, поэтому
        # шаг у разных плеч разный и «i * step_km» дал бы неверный километраж —
        # рельеф на разрезе молча съехал бы относительно погоды.
        "terrain": ({"km": [round(km, 3) for km, _lat, _lon in grid],
                     "elevations": elev} if elev else None),
        "verdict": {
            "score": verdict.score, "category": verdict.category,
            "label": verdict.label, "emoji": verdict.emoji,
            "feasibility": verdict.feasibility, "bottleneck": verdict.bottleneck,
            "blocked_at_km": verdict.blocked_at_km,
            "blocked_reason": criteria.veto_labels([verdict.blocked_reason])[0]
                              if verdict.blocked_reason else None,
            "flyable_until_km": (None if verdict.flyable_until_km is None
                                 else round(verdict.flyable_until_km, 1)),
            "mean_score": verdict.mean_score, "confidence": verdict.confidence,
        },
        "departure_scan": scan,
        "best_departure": best,
        "reverse": {"score": rev_verdict.score, "feasibility": rev_verdict.feasibility,
                    "better": gain >= criteria.REVERSE_GAIN},
        "notes": notes,
    }


async def get_analysis(site_name: str, rng: str, date: str | None = None, deep: bool = False) -> str:
    """LLM analysis over the cached facts.

    deep=False — reuse the data get_forecast already fetched; NO open-meteo re-request
                 when the cache is warm.
    deep=True  — additionally fetch surrounding points + the previous day (new data, by
                 design) and feed them as context. 1-day only.

    Falls back to the deterministic rule text when Gemini is unavailable.
    """
    site, date, base_key = _resolve(site_name, rng, date)
    mode = "deep" if deep else "fast"
    acache_key = base_key + (mode,)
    now = time.monotonic()
    _purge(now)
    if acache_key in _acache:
        log.info("analysis cache hit: %s", acache_key)
        return _acache[acache_key][1]

    card, _pngs, facts, fallback, _rows, _grid = await _ensure(site, rng, date, base_key)
    rules_tail = fallback[len(card):].strip() or fallback  # deterministic verdict tail

    if not analysis.available():
        log.info("analysis: rules (no GEMINI_API_KEY) — %s %s %s", site["name"], rng, mode)
        return "🧠 ИИ-разбор недоступен (не задан GEMINI_API_KEY). Разбор по правилам:\n\n" + rules_tail

    payload = facts
    if deep:  # additional data — this DOES query open-meteo
        ctx = await _detail_context(site, date)
        payload = {**facts, "context": ctx}

    t0 = time.monotonic()
    try:
        text = await asyncio.to_thread(analysis.analyze, payload, rng, deep)
        log.info("analysis: llm (gemini %s, %.1fs, %s) — %s %s",
                 analysis.model_name(), time.monotonic() - t0, mode, site["name"], rng)
    except Exception as e:  # noqa: BLE001 — any Gemini failure → rule-based text
        log.warning("analysis: rules (fallback — gemini failed: %s) — %s %s %s", e, site["name"], rng, mode)
        return rules_tail

    _acache[acache_key] = (time.monotonic() + _TTL, text)
    return text

"""Forecast layer — open-meteo facts, with LLM analysis on demand.

Default path — get_forecast(): fetches open-meteo once, returns the factual card +
charts. NO LLM.

On demand — get_analysis(): runs Gemini over the SAME data that get_forecast already
fetched (cached facts) — no open-meteo re-request when the cache is warm. Falls back
to the deterministic rule text if Gemini is unavailable.

Gemini only reasons over real data; it never invents numbers.
"""
import asyncio
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
import engine  # find_site, build_url, report_*, facts_*, RANGE_DAYS

log = logging.getLogger("pgbot.forecast")

_TTL = float(os.environ.get("CACHE_TTL_MIN", "15")) * 60
# facts cache:    key -> (expires, card, png_bytes, facts, fallback_text)
# analysis cache: key -> (expires, text)   — so a repeat button press is free
_fcache: dict[tuple, tuple] = {}
_acache: dict[tuple, tuple[float, str]] = {}
# ad-hoc points from "по координатам" — resolved by name like saved sites, but not
# persisted; aspect is unknown (None), so the direction verdict is skipped.
_adhoc: dict[str, dict] = {}


class ForecastError(Exception):
    """User-facing error (unknown site, bad range, upstream failure)."""


def known_sites():
    return [s["name"] for s in engine.load_sites()]


# A "suitable" day for the scan: flyable, or flyable-with-caveats. NOT маргинальный
# (which shares the ⚠️ emoji) and NOT нелётный — so filter on the label, not the emoji.
FLYABLE_LABELS = {"лётный", "с оговорками"}


async def scan_week() -> dict:
    """Week overview across ALL saved sites, keeping only flyable days.

    Returns {"sites": [{"name", "aspect", "days": [row, ...]}], "empty": [name...],
    "failed": [name...]}. Each row is an engine.overview_rows() dict. Fetches run
    concurrently and reuse (warm) the same week cache /week uses.
    """
    sites = engine.load_sites()

    async def fetch(site):
        key = (site["name"], "week", None)
        _c, _p, _f, _fb, rows, _grid = await _ensure(site, "week", None, key)
        return rows

    gathered = await asyncio.gather(*(fetch(s) for s in sites), return_exceptions=True)
    out: dict = {"sites": [], "empty": [], "failed": []}
    for site, res in zip(sites, gathered):
        if isinstance(res, Exception):
            log.warning("scan: %s failed: %s", site["name"], res)
            out["failed"].append(site["name"])
            continue
        fly = [r for r in res if r["label"] in FLYABLE_LABELS]
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
    return site, date, (site["name"], rng, date)


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
    for cache in (_fcache, _acache):
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
            fallback, png_paths, card = engine.report_1day(data, site, out)
            facts = engine.facts_1day(data, site)
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

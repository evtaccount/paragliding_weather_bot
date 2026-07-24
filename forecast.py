"""Forecast layer — resolves a saved site, fetches open-meteo, returns (text, png_bytes).

Pipeline:
  open-meteo (real numbers)
    ├── charts (Pillow) — visualisation of the facts
    ├── engine.report_* — factual card + deterministic (fallback) text
    ├── engine.facts_*  — real numbers extracted for the LLM
    └── analysis.analyze (Gemini) — INTERPRETS the facts
                                     ↳ default: short prose (card is shown separately)
                                     ↳ detail=True: thorough analysis
                                     ↳ on failure / no key: deterministic rule text

Gemini only reasons over real data; it never invents numbers.
"""
import asyncio
import datetime as dt
import logging
import os
import pathlib
import shutil
import tempfile
import time

import httpx

import analysis
import engine  # find_site, build_url, report_*, facts_*, RANGE_DAYS

log = logging.getLogger("pgbot.forecast")

# TTL cache: (site, rng, date, detail) -> (expires_at, text, [png_bytes]).
# Repeat requests within the TTL touch neither open-meteo nor Gemini.
_CACHE_TTL = float(os.environ.get("CACHE_TTL_MIN", "15")) * 60
_cache: dict[tuple, tuple[float, str, list[bytes]]] = {}


class ForecastError(Exception):
    """User-facing error (unknown site, bad range, upstream failure)."""


def known_sites():
    return [s["name"] for s in engine.load_sites()]


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
    """Extra data for the detailed analysis: a 4-point ring around the launch (one
    multi-location request) + the previous day at the launch. Best-effort — a failed
    sub-fetch just omits that piece."""
    lat, lon, off = site["lat"], site["lon"], 0.05
    pts = [("старт", lat, lon), ("С", lat + off, lon), ("Ю", lat - off, lon),
           ("В", lat, lon + off), ("З", lat, lon - off)]
    ctx: dict = {}
    async with httpx.AsyncClient(timeout=30) as client:
        # surrounding points — one multi-location call (comma-separated lat/lon)
        lats = ",".join(f"{p[1]:.4f}" for p in pts)
        lons = ",".join(f"{p[2]:.4f}" for p in pts)
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}"
               "&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m,precipitation"
               f"&wind_speed_unit=ms&timezone=auto&start_date={date}&end_date={date}")
        try:
            r = await client.get(url)
            r.raise_for_status()
            arr = r.json()
            if isinstance(arr, dict):  # single location comes back as an object
                arr = [arr]
            ctx["surrounding_points_daytime"] = {
                name: _daytime_summary(obj["hourly"]) for (name, _, _), obj in zip(pts, arr)
            }
        except Exception as e:  # noqa: BLE001
            log.warning("detail context: surrounding points failed: %s", e)

        # previous day at the launch
        try:
            prev = (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()
            r = await client.get(engine.build_url(site, "1d", prev))
            r.raise_for_status()
            ctx["previous_day"] = engine.brief_1day(r.json(), site)
        except Exception as e:  # noqa: BLE001
            log.warning("detail context: previous day failed: %s", e)

    return ctx


async def get_forecast(site_name: str, rng: str, date: str | None = None, detail: bool = False):
    """Return (telegram_text, [png_bytes, ...]) for a site + range.

    rng: "1d" | "3d" | "week" | "2weeks". For "1d", date defaults to today.
    detail=False → factual card + short LLM prose; detail=True → thorough analysis only.
    """
    if rng not in engine.RANGE_DAYS:
        raise ForecastError(f"Неизвестный диапазон: {rng}")
    try:
        site = engine.find_site(site_name)
    except SystemExit as e:
        raise ForecastError(str(e))

    if rng == "1d" and not date:
        date = dt.date.today().isoformat()

    key = (site["name"], rng, date, detail)
    now = time.monotonic()
    for k in [k for k, v in _cache.items() if v[0] <= now]:
        del _cache[k]
    if key in _cache:
        _, text, pngs = _cache[key]
        log.info("cache hit: %s", key)
        return text, pngs

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

    # Charts + factual card + deterministic (fallback) text + facts — all from the same data.
    out = tempfile.mkdtemp(prefix="pgfc_")
    try:
        if rng == "1d":
            fallback_text, png_paths, card = engine.report_1day(data, site, out)
            facts = engine.facts_1day(data, site)
        else:
            fallback_text, png_paths, card = engine.report_overview(data, site, rng, out)
            facts = engine.facts_overview(data, site, rng)
        pngs = [pathlib.Path(p).read_bytes() for p in png_paths]
    finally:
        shutil.rmtree(out, ignore_errors=True)

    # For the detailed view, enrich the facts with surrounding points + previous day.
    if detail and rng == "1d" and analysis.available():
        facts["context"] = await _detail_context(site, date)

    # LLM analysis over the real facts; fall back to the deterministic text otherwise.
    text = fallback_text
    if analysis.available():
        t0 = time.monotonic()
        try:
            llm = await asyncio.to_thread(analysis.analyze, facts, rng, detail)
            # detail: the card was already shown, so send only the analysis;
            # default: prepend the factual card to the short prose.
            text = llm if detail else f"{card}\n\n{llm}"
            log.info("analysis: llm (gemini %s, %.1fs, %s) — %s %s",
                     analysis.model_name(), time.monotonic() - t0,
                     "detail" if detail else "brief", site["name"], rng)
        except Exception as e:  # noqa: BLE001 — any Gemini failure → rule-based text
            log.warning("analysis: rules (fallback — gemini failed: %s) — %s %s",
                        e, site["name"], rng)
    else:
        log.info("analysis: rules (no GEMINI_API_KEY) — %s %s", site["name"], rng)

    _cache[key] = (time.monotonic() + _CACHE_TTL, text, pngs)
    return text, pngs

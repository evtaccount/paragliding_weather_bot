"""Forecast layer — resolves a saved site, fetches open-meteo, returns (text, png_paths).

Pipeline:
  open-meteo (real numbers)
    ├── charts (Pillow) — visualisation of the facts
    ├── engine.facts_*  — real numbers extracted for the LLM
    └── analysis.analyze (Gemini) — INTERPRETS the facts into a flying assessment
                                     ↳ on failure, falls back to the deterministic
                                       rule-based text from engine.report_*

Gemini only reasons over real data; it never invents numbers. Without a
GEMINI_API_KEY the bot still works, using the rule-based text.
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

# TTL cache: (site name, rng, date) -> (expires_at, text, [png_bytes]).
# Repeat requests within the TTL touch neither open-meteo nor Gemini.
_CACHE_TTL = float(os.environ.get("CACHE_TTL_MIN", "15")) * 60
_cache: dict[tuple, tuple[float, str, list[bytes]]] = {}


class ForecastError(Exception):
    """User-facing error (unknown site, bad range, upstream failure)."""


def known_sites():
    return [s["name"] for s in engine.load_sites()]


async def get_forecast(site_name: str, rng: str, date: str | None = None):
    """Return (telegram_text, [png_bytes, ...]) for a site + range.

    rng: "1d" | "3d" | "week" | "2weeks". For "1d", date defaults to today.
    """
    if rng not in engine.RANGE_DAYS:
        raise ForecastError(f"Неизвестный диапазон: {rng}")
    try:
        site = engine.find_site(site_name)
    except SystemExit as e:
        raise ForecastError(str(e))

    if rng == "1d" and not date:
        date = dt.date.today().isoformat()

    key = (site["name"], rng, date)
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

    # Charts + deterministic (fallback) text + facts — all from the same real data.
    out = tempfile.mkdtemp(prefix="pgfc_")
    try:
        if rng == "1d":
            fallback_text, png_paths = engine.report_1day(data, site, out)
            facts = engine.facts_1day(data, site)
        else:
            fallback_text, png_paths = engine.report_overview(data, site, rng, out)
            facts = engine.facts_overview(data, site, rng)
        pngs = [pathlib.Path(p).read_bytes() for p in png_paths]
    finally:
        shutil.rmtree(out, ignore_errors=True)

    # LLM analysis over the real facts; fall back to rules if Gemini is unavailable.
    text = fallback_text
    if analysis.available():
        try:
            text = await asyncio.to_thread(analysis.analyze, facts, rng)
        except Exception as e:  # noqa: BLE001 — any Gemini failure → rule-based text
            log.warning("LLM analysis failed (%s); using rule-based text", e)

    _cache[key] = (time.monotonic() + _CACHE_TTL, text, pngs)
    return text, pngs

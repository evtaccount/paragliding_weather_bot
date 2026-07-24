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


class ForecastError(Exception):
    """User-facing error (unknown site, bad range, upstream failure)."""


def known_sites():
    return [s["name"] for s in engine.load_sites()]


def _resolve(site_name: str, rng: str, date: str | None):
    if rng not in engine.RANGE_DAYS:
        raise ForecastError(f"Неизвестный диапазон: {rng}")
    try:
        site = engine.find_site(site_name)
    except SystemExit as e:
        raise ForecastError(str(e))
    if rng == "1d" and not date:
        date = dt.date.today().isoformat()
    return site, date, (site["name"], rng, date)


def _purge(now: float):
    for cache in (_fcache, _acache):
        for k in [k for k, v in cache.items() if v[0] <= now]:
            del cache[k]


async def _fetch_build(site: dict, rng: str, date: str | None):
    """Fetch open-meteo once and build (card, png_bytes, facts, fallback_text)."""
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
        else:
            fallback, png_paths, card = engine.report_overview(data, site, rng, out)
            facts = engine.facts_overview(data, site, rng)
        pngs = [pathlib.Path(p).read_bytes() for p in png_paths]
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return card, pngs, facts, fallback


async def _ensure(site: dict, rng: str, date: str | None, key: tuple):
    """Return (card, pngs, facts, fallback), fetching only on a cold cache."""
    now = time.monotonic()
    _purge(now)
    if key in _fcache:
        return _fcache[key][1:]
    card, pngs, facts, fallback = await _fetch_build(site, rng, date)
    _fcache[key] = (now + _TTL, card, pngs, facts, fallback)
    return card, pngs, facts, fallback


async def get_forecast(site_name: str, rng: str, date: str | None = None):
    """Factual card + charts. No LLM. rng: 1d | 3d | week | 2weeks."""
    site, date, key = _resolve(site_name, rng, date)
    card, pngs, _facts, _fallback = await _ensure(site, rng, date, key)
    return card, pngs


async def get_analysis(site_name: str, rng: str, date: str | None = None) -> str:
    """LLM analysis over the cached facts (no open-meteo re-request when warm).
    Falls back to the deterministic rule text when Gemini is unavailable."""
    site, date, key = _resolve(site_name, rng, date)
    now = time.monotonic()
    _purge(now)
    if key in _acache:
        log.info("analysis cache hit: %s", key)
        return _acache[key][1]

    card, _pngs, facts, fallback = await _ensure(site, rng, date, key)
    rules_tail = fallback[len(card):].strip() or fallback  # deterministic verdict tail

    if not analysis.available():
        log.info("analysis: rules (no GEMINI_API_KEY) — %s %s", site["name"], rng)
        return "🧠 ИИ-разбор недоступен (не задан GEMINI_API_KEY). Разбор по правилам:\n\n" + rules_tail

    t0 = time.monotonic()
    try:
        text = await asyncio.to_thread(analysis.analyze, facts, rng, True)
        log.info("analysis: llm (gemini %s, %.1fs) — %s %s",
                 analysis.model_name(), time.monotonic() - t0, site["name"], rng)
    except Exception as e:  # noqa: BLE001 — any Gemini failure → rule-based text
        log.warning("analysis: rules (fallback — gemini failed: %s) — %s %s", e, site["name"], rng)
        return rules_tail

    _acache[key] = (time.monotonic() + _TTL, text)
    return text

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

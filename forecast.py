"""Forecast layer — resolves a saved site, fetches open-meteo, returns (text, png_paths).

Reuses the skill engine (engine.py / charts.py) unchanged. The only new piece vs the
CLI skill is the network fetch, which here runs on the server (no sandbox restriction).
"""
import datetime as dt
import os
import tempfile

import httpx

import engine  # find_site, build_url, report_1day, report_overview, RANGE_DAYS


class ForecastError(Exception):
    """User-facing error (unknown site, bad range, upstream failure)."""


def known_sites():
    return [s["name"] for s in engine.load_sites()]


async def get_forecast(site_name: str, rng: str, date: str | None = None):
    """Return (telegram_text, [png_path, ...]) for a site + range.

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
    if rng == "1d":
        text, pngs = engine.report_1day(data, site, out)
    else:
        text, pngs = engine.report_overview(data, site, rng, out)
    return text, pngs

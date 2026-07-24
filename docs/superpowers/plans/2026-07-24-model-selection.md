# Meteo Model Selection (`/model`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick the open-meteo forecast model via a `/model` command (default ECMWF), applied to every forecast, degrading gracefully where the chosen model lacks the thermal-ceiling / freezing-level data.

**Architecture:** A model registry + a small persisted global setting in `engine.py`; `build_url` appends `&models=<id>`; `report_1day`/`facts_1day`/`charts` degrade when `boundary_layer_height`/`freezing_level_height` are absent; the `forecast` cache key gains the model dimension; `bot.py` adds `/model`.

**Tech Stack:** Python 3, aiogram 3, Pillow, pytest + pytest-asyncio. No new dependencies.

## Global Constraints

- Model registry is the single source of truth:
  ```python
  MODELS = {  # key → (UI label, open-meteo id)
      "auto":  ("Auto (best_match)", "best_match"),
      "ecmwf": ("ECMWF",             "ecmwf_ifs025"),
      "gfs":   ("GFS",               "gfs_seamless"),
      "icon":  ("ICON",              "icon_seamless"),
  }
  DEFAULT_MODEL_KEY = "ecmwf"
  ```
- The model is a GLOBAL setting (like `sites.json`), persisted to `model.json` in the same writable dir. Path: `MODEL_FILE = os.environ.get("MODEL_FILE") or os.path.join(os.path.dirname(SITES) or ".", "model.json")`, computed at import (so tests that set `SITES_FILE`/`MODEL_FILE` before import get an isolated file).
- Empirically confirmed on open-meteo: ECMWF (`ecmwf_ifs025`) returns everything EXCEPT `boundary_layer_height` and `freezing_level_height` (null). Pressure-level winds/directions/geopotentials, gusts, CAPE, temp, humidity, cloud — all present. So degradation is needed ONLY for those two variables; the wind grid, meteogram, wind-profile speed curves, and overviews are unaffected on every offered model.
- Requesting a variable a model doesn't provide does NOT error — open-meteo returns it as a null series. So `H_1D`/`H_OV`/`D_1D`/`D_OV` stay unchanged; only degradation logic is added.
- Wind in m/s; FROM-directions. No new dependencies. Reuse existing helpers.
- TDD: failing test first, minimal impl, verify, commit. One task = one commit.
- Run tests with `.venv/bin/python -m pytest -q` from repo root (NOT bare `python` — that has no pytest). Confirm by the pytest summary line.
- Repo `~/Developer/pet_projects/paragliding-bot`, branch `feature/model-selection`.
- No invented shorthand in user-facing copy; plain full Russian.

---

### Task 1: engine — model registry, persisted setting, `build_url` `&models=`

**Files:**
- Modify: `engine.py` — add `MODELS`, storage helpers, extend `build_url`
- Modify: `tests/conftest.py` — reset the model setting between tests
- Test: `tests/test_engine_model.py` (create)

**Interfaces:**
- Produces: `engine.MODELS`, `engine.DEFAULT_MODEL_KEY`, `engine.MODEL_FILE`, `engine.get_model_key() -> str`, `engine.set_model_key(key) -> None` (raises `ValueError` on unknown key), `engine.model_id(key) -> str`, `engine.model_label(key) -> str`. `build_url` now appends `&models=<model_id(get_model_key())>`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine_model.py`:

```python
"""engine model registry + persisted global setting + build_url &models=."""
import os

import engine


def _site():
    return {"name": "Тест", "lat": 42.0, "lon": 44.0, "elevation_m": 1500,
            "aspect": "Ю", "aspect_deg": 180.0, "notes": ""}


def _clear():
    if os.path.exists(engine.MODEL_FILE):
        os.remove(engine.MODEL_FILE)


def test_default_model_is_ecmwf():
    _clear()
    assert engine.get_model_key() == "ecmwf"
    assert engine.model_id("ecmwf") == "ecmwf_ifs025"
    assert engine.model_label("ecmwf") == "ECMWF"


def test_set_and_get_roundtrip():
    _clear()
    engine.set_model_key("gfs")
    assert engine.get_model_key() == "gfs"
    assert engine.model_id(engine.get_model_key()) == "gfs_seamless"


def test_set_rejects_unknown_key():
    _clear()
    import pytest
    with pytest.raises(ValueError):
        engine.set_model_key("nope")
    assert engine.get_model_key() == "ecmwf"  # unchanged


def test_corrupt_model_file_falls_back_to_default():
    with open(engine.MODEL_FILE, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert engine.get_model_key() == "ecmwf"


def test_build_url_includes_current_model():
    _clear()
    assert "models=ecmwf_ifs025" in engine.build_url(_site(), "week")
    engine.set_model_key("icon")
    assert "models=icon_seamless" in engine.build_url(_site(), "1d", "2026-07-25")
    _clear()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ~/Developer/pet_projects/paragliding-bot && .venv/bin/python -m pytest tests/test_engine_model.py -q`
Expected: FAIL — `AttributeError: module 'engine' has no attribute 'MODEL_FILE'` (or `MODELS`).

- [ ] **Step 3: Add the registry + storage helpers**

In `engine.py`, after the `SITES = ...` line near the top (where `DEFAULT_SITES`/`SITES` are defined), add:

```python
MODEL_FILE = os.environ.get("MODEL_FILE") or os.path.join(os.path.dirname(SITES) or ".", "model.json")

MODELS = {  # key → (UI label, open-meteo id)
    "auto":  ("Auto (best_match)", "best_match"),
    "ecmwf": ("ECMWF",             "ecmwf_ifs025"),
    "gfs":   ("GFS",               "gfs_seamless"),
    "icon":  ("ICON",              "icon_seamless"),
}
DEFAULT_MODEL_KEY = "ecmwf"


def model_id(key):
    return MODELS[key][1]


def model_label(key):
    return MODELS[key][0]


def get_model_key():
    """Current global model key; DEFAULT_MODEL_KEY when unset/invalid/corrupt."""
    try:
        with open(MODEL_FILE, encoding="utf-8") as f:
            key = json.load(f).get("model")
        return key if key in MODELS else DEFAULT_MODEL_KEY
    except (OSError, ValueError):
        return DEFAULT_MODEL_KEY


def set_model_key(key):
    """Persist the chosen model. Raises ValueError on an unknown key."""
    if key not in MODELS:
        raise ValueError(f"неизвестная модель: {key}. Доступно: {', '.join(MODELS)}")
    with open(MODEL_FILE, "w", encoding="utf-8") as f:
        json.dump({"model": key}, f, ensure_ascii=False)
```

(`json` and `os` are already imported at the top of engine.py.)

- [ ] **Step 4: Extend `build_url`**

In `engine.py::build_url`, the base string currently is:
```python
    base = (f"https://api.open-meteo.com/v1/forecast?latitude={site['lat']}&longitude={site['lon']}"
            "&wind_speed_unit=ms&timezone=auto")
```
Replace with:
```python
    base = (f"https://api.open-meteo.com/v1/forecast?latitude={site['lat']}&longitude={site['lon']}"
            f"&wind_speed_unit=ms&timezone=auto&models={model_id(get_model_key())}")
```

- [ ] **Step 5: Reset the model setting between tests**

In `tests/conftest.py`, inside the `fresh_state` autouse fixture (which already clears caches), add a line that removes the persisted model file so each test starts at the default. After the existing `forecast._adhoc.clear()` line (or alongside the other resets), add:
```python
    import os as _os
    if _os.path.exists(engine.MODEL_FILE):
        _os.remove(engine.MODEL_FILE)
```
`engine` is already imported in conftest.py (it imports `forecast`, which imports `engine`) — add `import engine` near the other imports if it is not already directly imported.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd ~/Developer/pet_projects/paragliding-bot && .venv/bin/python -m pytest tests/test_engine_model.py -q`
Expected: PASS (5 tests).

- [ ] **Step 7: Run the full suite (nothing else broke)**

Run: `.venv/bin/python -m pytest -q` — expect all prior tests still pass (build_url just gained a `&models=` suffix; no test asserts the exact full URL).

- [ ] **Step 8: Commit**

```bash
cd ~/Developer/pet_projects/paragliding-bot
git add engine.py tests/test_engine_model.py tests/conftest.py
git commit -m "engine: model registry + persisted /model setting; build_url &models="
```

---

### Task 2: engine + charts — degrade when ceiling/freezing data is absent

**Files:**
- Modify: `engine.py` — `_series_available` helper; `report_1day` and `facts_1day` degradation; model line in the card
- Modify: `charts.py` — `profile_png` draws the working-layer band only when blh is available
- Test: `tests/test_engine_degrade.py` (create)

**Interfaces:**
- Consumes: `engine.get_model_key`/`model_label` (Task 1).
- Produces: `report_1day` returns `(text, pngs, card_text)` with NO ceiling PNG and a "н/д" ceiling line when `boundary_layer_height` is a null series; `facts_1day` sets `thermal_ceiling_m_agl`/`_msl`/`freezing_level_m` to `None` and adds `site.model`. `charts.profile_png` renders without the working-layer band when blh is absent.

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine_degrade.py`. Two fixtures: one WITH blh/freezing, one where both are null (ECMWF-like). Reuse a complete 1d shape (all fields `report_1day`/`facts_1day` read).

```python
"""report_1day / facts_1day degrade gracefully when the model omits
boundary_layer_height and freezing_level_height (e.g. ECMWF)."""
import os
import tempfile

import engine


def _data(blh=1200.0, frz=4000.0):
    """One complete day; blh/frz=None models a ceiling-less model (ECMWF)."""
    hours = [f"2026-07-25T{h:02d}:00" for h in range(24)]
    n = len(hours)

    def c(v):
        return [v] * n

    return {
        "timezone": "Asia/Tbilisi",
        "daily": {
            "time": ["2026-07-25"], "sunrise": ["2026-07-25T05:00"], "sunset": ["2026-07-25T20:00"],
            "temperature_2m_max": [22.0], "temperature_2m_min": [10.0], "precipitation_sum": [0.0],
            "weather_code": [0], "sunshine_duration": [40000.0], "wind_speed_10m_max": [4.0],
            "wind_gusts_10m_max": [7.0], "wind_direction_10m_dominant": [180.0],
        },
        "hourly": {
            "time": hours,
            "temperature_2m": c(20.0), "dew_point_2m": c(8.0),
            "wind_speed_10m": c(2.0), "wind_gusts_10m": c(4.0), "wind_direction_10m": c(180.0),
            "precipitation": c(0.0), "cape": c(50.0),
            "cloud_cover_low": c(10.0), "cloud_cover_mid": c(10.0),
            "boundary_layer_height": c(blh), "freezing_level_height": c(frz),
            "wind_speed_925hPa": c(3.0), "wind_direction_925hPa": c(190.0), "geopotential_height_925hPa": c(760.0),
            "wind_speed_850hPa": c(4.0), "wind_direction_850hPa": c(200.0), "geopotential_height_850hPa": c(1500.0),
            "wind_speed_700hPa": c(6.0), "wind_direction_700hPa": c(210.0), "geopotential_height_700hPa": c(3000.0),
            "wind_speed_600hPa": c(9.0), "wind_direction_600hPa": c(220.0), "geopotential_height_600hPa": c(4200.0),
            "wind_speed_500hPa": c(13.0), "wind_direction_500hPa": c(230.0), "geopotential_height_500hPa": c(5600.0),
        },
    }


def _null_data():
    d = _data()
    d["hourly"]["boundary_layer_height"] = [None] * 24
    d["hourly"]["freezing_level_height"] = [None] * 24
    return d


def _site():
    return {"name": "Тест", "lat": 42.0, "lon": 44.0, "elevation_m": 1500,
            "aspect": "Ю", "aspect_deg": 180.0, "notes": ""}


def test_report_1day_full_has_ceiling_and_chart():
    out = tempfile.mkdtemp()
    text, pngs, _card = engine.report_1day(_data(), _site(), out)
    assert "Потолок:" in text and "н/д" not in text
    assert any("ceiling" in os.path.basename(p) for p in pngs)  # 02_ceiling.png present


def test_report_1day_degrades_without_blh():
    out = tempfile.mkdtemp()
    text, pngs, _card = engine.report_1day(_null_data(), _site(), out)
    assert "Потолок: н/д" in text            # no crash, explicit н/д
    assert not any("ceiling" in os.path.basename(p) for p in pngs)  # ceiling chart skipped
    assert any("meteogram" in os.path.basename(p) for p in pngs)    # other charts still there
    assert any("windprofile" in os.path.basename(p) for p in pngs)


def test_facts_1day_nulls_missing_and_reports_model():
    f = engine.facts_1day(_null_data(), _site())
    assert f["thermal_ceiling_m_agl"] is None and f["thermal_ceiling_m_msl"] is None
    assert f["freezing_level_m"] is None
    assert f["site"]["model"]  # model label present


def test_facts_1day_full_keeps_ceiling():
    f = engine.facts_1day(_data(), _site())
    assert f["thermal_ceiling_m_agl"] is not None and f["freezing_level_m"] is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ~/Developer/pet_projects/paragliding-bot && .venv/bin/python -m pytest tests/test_engine_degrade.py -q`
Expected: FAIL — the null-blh case raises `TypeError` in `max(blh[i] ...)` / has no "н/д" line and no `model` field.

- [ ] **Step 3: Add `_series_available` helper**

In `engine.py`, near the other helpers (after `daylight_idx`), add:
```python
def _series_available(H, key):
    """True if the hourly variable actually came back (present and not all-null)."""
    v = H.get(key)
    return bool(v) and any(x is not None for x in v)
```

- [ ] **Step 4: Degrade `report_1day`**

In `engine.py::report_1day`:

(a) After the line `clow = H["cloud_cover_low"]; dew = H["dew_point_2m"]; blh = H["boundary_layer_height"]`, add:
```python
    has_blh = _series_available(H, "boundary_layer_height")
```

(b) Replace the ceiling block (the lines computing `top_agl`, `top_msl`, `lcl_agl`, `blue`, currently around `top_agl = round(max(blh[i] for i in day))` … `blue = (clow[midday] < 15 and lcl_agl > blh[midday])`) so it only runs when blh exists:
```python
    lcl_agl = 122 * (temp[midday] - dew[midday])
    if has_blh:
        top_agl = round(max(blh[i] for i in day))
        top_msl = elev + top_agl
        blue = (clow[midday] < 15 and lcl_agl > blh[midday])
    else:
        top_agl = top_msl = None
        blue = False
```
(Keep the existing `midday = ...` line that precedes it; only the `top_agl/top_msl/lcl_agl/blue` computations change. If `lcl_agl` is already computed above this block, do not duplicate it — move/keep a single definition before the `if has_blh`.)

(c) The "🔆 Термичка" line currently reads `... if max(cape[i] for i in day) > 20 or top_agl > 500 ...`. Make it blh-safe:
```python
        f"🔆 Термичка: {'рабочая' if max(cape[i] for i in day) > 20 or (top_agl or 0) > 500 else 'слабая'}, пик {peak_lo:02d}–{peak_hi:02d}",
```

(d) The "🧗 Потолок" line — branch on `has_blh`:
```python
        (f"🧗 Потолок: ~{top_agl} м над стартом (~{top_msl} MSL){' · голубой' if blue else ''}"
         if has_blh else "🧗 Потолок: н/д (модель не даёт)"),
```

(e) The caveats block uses `blue` and `top_agl`. Guard the `top_agl` one:
```python
    if blue: cav.append("голубая термичка (без облаков-маркеров)")
    if has_blh and top_agl < 900: cav.append("низкий потолок — XC слабый")
```

(f) The charts block currently appends `meteogram_png`, `ceiling_png`, `profile_png`. Make ceiling conditional:
```python
    from charts import meteogram_png, ceiling_png, profile_png
    pngs.append(meteogram_png(data, site, out))
    if has_blh:
        pngs.append(ceiling_png(data, site, out))
    pngs.append(profile_png(data, site, out))
```

(g) Add the model source to the card. In `card_lines`, the second line is the coordinates/elevation/timezone line ending `· {data.get('timezone','')}`. Append the model label to it:
```python
        f"📍 {site['lat']:.3f}, {site['lon']:.3f} · {elev} м · {data.get('timezone','')} · {model_label(get_model_key())}",
```

- [ ] **Step 5: Degrade `facts_1day`**

In `engine.py::facts_1day`:

(a) After `clow = H["cloud_cover_low"]; dew = H["dew_point_2m"]; blh = H["boundary_layer_height"]`, add `has_blh = _series_available(H, "boundary_layer_height")` and `has_frz = _series_available(H, "freezing_level_height")`.

(b) Replace the `top_agl`/`blue` computation:
```python
    if has_blh:
        top_agl = round(max(blh[i] for i in day))
        blue = clow[tmax_i] < 15 and (elev + lcl_agl) > (elev + top_agl)
    else:
        top_agl = None
        blue = False
```

(c) In the returned dict, make the ceiling/freezing fields None-safe and add the model:
```python
        "freezing_level_m": round(H["freezing_level_height"][tmax_i]) if has_frz else None,
        "thermal_ceiling_m_agl": top_agl,
        "thermal_ceiling_m_msl": (elev + top_agl) if top_agl is not None else None,
```
and in the `"site": {...}` sub-dict, add `"model": model_label(get_model_key())`.

- [ ] **Step 6: Guard the working-layer band in `charts.profile_png`**

In `charts.py::profile_png`, the block:
```python
    top = elev + max(H["boundary_layer_height"][hidx[h]] for h in hours)
    cut = yf(top)
    d.rectangle([x0, cut, x1, y1], fill=GUST + (24,))
    d.line([x0, cut, x1, cut], fill=RAIN, width=1)
    d.text((x0 + S(6), cut - S(8)), f"потолок рабочего слоя ~{round(top)} м", font=_font(11, True), fill=RAIN, anchor="lb")
```
Wrap it so it only runs when blh values are present at the selected hours:
```python
    blh_vals = [H.get("boundary_layer_height", [None] * len(t))[hidx[h]] for h in hours]
    if any(v is not None for v in blh_vals):
        top = elev + max(v for v in blh_vals if v is not None)
        cut = yf(top)
        d.rectangle([x0, cut, x1, y1], fill=GUST + (24,))
        d.line([x0, cut, x1, cut], fill=RAIN, width=1)
        d.text((x0 + S(6), cut - S(8)), f"потолок рабочего слоя ~{round(top)} м", font=_font(11, True), fill=RAIN, anchor="lb")
```
(`t` is the hourly time list already bound earlier in `profile_png`.)

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd ~/Developer/pet_projects/paragliding-bot && .venv/bin/python -m pytest tests/test_engine_degrade.py -q`
Expected: PASS (4 tests).

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/python -m pytest -q` — all pass (existing 1d tests use best_match-shaped data with blh present, so they keep the ceiling).

- [ ] **Step 9: Commit**

```bash
cd ~/Developer/pet_projects/paragliding-bot
git add engine.py charts.py tests/test_engine_degrade.py
git commit -m "engine/charts: degrade ceiling+freezing when the model omits them; card shows model"
```

---

### Task 3: forecast — model in the cache key

**Files:**
- Modify: `forecast.py` — `_resolve` key + `scan_week` key include `engine.get_model_key()`
- Test: `tests/test_engine_model.py` (append a cache-isolation test)

**Interfaces:**
- Consumes: `engine.get_model_key` (Task 1).
- Produces: `_fcache`/`_acache` keys become `(site_name, rng, date, model_key)` (analysis appends its `mode` after). Switching the model no longer serves another model's cached result.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_engine_model.py`:

```python
import asyncio
import time as _time


def test_cache_key_includes_model(monkeypatch):
    _clear()
    import forecast

    calls = []

    async def fake_build(site, rng, date):
        calls.append((engine.get_model_key(), rng))
        return "card", [], {}, "fb", [], None  # 6-tuple _fetch_build contract

    monkeypatch.setattr(forecast, "_fetch_build", fake_build)

    site = engine.find_site("Гудаури")
    # warm the cache under ecmwf
    _s, _d, key1 = forecast._resolve("Гудаури", "week", None)
    asyncio.run(forecast._ensure(site, "week", None, key1))
    # switch model → a different key → must rebuild, not reuse
    engine.set_model_key("gfs")
    _s, _d, key2 = forecast._resolve("Гудаури", "week", None)
    assert key1 != key2
    asyncio.run(forecast._ensure(site, "week", None, key2))
    assert [c[0] for c in calls] == ["ecmwf", "gfs"]
    _clear()
```

(`Гудаури` is seeded by conftest.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ~/Developer/pet_projects/paragliding-bot && .venv/bin/python -m pytest tests/test_engine_model.py::test_cache_key_includes_model -q`
Expected: FAIL — `key1 == key2` (model not in key), so the second `_ensure` reuses the cache and `calls` has only one entry.

- [ ] **Step 3: Add the model to `_resolve`'s key**

In `forecast.py::_resolve`, the final line is:
```python
    return site, date, (site["name"], rng, date)
```
Replace with:
```python
    return site, date, (site["name"], rng, date, engine.get_model_key())
```

- [ ] **Step 4: Add the model to `scan_week`'s inline key**

In `forecast.py::scan_week`, the inner `fetch` builds `key = (site["name"], "week", None)`. Replace with:
```python
        key = (site["name"], "week", None, engine.get_model_key())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd ~/Developer/pet_projects/paragliding-bot && .venv/bin/python -m pytest tests/test_engine_model.py tests/test_dialogs.py tests/test_engine_scan.py -q`
Expected: PASS. Note: `tests/test_dialogs.py::test_day_picker_uses_cached_site_local_dates` hand-builds a `_fcache` key via `forecast._resolve(...)`, so it automatically gets the new 4-tuple key — verify it still passes. If any test hand-builds a *literal* 3-tuple cache key (not via `_resolve`), update it to include `engine.get_model_key()`; the scan tests mock `_ensure`/`load_sites` and pass keys through untouched, so they are unaffected.

- [ ] **Step 6: Commit**

```bash
cd ~/Developer/pet_projects/paragliding-bot
git add forecast.py tests/test_engine_model.py
git commit -m "forecast: include the model in the cache key so /model switches invalidate"
```

---

### Task 4: bot — the `/model` command

**Files:**
- Modify: `bot.py` — `cmd_model` handler; register in `BOT_COMMANDS` and `HELP`
- Test: `tests/test_dialogs.py` — `/model` show / set / invalid

**Interfaces:**
- Consumes: `engine.MODELS`, `engine.get_model_key`, `engine.set_model_key`, `engine.model_label`.
- Produces: `/model` (no arg → show current + options), `/model <key>` (set), invalid key / write error handled.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dialogs.py`:

```python
# ---------------------------------------------------------------- /model


async def test_model_shows_current_and_options(feed, session):
    await feed(text_update("/model"))
    out = texts(session)[-1]
    assert "ECMWF" in out  # default current model label
    assert "gfs" in out and "icon" in out and "auto" in out  # option keys listed


async def test_model_switch_persists(feed, session):
    await feed(text_update("/model gfs"))
    assert any("GFS" in t for t in texts(session))
    assert engine.get_model_key() == "gfs"


async def test_model_invalid_key_lists_options(feed, session):
    await feed(text_update("/model plasma"))
    out = texts(session)[-1]
    assert "plasma" not in engine.MODELS
    assert "ecmwf" in out and "gfs" in out  # error lists valid keys
    assert engine.get_model_key() == "ecmwf"  # unchanged
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/Developer/pet_projects/paragliding-bot && .venv/bin/python -m pytest tests/test_dialogs.py -k model -q`
Expected: FAIL — no `/model` handler (the catch-all replies "Не понял").

- [ ] **Step 3: Add the `cmd_model` handler**

In `bot.py`, add (near the other command handlers, e.g. after `cmd_sites`). Do NOT set `flags={"forecast": True}` — this is a setting, not a forecast request.

```python
def _model_options() -> str:
    return " · ".join(f"{k} ({engine.model_label(k)})" for k in engine.MODELS)


@dp.message(Command("model"))
async def cmd_model(message: Message, command: CommandObject):
    key = (command.args or "").strip().lower()
    if not key:
        cur = engine.get_model_key()
        await message.answer(
            f"Текущая модель: {engine.model_label(cur)} ({cur}).\n"
            f"Сменить: /model <ключ>\nДоступно: {_model_options()}")
        return
    try:
        engine.set_model_key(key)
    except ValueError:
        await message.answer(f"⚠️ Неизвестная модель «{key}».\nДоступно: {_model_options()}")
        return
    except OSError as e:  # read-only model.json in the container — don't fail silently
        log.exception("set_model_key: write failed")
        await message.answer("⚠️ Не удалось сохранить выбор модели — нет доступа к файлу на запись.\n"
                             f"({e.strerror or e})")
        return
    await message.answer(f"✅ Модель: {engine.model_label(key)} ({key}). "
                         f"Кэш обновится при следующем запросе.")
```

- [ ] **Step 4: Register in `BOT_COMMANDS` and `HELP`**

In `bot.py`, add to `BOT_COMMANDS` (e.g. after the `sites` entry):
```python
    BotCommand(command="model", description="Метеомодель: /model <auto|ecmwf|gfs|icon>"),
```
And add a line to the `HELP` string (near `/sites`):
```python
    "/model — метеомодель (auto · ecmwf · gfs · icon)\n"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd ~/Developer/pet_projects/paragliding-bot && .venv/bin/python -m pytest tests/test_dialogs.py -k model -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q` — all pass.

- [ ] **Step 7: Commit**

```bash
cd ~/Developer/pet_projects/paragliding-bot
git add bot.py tests/test_dialogs.py
git commit -m "bot: /model command to pick the meteo model (default ECMWF)"
```

---

### Task 5: Docs + full suite

**Files:**
- Modify: `README.md` — document `/model` and the ECMWF-default + ceiling caveat

**Interfaces:** none (documentation + verification).

- [ ] **Step 1: Update README**

Open `README.md`. Add a `/model` row to the Команды table (after `/sites` · `/help`, matching the existing table style):
```
| `/model <auto\|ecmwf\|gfs\|icon>` | выбор метеомодели (по умолчанию ECMWF); без аргумента — показать текущую |
```
And add a short note (one or two sentences, matching the file's «Заметки» section style) that the default model is ECMWF, and that ECMWF does not provide the thermal-ceiling / freezing-level data, so on ECMWF the «Потолок» shows «н/д» and the ceiling chart is omitted; `best_match`/ICON provide it. Read the surrounding lines first and match wording; no invented terms.

- [ ] **Step 2: Run the full suite**

Run: `cd ~/Developer/pet_projects/paragliding-bot && .venv/bin/python -m pytest -q`
Expected: all tests pass (confirm by the pytest summary line, not the exit code).

- [ ] **Step 3: Commit**

```bash
cd ~/Developer/pet_projects/paragliding-bot
git add README.md
git commit -m "README: document /model and the ECMWF ceiling caveat"
```

---

## Completion

After all tasks pass and the full suite is green:
- **REQUIRED SUB-SKILL:** Use superpowers:finishing-a-development-branch.
- Do NOT merge without explicit user approval ("сливай"/"мержим"). On approval: merge to `master` with `--no-ff`, delete the feature branch, then archive a short summary into the vault hub `_MOC Paragliding Bot.md` (Фичи + dated Архив планов entry), per the user's global rules.

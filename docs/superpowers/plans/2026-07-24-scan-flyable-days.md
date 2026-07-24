# `/scan` Flyable-Days-By-Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/scan` command that collects the week overview for every saved site, keeps only flyable days, and shows them grouped by site with one inline button per (site, day) that drills into the detailed 1-day forecast.

**Architecture:** Extract the per-day assessment loop already inside `engine.report_overview` into a reusable `engine.overview_rows(data, site)`. Cache those rows in `forecast._fcache` (shared with `/week`). `forecast.scan_week()` fans out over all sites concurrently and filters to flyable labels. `bot.cmd_scan` renders one message + a combined keyboard whose buttons reuse the existing `pd|<site>|<date>` callback (`cb_pick_day`).

**Tech Stack:** Python 3, aiogram 3, httpx, asyncio, pytest + pytest-asyncio.

## Global Constraints

- Flyable = day_status **label** in `{"лётный", "с оговорками"}`. Exclude `маргинальный` and `нелётный` (they must NOT be surfaced; note `маргинальный` also carries the ⚠️ emoji, so filter on label, never on emoji).
- Scan range is fixed to `week` (7 days). Do not parameterize.
- Inline `callback_data` must stay ≤ 64 bytes; always build day buttons through the existing `_btn()` helper. Reuse the existing `pd|<site>|<date>` callback — do NOT add a new callback type.
- Site names are already ≤ 40 UTF-8 bytes (enforced by `name_error` at add time).
- All new bot text is Russian, matching existing copy tone.
- The `_fcache` entry tuple gains a trailing `rows` element: `(expires, card, pngs, facts, fallback, rows)`. `facts` stays at index 3 (so `cached_dates` keeps working); `rows` is appended last.

---

### Task 1: `engine.overview_rows` — shared per-day assessment

**Files:**
- Modify: `engine.py` (add `overview_rows`, refactor `report_overview` at lines 285-327 to use it)
- Test: `tests/test_engine_scan.py` (new)

**Interfaces:**
- Produces: `overview_rows(data: dict, site: dict) -> list[dict]`. Each dict:
  `{"date": str "YYYY-MM-DD", "emoji": str, "label": str, "score": float, "tmax": float, "wmax": float, "gmax": float, "dom": float, "precip": float, "wc": int}`. One entry per day in `data["daily"]["time"]`, in order.

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine_scan.py`:

```python
"""engine.overview_rows: per-day flyability assessment shared by the card and scan."""
import engine


def _week_data():
    """Minimal 2-day open-meteo-shaped response: day 0 calm/flyable, day 1 windy."""
    days = ["2026-07-25", "2026-07-26"]
    hours = []
    for d in days:
        hours += [f"{d}T{h:02d}:00" for h in range(24)]
    n = len(hours)

    def per_hour(day0_val, day1_val):
        return [day0_val if t[:10] == days[0] else day1_val for t in hours]

    return {
        "timezone": "Asia/Tbilisi",
        "daily": {
            "time": days,
            "sunrise": [f"{d}T05:00" for d in days],
            "sunset": [f"{d}T20:00" for d in days],
            "temperature_2m_max": [22.0, 21.0],
            "temperature_2m_min": [10.0, 9.0],
            "wind_speed_10m_max": [4.0, 12.0],
            "wind_gusts_10m_max": [7.0, 16.0],
            "wind_direction_10m_dominant": [180.0, 180.0],
            "precipitation_sum": [0.0, 0.0],
            "weather_code": [0, 3],
            "sunshine_duration": [40000.0, 20000.0],
        },
        "hourly": {
            "time": hours,
            "temperature_2m": per_hour(20.0, 19.0),
            "wind_speed_10m": per_hour(4.0, 12.0),
            "wind_gusts_10m": per_hour(7.0, 16.0),
            "wind_direction_10m": per_hour(180.0, 180.0),
        },
    }


def _site():
    return {"name": "Тест", "lat": 42.0, "lon": 44.0, "elevation_m": 1500,
            "aspect": "Ю", "aspect_deg": 180.0, "notes": ""}


def test_overview_rows_flags_flyable_and_windy_days():
    rows = engine.overview_rows(_week_data(), _site())
    assert [r["date"] for r in rows] == ["2026-07-25", "2026-07-26"]
    assert rows[0]["label"] == "лётный" and rows[0]["emoji"] == "✅"
    # 12 m/s wind + 16 m/s gust into a headwind slope → not flyable
    assert rows[1]["label"].startswith("нелётный")
    assert rows[0]["score"] > rows[1]["score"]
    for key in ("wmax", "gmax", "dom", "precip", "wc", "tmax"):
        assert key in rows[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_engine_scan.py -v`
Expected: FAIL — `AttributeError: module 'engine' has no attribute 'overview_rows'`

- [ ] **Step 3: Add `overview_rows` and refactor `report_overview`**

In `engine.py`, insert `overview_rows` immediately **above** `def report_overview` (around line 285):

```python
def overview_rows(data, site):
    """Per-day daytime assessment for an overview response: one dict per day with
    date, status (emoji/label/score) and the headline numbers. Shared by
    report_overview (card + chart) and the multi-site scan."""
    D = data["daily"]; H = data["hourly"]; t = H["time"]; aspect = site["aspect_deg"]
    rows = []
    for k, dcode in enumerate(D["time"]):
        sr, ss = D["sunrise"][k], D["sunset"][k]
        idx = [i for i, tt in enumerate(t) if ymd(tt) == dcode and hour_of(sr) <= hour_of(tt) <= hour_of(ss)]
        dt_temp = [H["temperature_2m"][i] for i in idx] or [D["temperature_2m_max"][k]]
        dt_wind = [H["wind_speed_10m"][i] for i in idx] or [D["wind_speed_10m_max"][k]]
        dt_gust = [H["wind_gusts_10m"][i] for i in idx] or [D["wind_gusts_10m_max"][k]]
        core = [i for i in idx if 11 <= hour_of(t[i]) <= 16] or idx
        hdir = H.get("wind_direction_10m")
        if hdir and core:
            dom = wind_from_avg([hdir[i] for i in core], [max(H["wind_speed_10m"][i], 0.3) for i in core])
        else:
            dom = D["wind_direction_10m_dominant"][k]
        precip = D["precipitation_sum"][k]
        wc = D["weather_code"][k]; sun = D["sunshine_duration"][k]
        emoji, label, _ = day_status(precip, max(dt_wind), max(dt_gust), dom, aspect)
        score = day_score(precip, max(dt_wind), max(dt_gust), dom, aspect, sun)
        rows.append(dict(date=dcode, emoji=emoji, label=label, score=score,
                         tmax=max(dt_temp), wmax=max(dt_wind), gmax=max(dt_gust),
                         dom=dom, precip=precip, wc=wc))
    return rows
```

Then replace the head of `report_overview` (the lines from `D = data["daily"]; H = data["hourly"]` down to and including the `for k, dcode ...` loop that builds `rows`, i.e. old lines 286-308) with:

```python
def report_overview(data, site, rng, out):
    aspect = site["aspect_deg"]; elev = site["elevation_m"]
    rows = overview_rows(data, site)
    best = max(rows, key=lambda r: r["score"])
```

Leave everything from `names = {"3d": ...}` onward unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_engine_scan.py -v`
Expected: PASS (both assertions).

- [ ] **Step 5: Run the full suite to confirm no regression in the card/chart path**

Run: `.venv/bin/pytest -q`
Expected: all existing tests still PASS (report_overview unchanged in behavior).

- [ ] **Step 6: Commit**

```bash
git add engine.py tests/test_engine_scan.py
git commit -m "Extract engine.overview_rows shared by report_overview and scan

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Cache overview rows in the forecast layer

**Files:**
- Modify: `forecast.py` — `_fetch_build` (lines 160-184), `_ensure` (187-195), `get_forecast` (198-202), `get_analysis` (224)
- Modify: `tests/test_dialogs.py` — the one hand-built `_fcache` tuple at ~line 216

**Interfaces:**
- Consumes: `engine.overview_rows` (Task 1).
- Produces: `_fetch_build(...) -> (card, pngs, facts, fallback, rows)` and `_ensure(...) -> (card, pngs, facts, fallback, rows)`. `_fcache[key] = (expires, card, pngs, facts, fallback, rows)`. `rows` is `[]` for `1d`, else `engine.overview_rows(data, site)`.

- [ ] **Step 1: Update `_fetch_build` to build and return `rows`**

In `forecast.py`, inside `_fetch_build`, replace the `try:` block body (lines 175-183) with:

```python
        if rng == "1d":
            fallback, png_paths, card = engine.report_1day(data, site, out)
            facts = engine.facts_1day(data, site)
            rows = []
        else:
            fallback, png_paths, card = engine.report_overview(data, site, rng, out)
            facts = engine.facts_overview(data, site, rng)
            rows = engine.overview_rows(data, site)
        pngs = [pathlib.Path(p).read_bytes() for p in png_paths]
```

and change the return line to:

```python
    return card, pngs, facts, fallback, rows
```

- [ ] **Step 2: Update `_ensure` to cache and return the 6-tuple**

Replace `_ensure` body (lines 189-195) with:

```python
    now = time.monotonic()
    _purge(now)
    if key in _fcache:
        return _fcache[key][1:]
    card, pngs, facts, fallback, rows = await _fetch_build(site, rng, date)
    _fcache[key] = (now + _TTL, card, pngs, facts, fallback, rows)
    return card, pngs, facts, fallback, rows
```

- [ ] **Step 3: Update the two `_ensure` unpack sites**

In `get_forecast` (line 201):

```python
    card, pngs, _facts, _fallback, _rows = await _ensure(site, rng, date, key)
```

In `get_analysis` (line 224):

```python
    card, _pngs, facts, fallback, _rows = await _ensure(site, rng, date, base_key)
```

- [ ] **Step 4: Fix the hand-built cache tuple in the existing test**

In `tests/test_dialogs.py`, `test_day_picker_uses_cached_site_local_dates` (~line 216), the manual `_fcache` write is a 5-tuple. Append a trailing `[]` for `rows`:

```python
    forecast._fcache[key] = (time.monotonic() + 999, "c", [],
                             {"days_daytime": [{"date": d} for d in dates]}, "f", [])
```

- [ ] **Step 5: Run the suite to verify the contract change is consistent**

Run: `.venv/bin/pytest -q`
Expected: all tests PASS. (If any test fails unpacking a 4-tuple, another `_fcache` writer or `_ensure` consumer was missed — grep `_fcache\[` and `_ensure(` and fix.)

- [ ] **Step 6: Commit**

```bash
git add forecast.py tests/test_dialogs.py
git commit -m "Cache overview rows in _fcache, shared with /week

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `forecast.scan_week` — flyable days across all sites

**Files:**
- Modify: `forecast.py` (add `FLYABLE_LABELS` + `scan_week`, e.g. after `known_sites`)
- Test: `tests/test_engine_scan.py` (extend)

**Interfaces:**
- Consumes: `_ensure` returning `(card, pngs, facts, fallback, rows)` (Task 2), `engine.load_sites()`.
- Produces: `async scan_week() -> {"sites": list[{"name": str, "aspect": float|None, "days": list[row]}], "empty": list[str], "failed": list[str]}`. `row` is an `engine.overview_rows` dict. `days` contains only rows whose `label` is in `FLYABLE_LABELS`. A site with no flyable day goes to `empty`; a fetch that raised goes to `failed`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_engine_scan.py`:

```python
import asyncio
import forecast


def test_scan_week_filters_flyable_and_reports_empty(monkeypatch):
    # Two saved sites; site A has one flyable day, site B has none.
    monkeypatch.setattr(forecast.engine, "load_sites", lambda: [
        {"name": "A", "aspect_deg": 180.0}, {"name": "B", "aspect_deg": 180.0},
    ])
    rows_by_site = {
        "A": [
            {"date": "2026-07-25", "emoji": "✅", "label": "лётный", "score": 90,
             "wmax": 4, "gmax": 7, "dom": 180, "precip": 0.0, "wc": 0, "tmax": 20},
            {"date": "2026-07-26", "emoji": "⚠️", "label": "маргинальный", "score": 40,
             "wmax": 8, "gmax": 13, "dom": 200, "precip": 0.0, "wc": 3, "tmax": 19},
        ],
        "B": [
            {"date": "2026-07-25", "emoji": "❌", "label": "нелётный (ветер)", "score": 5,
             "wmax": 14, "gmax": 18, "dom": 180, "precip": 0.0, "wc": 0, "tmax": 18},
        ],
    }

    async def fake_ensure(site, rng, date, key):
        return "card", [], {}, "fb", rows_by_site[site["name"]]

    monkeypatch.setattr(forecast, "_ensure", fake_ensure)
    result = asyncio.run(forecast.scan_week())
    assert [s["name"] for s in result["sites"]] == ["A"]
    # маргинальный is excluded — only the "лётный" day survives
    assert [d["date"] for d in result["sites"][0]["days"]] == ["2026-07-25"]
    assert result["empty"] == ["B"]
    assert result["failed"] == []


def test_scan_week_records_failed_fetch(monkeypatch):
    monkeypatch.setattr(forecast.engine, "load_sites", lambda: [{"name": "X", "aspect_deg": None}])

    async def boom(site, rng, date, key):
        raise RuntimeError("open-meteo down")

    monkeypatch.setattr(forecast, "_ensure", boom)
    result = asyncio.run(forecast.scan_week())
    assert result["sites"] == [] and result["empty"] == [] and result["failed"] == ["X"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_engine_scan.py -k scan_week -v`
Expected: FAIL — `AttributeError: module 'forecast' has no attribute 'scan_week'`

- [ ] **Step 3: Implement `scan_week`**

In `forecast.py`, after `known_sites` (line 44), add:

```python
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
        _c, _p, _f, _fb, rows = await _ensure(site, "week", None, key)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_engine_scan.py -k scan_week -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add forecast.py tests/test_engine_scan.py
git commit -m "Add forecast.scan_week: flyable days across all sites

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `/scan` command + renderer in the bot

**Files:**
- Modify: `bot.py` (add `_scan_message` + `cmd_scan`; extend `BOT_COMMANDS` and `HELP`)
- Test: `tests/test_dialogs.py` (add a scan section)

**Interfaces:**
- Consumes: `forecast.scan_week()` (Task 3); existing `_btn`, `_WD`, `_chunks`, `engine.card`, `engine.WMO`, `engine.RAIN_DAY`, and the existing `pd|<site>|<date>` callback handled by `cb_pick_day`.
- Produces: message handler on `Command("scan")` with `flags={"forecast": True}`; helper `_scan_message(result) -> (text: str, kb: InlineKeyboardMarkup | None)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dialogs.py` (a new section near the forecast-command tests):

```python
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
    assert fc_calls == [("Гудаури", "1d", TODAY)]


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_dialogs.py -k scan -v`
Expected: FAIL — no `/scan` handler yet (`test_scan_no_sites_hints_add` hits the catch-all; button/list tests find no keyboard).

- [ ] **Step 3: Add the renderer and handler**

In `bot.py`, add `_scan_message` just above the forecast shortcut handlers (e.g. after `_day_picker_kb`, ~line 181):

```python
async def _noop():  # placeholder anchor — remove if present; do not use
    pass
```

Actually add this function (not the placeholder above — that line is illustrative only):

```python
def _scan_message(result: dict) -> tuple[str, InlineKeyboardMarkup | None]:
    """Render scan_week() output → (text, keyboard). One pd|-button per (site, day)."""
    if not result["sites"]:
        lines = ["🔎 На этой неделе лётных окон нет по всем стартам."]
        if result["failed"]:
            lines.append(f"⚠️ Не удалось получить: {', '.join(result['failed'])}.")
        return "\n".join(lines), None
    lines = ["🔎 Лётные дни на неделю — по стартам", ""]
    rows: list[list[InlineKeyboardButton]] = []
    for s in result["sites"]:
        head = f"🪂 {s['name']}" + (f" ({engine.card(s['aspect'])})" if s["aspect"] is not None else "")
        lines.append(head)
        for r in s["days"]:
            d = dt.date.fromisoformat(r["date"])
            day = f"{_WD[d.weekday()]} {d.day:02d}.{d.month:02d}"
            lines.append(f"  {r['emoji']} {day} · до {r['wmax']:.0f}, порыв {r['gmax']:.0f} м/с · "
                         f"{engine.card(r['dom'])} · {engine.WMO.get(r['wc'], '')}"
                         + (f" {r['precip']:.1f}мм" if r["precip"] > engine.RAIN_DAY else ""))
            btn = _btn(f"{r['emoji']} {day} · {s['name']}", f"pd|{s['name']}|{r['date']}")
            if btn is not None:
                rows.append([btn])
        lines.append("")
    if result["empty"]:
        lines.append("Без лётных дней: " + ", ".join(result["empty"]) + ".")
    if result["failed"]:
        lines.append(f"⚠️ Не удалось получить: {', '.join(result['failed'])}.")
    kb = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    return "\n".join(lines).rstrip(), kb


@dp.message(Command("scan"), flags={"forecast": True})
async def cmd_scan(message: Message):
    if not forecast.known_sites():
        await message.answer("Сохранённых стартов нет. Добавить: /add")
        return
    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            result = await forecast.scan_week()
    except Exception as e:  # noqa: BLE001 — surface any unexpected failure to the user
        log.exception("scan failed")
        await message.answer(f"⚠️ Ошибка: {e}")
        return
    text, kb = _scan_message(result)
    chunks = list(_chunks(text))
    for i, chunk in enumerate(chunks):  # keyboard rides the last chunk
        await message.answer(chunk, reply_markup=kb if i == len(chunks) - 1 else None)
```

(Do not add the `_noop` placeholder — it was only to mark the insertion point.)

- [ ] **Step 4: Register the command in the menu and help**

In `BOT_COMMANDS` (after the `twoweeks` entry, ~line 91) add:

```python
    BotCommand(command="scan", description="Лётные дни на неделю по всем стартам"),
```

In `HELP`, add a line after the `/twoweeks` line:

```python
    "/scan — лётные дни на неделю по всем стартам\n"
```

- [ ] **Step 5: Run the scan tests, then the full suite**

Run: `.venv/bin/pytest tests/test_dialogs.py -k scan -v`
Expected: PASS (all five scan tests).

Run: `.venv/bin/pytest -q`
Expected: entire suite PASS.

- [ ] **Step 6: Commit**

```bash
git add bot.py tests/test_dialogs.py
git commit -m "Add /scan command: flyable days across all sites with day buttons

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Docs — README command list

**Files:**
- Modify: `README.md` (command reference section)

- [ ] **Step 1: Find the command list**

Run: `grep -n "/twoweeks\|/week\|Команды\|Commands" README.md`
Expected: locates the command reference block.

- [ ] **Step 2: Add the `/scan` line**

Add, next to the other forecast commands, a line describing:
`/scan — лётные дни на неделю по всем сохранённым стартам; под сводкой — кнопки «старт + день» → подробный прогноз на 1 день.`

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "README: document /scan command

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Порог лётный+с оговорками → Task 3 `FLYABLE_LABELS` (+ Task 1 status, Task 3 test asserts маргинальный excluded). ✓
- Диапазон = неделя фиксированно → Task 3 hardcodes `"week"`. ✓
- Группировка по стартам → Task 4 `_scan_message` iterates `result["sites"]`. ✓
- Одно сообщение + общая клавиатура → Task 4 single text + single `InlineKeyboardMarkup` (chunked only if >4096, kb on last chunk). ✓
- Кнопка на пару старт+день, callback `pd|` → Task 4 buttons, Task 4 `test_scan_button_routes_to_pick_day`. ✓
- Кэш общий с /week → Task 2 caches rows under the same `(name,"week",None)` key. ✓
- Крайние случаи (нет стартов / нет лётных / упавшие) → Task 4 handler + `_scan_message`, tests cover all three. ✓
- Тесты в существующий harness → Tasks 1/3 (`test_engine_scan.py`), Task 4 (`test_dialogs.py`). ✓

**Placeholder scan:** No TBD/TODO. The only prose-only note is the `_noop` insertion marker, explicitly flagged as illustrative and "do not add." Every code step shows full code.

**Type consistency:** `overview_rows` row keys (`date/emoji/label/score/tmax/wmax/gmax/dom/precip/wc`) are defined in Task 1 and consumed identically in Tasks 3-4. `_ensure`/`_fetch_build` 6-tuple `(card,pngs,facts,fallback,rows)` consistent across Tasks 2-3. `scan_week` return shape (`sites/empty/failed`, site dict `name/aspect/days`) consistent between Task 3 producer and Task 4 consumer. `FLYABLE_LABELS` defined once in Task 3.

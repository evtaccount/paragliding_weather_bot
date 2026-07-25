#!/usr/bin/env python3
"""
Paragliding forecast engine (open-meteo).

Two subcommands, so the network step (curl) is separate from local compute
(always allowed even when the sandbox blocks the network):

  url    — print the open-meteo URL to fetch for a site + range
  report — read the fetched JSON and print a Telegram-ready text + write PNG charts

Wind is in m/s everywhere. Temperature and wind ranges in the text are computed
over DAYLIGHT hours only (between sunrise and sunset).

Usage:
  python3 engine.py url    --site Laliskuri --range 1d --date 2026-07-29
  python3 engine.py url    --site Laliskuri --range week
  python3 engine.py report --site Laliskuri --range 1d --date 2026-07-29 \
                           --json forecast.json --out /tmp/pgfc
"""
import argparse, json, os, shutil, sys, math, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
# The packaged default (baked into the image). SITES may be redirected via
# SITES_FILE to a writable location (a mounted data volume) so /add and
# /removesite can persist as a non-root container user.
DEFAULT_SITES = os.path.join(HERE, "sites.json")
SITES = os.environ.get("SITES_FILE") or DEFAULT_SITES
sys.path.insert(0, HERE)  # so `from charts import ...` works from any cwd

# Meteo model — a global setting persisted next to sites.json (writable volume in
# the container). Requesting a variable a model lacks is not an error: open-meteo
# returns it as a null series (handled by the degradation in report_1day).
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


def ensure_sites_file():
    """Seed SITES from the packaged default on first run (e.g. an empty volume)."""
    if os.path.abspath(SITES) == os.path.abspath(DEFAULT_SITES):
        return
    if not os.path.exists(SITES):
        os.makedirs(os.path.dirname(SITES) or ".", exist_ok=True)
        shutil.copy(DEFAULT_SITES, SITES)

# ---- paragliding thresholds (m/s) — tune here ----
WIND_GOOD   = 5.0    # <= calm/comfortable
WIND_MAX    = 7.0    # > this = no-go on surface wind
GUST_MAX    = 8.0    # > this gust = alarm
GUST_SPREAD = 5.0    # gust-wind spread that flags rowdy air
GUST_STRONG = 11.0   # > this gust = clearly unflyable
RAIN_DAY    = 0.2    # mm/day -> wet day
RAIN_HR     = 0.1    # mm/h   -> wet hour
DIR_IN      = 80     # <= deg from launch aspect = into the slope (good)
DIR_TAIL    = 110    # >= deg = tail/cross-tail (bad)

RANGE_DAYS = {"1d": 1, "3d": 3, "week": 7, "2weeks": 14}
WMO = {0:"ясно",1:"в осн. ясно",2:"перем. обл.",3:"пасмурно",45:"туман",48:"туман",
       51:"морось",53:"морось",55:"морось",61:"дождь",63:"дождь",65:"ливень",
       71:"снег",73:"снег",75:"снег",80:"ливни",81:"ливни",82:"ливни",
       95:"гроза",96:"гроза",99:"гроза"}
CARD = ["С","ССВ","СВ","ВСВ","В","ВЮВ","ЮВ","ЮЮВ","Ю","ЮЮЗ","ЮЗ","ЗЮЗ","З","ЗСЗ","СЗ","ССЗ"]
DOW = ["ПН","ВТ","СР","ЧТ","ПТ","СБ","ВС"]
MON = ["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"]

def card(deg): return CARD[round((deg % 360) / 22.5) % 16]
def ang(a, b):
    d = abs((a - b) % 360)
    return min(d, 360 - d)
def wind_from_avg(dirs, speeds):
    """speed-weighted mean of FROM-directions (degrees); handles wrap-around."""
    su = sum(s * math.sin(math.radians(d)) for d, s in zip(dirs, speeds))
    sv = sum(s * math.cos(math.radians(d)) for d, s in zip(dirs, speeds))
    if su == 0 and sv == 0:
        return dirs[len(dirs) // 2]
    return math.degrees(math.atan2(su, sv)) % 360

# ---------------------------------------------------------------- sites
def load_sites():
    with open(SITES, encoding="utf-8") as f:
        return json.load(f)["sites"]

def find_site(name):
    key = name.strip().lower()
    for s in load_sites():
        if s["name"].lower() == key or key in [a.lower() for a in s.get("aliases", [])]:
            return s
    raise SystemExit(f"Сайт не найден: {name}. Есть: " + ", ".join(s["name"] for s in load_sites()))

_COMPASS = {"С": 0, "N": 0, "СВ": 45, "NE": 45, "В": 90, "E": 90, "ЮВ": 135, "SE": 135,
            "Ю": 180, "S": 180, "ЮЗ": 225, "SW": 225, "З": 270, "W": 270, "СЗ": 315, "NW": 315}

def parse_aspect(s: str) -> float:
    """Compass letters (С/СВ/…/N/NE/…) or degrees (0–359) → aspect degrees."""
    key = s.strip().upper()
    if key in _COMPASS:
        return _COMPASS[key]
    try:
        d = float(key)
    except ValueError:
        raise ValueError("экспозиция: С/СВ/В/ЮВ/Ю/ЮЗ/З/СЗ или градусы 0–359")
    if 0 <= d < 360:
        return d
    raise ValueError("градусы экспозиции: 0–359")

def _load_raw():
    with open(SITES, encoding="utf-8") as f:
        return json.load(f)

def add_site(site: dict):
    """Append a site to sites.json (raises if the name collides with a name OR an
    alias — find_site matches aliases too, an alias-shadowed site would be unreachable)."""
    data = _load_raw()
    key = site["name"].lower()
    for s in data["sites"]:
        if key == s["name"].lower():
            raise ValueError(f"старт «{site['name']}» уже есть")
        if key in [a.lower() for a in s.get("aliases", [])]:
            raise ValueError(f"имя «{site['name']}» уже занято как псевдоним старта «{s['name']}»")
    data["sites"].append(site)
    with open(SITES, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def remove_site(name: str):
    """Delete a site by name (raises if not found)."""
    data = _load_raw()
    kept = [s for s in data["sites"] if s["name"].lower() != name.strip().lower()]
    if len(kept) == len(data["sites"]):
        raise ValueError(f"старт «{name}» не найден")
    data["sites"] = kept
    with open(SITES, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------- URL
H_1D = ("temperature_2m,wind_speed_10m,wind_gusts_10m,wind_direction_10m,cloud_cover_low,"
        "cloud_cover_mid,precipitation,cape,dew_point_2m,boundary_layer_height,freezing_level_height,"
        "wind_speed_925hPa,wind_direction_925hPa,geopotential_height_925hPa,"
        "wind_speed_850hPa,wind_direction_850hPa,geopotential_height_850hPa,"
        "wind_speed_700hPa,wind_direction_700hPa,geopotential_height_700hPa,"
        "wind_speed_600hPa,wind_direction_600hPa,geopotential_height_600hPa,"
        "wind_speed_500hPa,wind_direction_500hPa,geopotential_height_500hPa")
D_1D = "sunrise,sunset,weather_code,temperature_2m_max,temperature_2m_min,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant,precipitation_sum,sunshine_duration"
H_OV = "temperature_2m,wind_speed_10m,wind_gusts_10m,wind_direction_10m"
D_OV = ("sunrise,sunset,weather_code,temperature_2m_max,temperature_2m_min,wind_speed_10m_max,"
        "wind_gusts_10m_max,wind_direction_10m_dominant,precipitation_sum,precipitation_probability_max,"
        "sunshine_duration,shortwave_radiation_sum")

def build_url(site, rng, date=None):
    base = (f"https://api.open-meteo.com/v1/forecast?latitude={site['lat']}&longitude={site['lon']}"
            f"&wind_speed_unit=ms&timezone=auto&models={model_id(get_model_key())}")
    if rng == "1d":
        if not date:
            raise SystemExit("для --range 1d нужен --date YYYY-MM-DD")
        return f"{base}&hourly={H_1D}&daily={D_1D}&start_date={date}&end_date={date}"
    n = RANGE_DAYS[rng]
    return f"{base}&hourly={H_OV}&daily={D_OV}&forecast_days={n}"

# ---------------------------------------------------------------- helpers
def hour_of(iso): return int(iso[11:13])
def ymd(iso): return iso[:10]
def fmt_date(iso):
    d = dt.date.fromisoformat(iso[:10])
    return f"{DOW[d.weekday()]} {d.day} {MON[d.month-1]}"

def daylight_idx(times, sunrise, sunset):
    """indices of hourly `times` between sunrise and sunset (inclusive of the hour)."""
    lo, hi = hour_of(sunrise), hour_of(sunset)
    return [i for i, t in enumerate(times) if lo <= hour_of(t) <= hi]

# ---------------------------------------------------------------- sun geometry
# The launch aspect is a fixed number, but the sun moves: an eastern slope heats in the
# morning, a southern one at midday, a western one in the evening. Without these numbers
# the LLM treats every daylight hour as equally thermic and flags "risks" at sunrise.
# All of it is local compute from lat + date + the sunrise/sunset already in the response.
SLOPE_DEG      = 25.0   # assumed launch steepness when the site doesn't specify slope_deg
SUN_MIN_ELEV   = 12.0   # sun lower than this: heating too weak for workable thermals
SLOPE_LIT_MIN  = 0.15   # cos(incidence) below this: the slope face is effectively in shade
THERMAL_LAG_H  = 2      # thermals need ~2h of sun after sunrise to break off
THERMAL_LEAD_H = 1      # the last hour before sunset is already collapsing


def _declination(date_iso):
    """Solar declination (deg) for a date — Cooper's day-of-year approximation."""
    n = dt.date.fromisoformat(date_iso[:10]).timetuple().tm_yday
    return 23.45 * math.sin(math.radians(360.0 * (284 + n) / 365.0))


def _clock_h(iso):
    """ISO local time → hours as a float (05:47 → 5.783)."""
    return int(iso[11:13]) + int(iso[14:16]) / 60.0


def sun_position(lat, dec, hour_angle):
    """(elevation, azimuth) in degrees for a solar hour angle (0 = solar noon,
    negative = morning). Azimuth is measured from north, clockwise (90 = east)."""
    la, d, h = map(math.radians, (lat, dec, hour_angle))
    sin_el = math.sin(la) * math.sin(d) + math.cos(la) * math.cos(d) * math.cos(h)
    el = math.asin(max(-1.0, min(1.0, sin_el)))
    sin_az = -math.cos(d) * math.sin(h)
    cos_az = (math.sin(d) - math.sin(la) * math.sin(el)) / (math.cos(la) * math.cos(el) or 1e-9)
    return math.degrees(el), math.degrees(math.atan2(sin_az, cos_az)) % 360


def slope_sun_index(sun_elev, sun_az, aspect_deg, slope_deg=SLOPE_DEG):
    """How directly the sun hits the launch slope: cos of the incidence angle, 0–1.
    1 = perpendicular to the face (maximum heating), 0 = the face gets no direct sun.
    None when the aspect is unknown (ad-hoc point)."""
    if aspect_deg is None:
        return None
    if sun_elev <= 0:
        return 0.0
    el, sl = math.radians(sun_elev), math.radians(slope_deg)
    c = (math.cos(sl) * math.sin(el)
         + math.sin(sl) * math.cos(el) * math.cos(math.radians(sun_az - aspect_deg)))
    return round(max(0.0, c), 2)


def sun_hours(date_iso, lat, sunrise, sunset, hours, aspect_deg, slope_deg=SLOPE_DEG):
    """Per-hour sun geometry over `hours` (local clock hours), plus the derived
    thermal window. Solar noon is the sunrise/sunset midpoint, so no timezone math
    is needed — the API already returns everything in the site's local time."""
    dec = _declination(date_iso)
    noon = (_clock_h(sunrise) + _clock_h(sunset)) / 2.0
    rows = []
    for h in hours:
        el, az = sun_position(lat, dec, 15.0 * (h + 0.5 - noon))  # mid-hour sample
        rows.append({"hour": h, "sun_elev_deg": round(el), "sun_az_deg": round(az),
                     "slope_sun_index": slope_sun_index(el, az, aspect_deg, slope_deg)})
    lit = [r for r in rows if r["sun_elev_deg"] >= SUN_MIN_ELEV
           and (r["slope_sun_index"] is None or r["slope_sun_index"] >= SLOPE_LIT_MIN)]
    window = None
    if lit:
        lo = max(int(_clock_h(sunrise)) + THERMAL_LAG_H, lit[0]["hour"])
        hi = min(int(_clock_h(sunset)) - THERMAL_LEAD_H, lit[-1]["hour"])
        if lo <= hi:
            best = max(lit, key=lambda r: (r["slope_sun_index"] if r["slope_sun_index"] is not None
                                           else r["sun_elev_deg"]))
            window = {"start_hour": lo, "end_hour": hi, "peak_hour": best["hour"],
                      "solar_noon": f"{int(noon):02d}:{round((noon % 1) * 60):02d}"}
    return rows, window


def sun_summary(date_iso, site, sunrise, sunset):
    """Thermal window for one day at a site — used where there is no hourly series
    (the multi-day overview). Same geometry, evaluated over whole daylight hours."""
    hours = list(range(int(_clock_h(sunrise)), int(_clock_h(sunset)) + 1))
    _, window = sun_hours(date_iso, site["lat"], sunrise, sunset, hours,
                          site.get("aspect_deg"), site.get("slope_deg", SLOPE_DEG))
    return window


def rng_str(vals, unit="", dec=0):
    lo, hi = min(vals), max(vals)
    if dec:
        return f"{lo:.1f}–{hi:.1f}{unit}" if lo != hi else f"{lo:.1f}{unit}"
    return f"{round(lo)}–{round(hi)}{unit}" if round(lo) != round(hi) else f"{round(lo)}{unit}"

# ---------------------------------------------------------------- assessment
def dir_verdict(deg, aspect_deg):
    if aspect_deg is None:  # ad-hoc point — slope orientation unknown
        return "экспозиция неизвестна", "unknown"
    a = ang(deg, aspect_deg)
    if a <= DIR_IN:  return "в лоб склону ✅", "in"
    if a >= DIR_TAIL: return "в спину ❌", "tail"
    return "боковой ⚠️", "cross"

def day_status(precip, wind_max, gust_max, dom_dir, aspect_deg):
    """returns (emoji, label, score)."""
    _, dc = dir_verdict(dom_dir, aspect_deg)
    if precip > RAIN_DAY:
        return "❌", "нелётный (дождь)", 0
    if gust_max > GUST_STRONG or wind_max > WIND_MAX + 2:
        return "❌", "нелётный (ветер)", 5
    bad = 0
    if wind_max > WIND_MAX: bad += 2
    if gust_max > GUST_MAX + 2: bad += 2
    if dc == "tail": bad += 2
    if dc == "cross": bad += 1
    if bad >= 3:
        return "⚠️", "маргинальный", 40
    if bad >= 1:
        return "⚠️", "с оговорками", 60
    return "✅", "лётный", 90

def day_score(precip, wind_max, gust_max, dom_dir, aspect_deg, sunshine_s):
    s = 100.0
    if precip > RAIN_DAY: s -= 60
    s -= precip * 3
    s -= max(0, wind_max - 3) * 7
    s -= max(0, gust_max - 5) * 5
    if aspect_deg is not None:
        a = ang(dom_dir, aspect_deg)
        if a >= DIR_TAIL: s -= 30
        elif a > DIR_IN: s -= 12
    s += min(sunshine_s / 3600.0, 12) * 1.5  # reward sun (thermals)
    return s

def _series_available(H, key):
    """True if the hourly variable actually came back (present and not all-null).
    ECMWF, for instance, returns boundary_layer_height / freezing_level_height as null."""
    v = H.get(key)
    return bool(v) and any(x is not None for x in v)


# ---------------------------------------------------------------- report: 1 day
def report_1day(data, site, out):
    H, D = data["hourly"], data["daily"]
    t = H["time"]
    sr, ss = D["sunrise"][0], D["sunset"][0]
    day = daylight_idx(t, sr, ss)
    elev = site["elevation_m"]; aspect = site["aspect_deg"]
    temp = H["temperature_2m"]; wind = H["wind_speed_10m"]; gust = H["wind_gusts_10m"]
    wdir = H["wind_direction_10m"]; precip = H["precipitation"]; cape = H["cape"]
    clow = H["cloud_cover_low"]; dew = H["dew_point_2m"]; blh = H["boundary_layer_height"]
    has_blh = _series_available(H, "boundary_layer_height")

    dt_temp = [temp[i] for i in day]
    dt_wind = [wind[i] for i in day]
    dt_gust = [gust[i] for i in day]
    # flyable hours: within daylight, wind/gust/precip/direction ok
    fly = []
    for i in day:
        ok = (wind[i] <= WIND_MAX and gust[i] <= GUST_MAX and precip[i] < RAIN_HR
              and (aspect is None or ang(wdir[i], aspect) < DIR_TAIL))
        fly.append((hour_of(t[i]), ok))
    fly_hours = [h for h, ok in fly if ok]
    window = f"{min(fly_hours):02d}:00–{max(fly_hours):02d}:00" if fly_hours else "нет"
    # thermal peak = hours around max temp within daylight
    tmax_i = max(day, key=lambda i: temp[i])
    peak_lo = max(hour_of(sr), hour_of(t[tmax_i]) - 1)
    peak_hi = hour_of(t[tmax_i]) + 1
    # ceiling
    midday = min(day, key=lambda i: abs(hour_of(t[i]) - hour_of(t[tmax_i])))
    lcl_agl = 122 * (temp[midday] - dew[midday])
    if has_blh:
        top_agl = round(max(blh[i] for i in day))
        top_msl = elev + top_agl
        blue = (clow[midday] < 15 and lcl_agl > blh[midday])
    else:  # model without a boundary-layer series (e.g. ECMWF) — no ceiling
        top_agl = top_msl = None
        blue = False
    # flying-window direction (11–16, speed-weighted) — NOT the 24h dominant,
    # which light morning/evening drainage skews away from the thermal wind.
    core = [i for i in day if 11 <= hour_of(t[i]) <= 16] or [tmax_i]
    fly_dir = wind_from_avg([wdir[i] for i in core], [max(wind[i], 0.3) for i in core])
    dv, dc = dir_verdict(fly_dir, aspect)
    precip_sum = D["precipitation_sum"][0]
    st_emoji, st_label, _ = day_status(precip_sum, max(dt_wind), max(dt_gust), fly_dir, aspect)

    # ---- text: factual card (always shown) + tail (window/caveats) ----
    card_lines = [
        f"🪂 {site['name']}{(' (' + card(aspect) + ')') if aspect is not None else ''} — прогноз на {fmt_date(t[0])}",
        f"📍 {site['lat']:.3f}, {site['lon']:.3f} · {elev} м · {data.get('timezone','')} · {model_label(get_model_key())}",
        "",
        f"Вердикт: {st_emoji} {st_label}",
        "",
        f"🌡️ Днём ({hour_of(sr):02d}–{hour_of(ss):02d}): {rng_str(dt_temp,'°')}",
        f"💨 Ветер (днём): {rng_str(dt_wind,' м/с',1)}, порывы до {max(dt_gust):.0f}",
        f"🧭 Направление (в окно): {card(fly_dir)} ~{round(fly_dir)}° → {dv}",
        f"🌧️ Осадки: {'нет' if precip_sum < RAIN_DAY else f'{precip_sum:.1f} мм'}",
        f"🔆 Термичка: {'рабочая' if max(cape[i] for i in day) > 20 or (top_agl or 0) > 500 else 'слабая'}, пик {peak_lo:02d}–{peak_hi:02d}",
        (f"🧗 Потолок: ~{top_agl} м над стартом (~{top_msl} MSL){' · голубой' if blue else ''}"
         if has_blh else "🧗 Потолок: н/д (модель не даёт)"),
    ]
    card_text = "\n".join(card_lines)

    tail = [f"⏱️ Лётное окно: {window}" + (f" (пик {peak_lo:02d}–{peak_hi:02d})" if fly_hours else "")]
    cav = []
    if blue: cav.append("голубая термичка (без облаков-маркеров)")
    if has_blh and top_agl < 900: cav.append("низкий потолок — XC слабый")
    if dc == "tail": cav.append("ветер в спину в рабочее окно — опасно, сверь экспозицию")
    elif dc == "cross": cav.append("боковой ветер к склону — сверь экспозицию")
    cav.append(f"высота старта по гриду ({elev} м); прогноз далеко вперёд — пересними за 1–2 суток")
    if cav:
        tail.append("")
        tail.append("⚠️ " + "; ".join(cav) + ".")
    text = card_text + "\n\n" + "\n".join(tail)

    # ---- charts ----
    pngs = []
    from charts import meteogram_png, ceiling_png, profile_png
    pngs.append(meteogram_png(data, site, out))
    if has_blh:  # ceiling chart needs the boundary-layer series
        pngs.append(ceiling_png(data, site, out))
    pngs.append(profile_png(data, site, out))
    return text, pngs, card_text

# ---------------------------------------------------------------- wind grid (altitude × hour)
# Levels available in the 1d response, low → high. dir key present for all six after
# H_1D was extended. Height is a fixed elevation for 10m, else a geopotential-height key.
_GRID_LEVELS = [
    ("10 м", "elev+10", "wind_speed_10m", "wind_direction_10m"),
    ("925", "geopotential_height_925hPa", "wind_speed_925hPa", "wind_direction_925hPa"),
    ("850", "geopotential_height_850hPa", "wind_speed_850hPa", "wind_direction_850hPa"),
    ("700", "geopotential_height_700hPa", "wind_speed_700hPa", "wind_direction_700hPa"),
    ("600", "geopotential_height_600hPa", "wind_speed_600hPa", "wind_direction_600hPa"),
    ("500", "geopotential_height_500hPa", "wind_speed_500hPa", "wind_direction_500hPa"),
]


def wind_grid(data, site):
    """Altitude × hour wind table from the 1d open-meteo response.

    Rows are pressure/height levels, columns are daylight hours (hourly). Only levels
    at/above launch are kept, plus the single nearest level below launch (context);
    10 m is the launch surface and always kept. Heights come from the midday reference
    hour (levels' geopotential heights drift hour-to-hour). Pure local compute."""
    H, D = data["hourly"], data["daily"]
    t = H["time"]
    sr, ss = D["sunrise"][0], D["sunset"][0]
    day = daylight_idx(t, sr, ss)
    launch = site["elevation_m"]
    ref = day[len(day) // 2]  # midday reference for level altitudes

    built = []
    for label, hkey, spd_key, dir_key in _GRID_LEVELS:
        alt = launch + 10 if hkey == "elev+10" else round(H[hkey][ref])
        hourly = [{"hour": hour_of(t[i]), "wind_ms": round(H[spd_key][i], 1),
                   "dir_deg": round(H[dir_key][i])} for i in day]
        built.append({"label": label, "alt_m_msl": alt, "is_launch": hkey == "elev+10",
                      "hourly": hourly})

    # keep levels at/above launch + the single nearest below-launch level for context
    above = [lv for lv in built if lv["alt_m_msl"] >= launch]
    below = [lv for lv in built if lv["alt_m_msl"] < launch]
    context = [max(below, key=lambda lv: lv["alt_m_msl"])] if below else []
    levels = sorted(above + context, key=lambda lv: lv["alt_m_msl"])

    return {"date": t[0][:10], "timezone": data.get("timezone"), "launch_m": launch,
            "hours": [hour_of(t[i]) for i in day], "levels": levels}

# ---------------------------------------------------------------- report: overview
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


def report_overview(data, site, rng, out):
    aspect = site["aspect_deg"]; elev = site["elevation_m"]
    rows = overview_rows(data, site)
    best = max(rows, key=lambda r: r["score"])
    names = {"3d": "3 дня", "week": "неделю", "2weeks": "2 недели"}
    card_lines = [f"🪂 {site['name']}{(' (' + card(aspect) + ')') if aspect is not None else ''} — обзор на {names[rng]}",
                  f"📍 {site['lat']:.3f}, {site['lon']:.3f} · {elev} м · {data.get('timezone','')}",
                  "",
                  f"🏆 Лучший день: {best['emoji']} {fmt_date(best['date'])} — {WMO.get(best['wc'],'')}, "
                  f"ветер до {best['wmax']:.0f}, порыв {best['gmax']:.0f} м/с",
                  "",
                  "По дням (светлое время):"]
    for r in rows:
        card_lines.append(f"{r['emoji']} {fmt_date(r['date'])} · {r['tmax']:.0f}° · "
                          f"ветер до {r['wmax']:.0f}, порыв {r['gmax']:.0f} м/с · "
                          f"{card(r['dom'])} · {WMO.get(r['wc'],'')}"
                          + (f" {r['precip']:.1f}мм" if r["precip"] > RAIN_DAY else ""))
    card_text = "\n".join(card_lines)
    note = "💨 ветер в м/с; T и ветер — за светлое время. Пороги: ≤5 ок · 5–7 маргинал · >7 нет."
    from charts import overview_png
    png = overview_png(rows, site, rng, out)
    return card_text + "\n\n" + note, [png], card_text

# ---------------------------------------------------------------- facts (for LLM analysis)
# These extract the REAL numbers from the open-meteo response into a compact,
# unit-labelled dict. The LLM interprets these facts; it never invents them.
def facts_1day(data, site):
    H, D = data["hourly"], data["daily"]
    t = H["time"]; sr, ss = D["sunrise"][0], D["sunset"][0]
    day = daylight_idx(t, sr, ss)
    elev = site["elevation_m"]; aspect = site["aspect_deg"]
    temp = H["temperature_2m"]; wind = H["wind_speed_10m"]; gust = H["wind_gusts_10m"]
    wdir = H["wind_direction_10m"]; precip = H["precipitation"]; cape = H["cape"]
    clow = H["cloud_cover_low"]; dew = H["dew_point_2m"]; blh = H["boundary_layer_height"]
    has_blh = _series_available(H, "boundary_layer_height")
    has_frz = _series_available(H, "freezing_level_height")
    tmax_i = max(day, key=lambda i: temp[i])  # peak-heating hour
    lcl_agl = round(122 * (temp[tmax_i] - dew[tmax_i]))
    if has_blh:
        top_agl = round(max(blh[i] for i in day))
        blue = clow[tmax_i] < 15 and (elev + lcl_agl) > (elev + top_agl)
    else:  # model without a boundary-layer series (e.g. ECMWF)
        top_agl = None
        blue = False

    levels = [("10m", elev + 10, "wind_speed_10m", "wind_direction_10m"),
              ("925hPa", "geopotential_height_925hPa", "wind_speed_925hPa", "wind_direction_925hPa"),
              ("850hPa", "geopotential_height_850hPa", "wind_speed_850hPa", "wind_direction_850hPa"),
              ("700hPa", "geopotential_height_700hPa", "wind_speed_700hPa", "wind_direction_700hPa"),
              ("600hPa", "geopotential_height_600hPa", "wind_speed_600hPa", "wind_direction_600hPa"),
              ("500hPa", "geopotential_height_500hPa", "wind_speed_500hPa", "wind_direction_500hPa")]
    profile = []
    for name, h, spd, dr in levels:
        alt = h if isinstance(h, (int, float)) else round(H[h][tmax_i])
        row = {"level": name, "alt_m_msl": alt, "wind_ms": round(H[spd][tmax_i], 1)}
        if dr:
            row["dir_deg"] = round(H[dr][tmax_i])
        profile.append(row)

    sun_rows, thermal_window = sun_hours(t[0], site["lat"], sr, ss, [hour_of(t[i]) for i in day],
                                         aspect, site.get("slope_deg", SLOPE_DEG))
    sun_by_hour = {r["hour"]: r for r in sun_rows}

    return {
        "site": {"name": site["name"], "aspect": card(aspect) if aspect is not None else None, "aspect_deg": aspect,
                 "elevation_m": elev, "timezone": data.get("timezone"), "model": model_label(get_model_key())},
        "date": t[0][:10],
        "daylight_hours": f"{hour_of(sr):02d}-{hour_of(ss):02d}",
        "thermal_window": thermal_window,
        "precip_sum_mm": round(D["precipitation_sum"][0], 1),
        "cape_max": round(max(cape[i] for i in day)),
        "freezing_level_m": round(H["freezing_level_height"][tmax_i]) if has_frz else None,
        "thermal_ceiling_m_agl": top_agl,
        "thermal_ceiling_m_msl": (elev + top_agl) if top_agl is not None else None,
        "lcl_m_agl": lcl_agl,
        "blue_thermals": bool(blue),
        "hourly_daytime": [
            {"time": t[i][11:16], "temp_c": round(temp[i], 1), "wind_ms": round(wind[i], 1),
             "gust_ms": round(gust[i], 1), "dir_deg": round(wdir[i]),
             "cloud_low_pct": round(clow[i]), "precip_mm": round(precip[i], 2), "cape": round(cape[i]),
             "sun_elev_deg": sun_by_hour[hour_of(t[i])]["sun_elev_deg"],
             "sun_az_deg": sun_by_hour[hour_of(t[i])]["sun_az_deg"],
             "slope_sun_index": sun_by_hour[hour_of(t[i])]["slope_sun_index"]}
            for i in day],
        "wind_profile_peak_hour": profile,
    }


def facts_overview(data, site, rng):
    D = data["daily"]; H = data["hourly"]
    t = H["time"]; aspect = site["aspect_deg"]
    days = []
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
        days.append({
            "date": dcode, "weather": WMO.get(D["weather_code"][k], ""),
            "temp_max_c": round(max(dt_temp)), "temp_min_c": round(D["temperature_2m_min"][k]),
            "wind_max_ms": round(max(dt_wind), 1), "gust_max_ms": round(max(dt_gust), 1),
            "wind_dir_window": f"{card(dom)} ({round(dom)}°)",
            "precip_mm": round(D["precipitation_sum"][k], 1),
            "sunshine_h": round(D["sunshine_duration"][k] / 3600.0, 1),
            "thermal_window": sun_summary(dcode, site, sr, ss),
        })
    return {
        "site": {"name": site["name"], "aspect": card(aspect) if aspect is not None else None, "aspect_deg": aspect,
                 "elevation_m": site["elevation_m"], "timezone": data.get("timezone")},
        "range": rng,
        "days_daytime": days,
    }

def brief_1day(data, site):
    """Compact daytime summary of a single-day open-meteo response (surface only).
    Used for the 'previous day' context in the detailed analysis."""
    H, D = data["hourly"], data["daily"]
    t = H["time"]
    sr, ss = D["sunrise"][0], D["sunset"][0]
    day = daylight_idx(t, sr, ss)
    w = [H["wind_speed_10m"][i] for i in day]
    g = [H["wind_gusts_10m"][i] for i in day]
    tp = [H["temperature_2m"][i] for i in day]
    core = [i for i in day if 11 <= hour_of(t[i]) <= 16] or day
    dom = wind_from_avg([H["wind_direction_10m"][i] for i in core],
                        [max(H["wind_speed_10m"][i], 0.3) for i in core])
    return {
        "date": t[0][:10], "weather": WMO.get(D["weather_code"][0], ""),
        "temp_c": f"{round(min(tp))}–{round(max(tp))}",
        "wind_ms": f"{min(w):.1f}–{max(w):.1f}", "gust_max_ms": round(max(g), 1),
        "wind_dir_window": f"{card(dom)} ({round(dom)}°)",
        "precip_mm": round(D["precipitation_sum"][0], 1),
    }

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("url", "report"):
        p = sub.add_parser(c)
        p.add_argument("--site", required=True)
        p.add_argument("--range", required=True, choices=list(RANGE_DAYS))
        p.add_argument("--date")
        if c == "report":
            p.add_argument("--json", required=True)
            p.add_argument("--out", required=True)
    a = ap.parse_args()
    site = find_site(a.site)
    if a.cmd == "url":
        print(build_url(site, a.range, a.date)); return
    with open(a.json, encoding="utf-8") as f:
        data = json.load(f)
    os.makedirs(a.out, exist_ok=True)
    if a.range == "1d":
        text, pngs, _ = report_1day(data, site, a.out)
    else:
        text, pngs, _ = report_overview(data, site, a.range, a.out)
    print("=" * 8 + " TELEGRAM " + "=" * 8)
    print(text)
    print("=" * 26)
    print("PNG:")
    for p in pngs:
        print(" ", p)

if __name__ == "__main__":
    main()

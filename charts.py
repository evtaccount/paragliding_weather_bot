#!/usr/bin/env python3
"""PNG charts for the paragliding forecast — light theme, wind in m/s, pure Pillow."""
import os
from PIL import Image, ImageDraw, ImageFont

SS = 2  # supersampling for anti-aliasing

# ---- validated light palette (surface #fcfcfb) ----
BG    = (252, 252, 251)
GRID  = (230, 228, 221)
INK   = (28, 28, 26)
MUTED = (106, 106, 99)
FAINT = (158, 158, 148)
TEMP  = (194, 94, 18)
WIND  = (47, 111, 224)
GUST  = (14, 140, 124)
GOOD  = (63, 143, 87)
WARN  = (194, 94, 18)
RAIN  = (194, 58, 82)
BEST  = (47, 143, 82)

def _font(sz, bold=False):
    cands = (["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"]
             if bold else
             ["/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc"])
    for p in cands:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, sz * SS)
            except Exception: pass
    return ImageFont.load_default()

def _canvas(w, h):
    img = Image.new("RGB", (w * SS, h * SS), BG)
    return img, ImageDraw.Draw(img, "RGBA")

def _save(img, out, name):
    w, h = img.size
    img = img.resize((w // SS, h // SS), Image.LANCZOS)
    path = os.path.join(out, name)
    img.save(path)
    return path

def S(v): return v * SS
def _hour(iso): return int(iso[11:13])
def _ang(a, b):
    d = abs((a - b) % 360); return min(d, 360 - d)
def _card(deg):
    return ["С","ССВ","СВ","ВСВ","В","ВЮВ","ЮВ","ЮЮВ","Ю","ЮЮЗ","ЮЗ","ЗЮЗ","З","ЗСЗ","СЗ","ССЗ"][round((deg%360)/22.5)%16]

def _daylight(times, sr, ss, pad=1):
    lo, hi = max(0, _hour(sr) - pad), min(23, _hour(ss) + pad)
    idx = [i for i, t in enumerate(times) if lo <= _hour(t) <= hi]
    return idx, lo, hi

# ---------------------------------------------------------------- meteogram
def meteogram_png(data, site, out):
    H, D = data["hourly"], data["daily"]
    t = H["time"]; sr, ss = D["sunrise"][0], D["sunset"][0]
    idx, h0, h1 = _daylight(t, sr, ss)
    hrs = [_hour(t[i]) for i in idx]
    temp = [H["temperature_2m"][i] for i in idx]
    wind = [H["wind_speed_10m"][i] for i in idx]
    gust = [H["wind_gusts_10m"][i] for i in idx]
    srh, ssh = _hour(sr), _hour(ss)
    W, Ht = 1040, 620
    img, d = _canvas(W, Ht)
    L, R = 66, 30
    x0, x1 = S(L), S(W - R)
    xf = lambda h: x0 + (x1 - x0) * (h - h0) / max(1, (h1 - h0))
    d.text((S(40), S(28)), f"{site['name']} — метеограмма {t[0][:10]}", font=_font(24, True), fill=INK, anchor="lm")
    d.text((S(40), S(56)), f"Светлое время {srh:02d}–{ssh:02d} · ветер в м/с · {data.get('timezone','')}",
           font=_font(13), fill=MUTED, anchor="lm")
    # flyable window band — same criteria as the engine (incl. direction into the slope)
    asp = site.get("aspect_deg", 180)
    fly = [h for h, i in zip(hrs, idx)
           if H["wind_speed_10m"][i] <= 7 and H["wind_gusts_10m"][i] <= 8
           and H["precipitation"][i] < 0.1 and _ang(H["wind_direction_10m"][i], asp) < 110]
    if fly:
        d.rectangle([xf(min(fly)), S(84), xf(max(fly)), S(Ht-34)], fill=GUST + (26,))
        d.text(((xf(min(fly))+xf(max(fly)))/2, S(96)), f"лётное окно {min(fly):02d}–{max(fly):02d}",
               font=_font(12, True), fill=GUST, anchor="mm")
    # panel A temp
    ay0, ay1 = S(112), S(320)
    tmn, tmx = min(temp) - 2, max(temp) + 2
    yT = lambda v: ay1 - (ay1 - ay0) * (v - tmn) / (tmx - tmn)
    step = 5
    lo = int(tmn // step * step)
    for tv in range(lo, int(tmx) + step, step):
        if tv < tmn or tv > tmx: continue
        yy = yT(tv); d.line([x0, yy, x1, yy], fill=GRID, width=1)
        d.text((x0 - S(10), yy), f"{tv}°", font=_font(12), fill=FAINT, anchor="rm")
    pts = [(xf(h), yT(v)) for h, v in zip(hrs, temp)]
    d.polygon(pts + [(xf(hrs[-1]), ay1), (xf(hrs[0]), ay1)], fill=TEMP + (36,))
    d.line(pts, fill=TEMP, width=S(3), joint="curve")
    d.text((x0, ay0 - S(16)), "Температура, °C", font=_font(13, True), fill=TEMP, anchor="lm")
    # panel B wind/gust (m/s)
    by0, by1 = S(376), S(Ht - 34)
    wmx = max(max(gust) + 1, 4)
    yW = lambda v: by1 - (by1 - by0) * v / wmx
    for wv in range(0, int(wmx) + 1, 2):
        yy = yW(wv); d.line([x0, yy, x1, yy], fill=GRID, width=1)
        d.text((x0 - S(10), yy), f"{wv}", font=_font(12), fill=FAINT, anchor="rm")
    d.line([(xf(h), yW(v)) for h, v in zip(hrs, gust)], fill=GUST, width=S(3), joint="curve")
    d.line([(xf(h), yW(v)) for h, v in zip(hrs, wind)], fill=WIND, width=S(3), joint="curve")
    d.text((x0, by0 - S(16)), "Ветер / порывы, м/с", font=_font(13, True), fill=INK, anchor="lm")
    lx = x1 - S(210)
    d.line([lx, by0 - S(12), lx + S(24), by0 - S(12)], fill=WIND, width=S(3))
    d.text((lx + S(30), by0 - S(12)), "ветер", font=_font(12), fill=MUTED, anchor="lm")
    d.line([lx + S(84), by0 - S(12), lx + S(108), by0 - S(12)], fill=GUST, width=S(3))
    d.text((lx + S(114), by0 - S(12)), "порывы", font=_font(12), fill=MUTED, anchor="lm")
    for h in hrs:
        if h % 2 == 0:
            d.text((xf(h), by1 + S(14)), f"{h:02d}", font=_font(12), fill=FAINT, anchor="mm")
    return _save(img, out, "01_meteogram.png")

# ---------------------------------------------------------------- ceiling
def ceiling_png(data, site, out):
    H, D = data["hourly"], data["daily"]
    t = H["time"]; sr, ss = D["sunrise"][0], D["sunset"][0]
    idx, h0, h1 = _daylight(t, sr, ss, pad=0)
    hrs = [_hour(t[i]) for i in idx]
    elev = site["elevation_m"]
    blh_msl = [elev + H["boundary_layer_height"][i] for i in idx]
    lcl_msl = [elev + max(0, 122 * (H["temperature_2m"][i] - H["dew_point_2m"][i])) for i in idx]
    W, Ht = 1040, 540
    img, d = _canvas(W, Ht)
    L, R = 66, 28
    x0, x1 = S(L), S(W - R); y0, y1 = S(112), S(Ht - 40)
    zmn = elev - 100
    zmx = max(max(lcl_msl), max(blh_msl)) + 200
    xf = lambda h: x0 + (x1 - x0) * (h - h0) / max(1, (h1 - h0))
    yf = lambda z: y1 - (y1 - y0) * (z - zmn) / (zmx - zmn)
    d.text((S(40), S(28)), f"{site['name']} — потолок термиков и база {t[0][:10]}", font=_font(24, True), fill=INK, anchor="lm")
    d.text((S(40), S(56)), "Потолок = высота пограничного слоя (MSL); LCL = уровень конденсации",
           font=_font(13), fill=MUTED, anchor="lm")
    zstep = 500
    for z in range(int((zmn // zstep + 1) * zstep), int(zmx), zstep):
        yy = yf(z); d.line([x0, yy, x1, yy], fill=GRID, width=1)
        d.text((x0 - S(10), yy), f"{z}", font=_font(12), fill=FAINT, anchor="rm")
    d.text((x0 - S(10), y0 - S(4)), "м MSL", font=_font(11), fill=FAINT, anchor="rb")
    ly = yf(elev); d.line([x0, ly, x1, ly], fill=MUTED, width=1)
    d.text((x1, ly - S(6)), f"старт {elev} м", font=_font(11), fill=MUTED, anchor="rb")
    lpts = [(xf(h), yf(v)) for h, v in zip(hrs, lcl_msl)]
    d.line(lpts, fill=WIND, width=S(3), joint="curve")
    bpts = [(xf(h), yf(v)) for h, v in zip(hrs, blh_msl)]
    d.polygon(bpts + [(xf(hrs[-1]), y1), (xf(hrs[0]), y1)], fill=GUST + (46,))
    d.line(bpts, fill=GUST, width=S(3), joint="curve")
    imax = blh_msl.index(max(blh_msl))
    d.text((xf(hrs[imax]), yf(blh_msl[imax]) - S(14)), "потолок термиков", font=_font(12, True), fill=GUST, anchor="mm")
    jmax = lcl_msl.index(max(lcl_msl))
    d.text((xf(hrs[jmax]), yf(lcl_msl[jmax]) - S(14)), "уровень конденсации (LCL)", font=_font(12, True), fill=WIND, anchor="mm")
    for h in hrs:
        d.text((xf(h), y1 + S(16)), f"{h:02d}", font=_font(12), fill=FAINT, anchor="mm")
    return _save(img, out, "02_ceiling.png")

# ---------------------------------------------------------------- wind profile
def profile_png(data, site, out):
    H, D = data["hourly"], data["daily"]
    t = H["time"]; sr, ss = D["sunrise"][0], D["sunset"][0]
    srh, ssh = _hour(sr), _hour(ss)
    # pick 3 daytime hours: prefer 11/14/17 clamped to daylight
    want = [11, 14, 17]
    hours = sorted({min(max(w, srh + 1), ssh - 1) for w in want})
    hidx = {h: next(i for i, tt in enumerate(t) if _hour(tt) == h) for h in hours}
    elev = site["elevation_m"]
    levels = [("10 м", elev + 10, "wind_speed_10m", "wind_direction_10m"),
              ("925", "geopotential_height_925hPa", "wind_speed_925hPa", "wind_direction_925hPa"),
              ("850", "geopotential_height_850hPa", "wind_speed_850hPa", "wind_direction_850hPa"),
              ("700", "geopotential_height_700hPa", "wind_speed_700hPa", "wind_direction_700hPa"),
              ("600", "geopotential_height_600hPa", "wind_speed_600hPa", None),
              ("500", "geopotential_height_500hPa", "wind_speed_500hPa", None)]
    ref = hidx[hours[len(hours)//2]]  # middle hour for heights & directions
    alt = [lv[1] if isinstance(lv[1], (int, float)) else H[lv[1]][ref] for lv in levels]
    W, Ht = 800, 640
    img, d = _canvas(W, Ht)
    L, R = 60, 156
    x0, x1 = S(L), S(W - R); y0, y1 = S(112), S(Ht - 48)
    smax = max(max(H[lv[2]][hidx[h]] for h in hours) for lv in levels) + 2
    zmn, zmx = elev - 100, max(alt) + 200
    xf = lambda s: x0 + (x1 - x0) * s / smax
    yf = lambda z: y1 - (y1 - y0) * (z - zmn) / (zmx - zmn)
    d.text((S(36), S(28)), f"{site['name']} — ветер по высотам {t[0][:10]}", font=_font(23, True), fill=INK, anchor="lm")
    d.text((S(36), S(56)), f"Профиль скорости (м/с), срезы " + " / ".join(f"{h:02d}:00" for h in hours),
           font=_font(13), fill=MUTED, anchor="lm")
    sstep = 2
    for s in range(0, int(smax) + 1, sstep):
        xx = xf(s); d.line([xx, y0, xx, y1], fill=GRID, width=1)
        d.text((xx, y1 + S(14)), f"{s}", font=_font(12), fill=FAINT, anchor="mm")
    d.text(((x0 + x1) / 2, y1 + S(34)), "скорость, м/с", font=_font(12), fill=MUTED, anchor="mm")
    for z in range(1000, int(zmx), 1000):
        yy = yf(z); d.line([x0, yy, x1, yy], fill=GRID, width=1)
        d.text((x0 - S(10), yy), f"{z}", font=_font(12), fill=FAINT, anchor="rm")
    d.text((x0 - S(10), y0 - S(2)), "м MSL", font=_font(11), fill=FAINT, anchor="rb")
    # working layer to max blh
    top = elev + max(H["boundary_layer_height"][hidx[h]] for h in hours)
    cut = yf(top)
    d.rectangle([x0, cut, x1, y1], fill=GUST + (24,))
    d.line([x0, cut, x1, cut], fill=RAIN, width=1)
    d.text((x0 + S(6), cut - S(8)), f"потолок рабочего слоя ~{round(top)} м", font=_font(11, True), fill=RAIN, anchor="lb")
    cols = {hours[0]: MUTED, hours[-1]: GUST}
    mid = hours[len(hours)//2]; cols[mid] = WIND
    for h in hours:
        col = cols.get(h, MUTED)
        w = S(3) if h == mid else S(2)
        pts = [(xf(H[lv[2]][hidx[h]]), yf(alt[k])) for k, lv in enumerate(levels)]
        d.line(pts, fill=col, width=w, joint="curve")
        for px, py in pts:
            d.ellipse([px - S(3), py - S(3), px + S(3), py + S(3)], fill=BG, outline=col, width=S(2))
    # direction letters at mid-hour for levels >= 850
    for k, lv in enumerate(levels):
        if lv[3] and alt[k] > elev + 300:
            dg = H[lv[3]][ref]
            d.text((xf(H[lv[2]][ref]) + S(11), yf(alt[k]) + S(3)), _card(dg), font=_font(11, True), fill=INK, anchor="lm")
    # legend
    lx, lyy = x1 + S(22), y0 + S(10)
    order = [(mid, f"{mid:02d}:00 (пик)"), (hours[-1], f"{hours[-1]:02d}:00"), (hours[0], f"{hours[0]:02d}:00")]
    seen = set()
    for h, lab in order:
        if h in seen: continue
        seen.add(h)
        d.line([lx, lyy, lx + S(22), lyy], fill=cols.get(h, MUTED), width=S(3))
        d.text((lx + S(28), lyy), lab, font=_font(12), fill=MUTED, anchor="lm")
        lyy += S(22)
    d.text((lx, lyy + S(12)), "буквы — направление", font=_font(11), fill=FAINT, anchor="lm")
    return _save(img, out, "03_windprofile.png")

# ---------------------------------------------------------------- overview
def overview_png(rows, site, rng, out):
    DOW = ["ПН","ВТ","СР","ЧТ","ПТ","СБ","ВС"]
    MON = ["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"]
    import datetime as dt
    def lab(dcode):
        dd = dt.date.fromisoformat(dcode); return f"{DOW[dd.weekday()]} {dd.day}"
    n = len(rows)
    W, Ht = max(760, 96 * n + 120), 480
    img, d = _canvas(W, Ht)
    L, R = 48, 24
    x0, x1 = S(L), S(W - R); y0, y1 = S(96), S(Ht - 92)
    gmax = max(max(r["gmax"] for r in rows) + 1, 6)
    slot = (x1 - x0) / n; bw = min(slot * 0.5, S(70))
    yf = lambda v: y1 - (y1 - y0) * v / gmax
    colFor = lambda e: RAIN if e == "❌" else (WARN if e == "⚠️" else GOOD)
    names = {"3d": "3 дня", "week": "неделю", "2weeks": "2 недели"}
    d.text((S(36), S(28)), f"{site['name']} — обзор на {names[rng]}", font=_font(24, True), fill=INK, anchor="lm")
    d.text((S(36), S(56)), "Высота столбца — макс. порыв за светлое время (м/с); цвет — пригодность",
           font=_font(13), fill=MUTED, anchor="lm")
    for gv in range(0, int(gmax) + 1, 2):
        yy = yf(gv); d.line([x0, yy, x1, yy], fill=GRID, width=1)
        d.text((x0 - S(6), yy), f"{gv}", font=_font(12), fill=FAINT, anchor="rm")
    d.text((x0 - S(6), y0 - S(6)), "м/с", font=_font(11), fill=FAINT, anchor="rb")
    best = max(range(n), key=lambda i: rows[i]["score"])
    for i, r in enumerate(rows):
        cx = x0 + slot * (i + 0.5); bx0 = cx - bw / 2; yy = yf(r["gmax"])
        if i == best:
            d.rounded_rectangle([bx0 - S(4), yy - S(4), cx + bw/2 + S(4), y1], radius=S(6), outline=BEST, width=S(2))
        d.rounded_rectangle([bx0, yy, cx + bw / 2, y1], radius=S(4), fill=colFor(r["emoji"]) + (235,))
        d.text((cx, yy - S(10)), f"{r['gmax']:.0f}", font=_font(13, True), fill=INK, anchor="mm")
        d.text((cx, y1 + S(18)), lab(r["date"]), font=_font(12, True), fill=INK, anchor="mm")
        d.text((cx, y1 + S(36)), r["label"].split()[0], font=_font(11), fill=MUTED, anchor="mm")
        tail = f"{r['tmax']:.0f}°" + (f" · {r['precip']:.1f}мм" if r["precip"] > 0.2 else "")
        d.text((cx, y1 + S(52)), tail, font=_font(11), fill=FAINT, anchor="mm")
    return _save(img, out, "04_overview.png")

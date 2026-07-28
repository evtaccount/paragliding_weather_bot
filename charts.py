#!/usr/bin/env python3
"""PNG charts for the paragliding forecast — light theme, wind in m/s, pure Pillow."""
import math
import os
from PIL import Image, ImageDraw, ImageFont

import criteria as _criteria

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
TERRAIN = (150, 142, 128)   # заливка рельефа на разрезе маршрута
BAND    = (110, 170, 210)   # заливка рабочего коридора

# Цвет уровня оценки. Ключи — уровни criteria; сами пороги живут только там,
# здесь остаётся исключительно палитра.
GRADE_RGB = {
    "ideal":     (22, 97, 58),
    "excellent": (63, 143, 87),
    "fair":      (198, 154, 30),
    "marginal":  (194, 94, 18),
    "no_fly":    (194, 58, 82),
    "danger":    (140, 30, 52),
    "no_data":   (158, 158, 148),
}

# Font candidates, in priority order, covering macOS (dev) and Linux/Docker (deploy).
# DejaVu / Liberation ship Cyrillic glyphs and are installed in the container.
_FONT_PATHS = {
    False: [
        "/System/Library/Fonts/Supplemental/Arial.ttf",              # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",           # Debian/Ubuntu
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",                    # Alpine/other
        "/System/Library/Fonts/Helvetica.ttc",
    ],
    True: [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
}

def _font(sz, bold=False):
    for p in _FONT_PATHS[bold]:
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

def _wind_arrow(d, cx, cy, from_deg, r, color):
    """Arrow pointing where the wind BLOWS TO, map-oriented (N up, E right).
    Input stays the meteorological source bearing (open-meteo wind_direction_*),
    so a wind from the south (180°) is drawn pointing up, toward the north."""
    to_deg = (from_deg + 180) % 360
    a = math.radians(to_deg)
    dx, dy = math.sin(a), -math.cos(a)          # bearing → screen vector
    hx, hy = cx + dx * r, cy + dy * r           # head, downwind
    tx, ty = cx - dx * r, cy - dy * r           # tail, toward source
    d.line([tx, ty, hx, hy], fill=color, width=S(2))
    for wing in (to_deg + 148, to_deg - 148):
        wa = math.radians(wing)
        d.line([hx, hy, hx + math.sin(wa) * r * 0.55, hy - math.cos(wa) * r * 0.55],
               fill=color, width=S(2))

def _daylight(times, sr, ss, pad=1):
    lo, hi = max(0, _hour(sr) - pad), min(23, _hour(ss) + pad)
    idx = [i for i, t in enumerate(times) if lo <= _hour(t) <= hi]
    return idx, lo, hi

# ---------------------------------------------------------------- meteogram
def meteogram_png(data, site, out, assess=None):
    H, D = data["hourly"], data["daily"]
    t = H["time"]; sr, ss = D["sunrise"][0], D["sunset"][0]
    idx, h0, h1 = _daylight(t, sr, ss)
    hrs = [_hour(t[i]) for i in idx]
    temp = [H["temperature_2m"][i] for i in idx]
    wind = [H["wind_speed_10m"][i] for i in idx]
    gust = [H["wind_gusts_10m"][i] for i in idx]
    wdir = [H["wind_direction_10m"][i] for i in idx]
    srh, ssh = _hour(sr), _hour(ss)
    W, Ht = 1040, 692   # +40 к прежней высоте — под ленту категорий у нижнего края
    img, d = _canvas(W, Ht)
    L, R = 66, 30
    x0, x1 = S(L), S(W - R)
    xf = lambda h: x0 + (x1 - x0) * (h - h0) / max(1, (h1 - h0))
    d.text((S(40), S(28)), f"{site['name']} — метеограмма {t[0][:10]}", font=_font(24, True), fill=INK, anchor="lm")
    d.text((S(40), S(56)), f"Светлое время {srh:02d}–{ssh:02d} · ветер в м/с, стрелки — куда дует · {data.get('timezone','')}",
           font=_font(13), fill=MUTED, anchor="lm")
    # Лётное окно берётся из ГОТОВОЙ оценки (engine.assess_day → criteria), а не
    # пересчитывается здесь по своим порогам: раньше карточка и график считали
    # лётность независимо, совпадали по случайности и разъезжались от любой правки.
    if assess is None:
        from engine import assess_day
        assess, _ctx = assess_day(data, site)
    fly = assess.fly_hours
    segs = []
    for h in fly:
        if segs and h == segs[-1][-1] + 1:
            segs[-1].append(h)
        else:
            segs.append([h])
    if segs:
        for s in segs:  # widen by ½h each side so a lone flyable hour is still visible
            bx0 = max(x0, xf(s[0] - 0.5)); bx1 = min(x1, xf(s[-1] + 0.5))
            d.rectangle([bx0, S(84), bx1, S(586)], fill=GUST + (26,))
        wins = ", ".join(f"{s[0]:02d}–{s[-1]:02d}" if len(s) > 1 else f"{s[0]:02d}" for s in segs)
        mid = (xf(fly[0]) + xf(fly[-1])) / 2  # center over the span → clear of the panel labels
        d.text((mid, S(96)), f"лётное окно {wins}", font=_font(12, True), fill=GUST, anchor="mm")
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
    by0, by1 = S(376), S(Ht - 106)
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
    # wind-direction arrow lane + hour axis (every 2 h)
    ya = by1 + S(22)
    for h, wd in zip(hrs, wdir):
        if h % 2 == 0:
            _wind_arrow(d, xf(h), ya, wd, S(8), WIND)
            d.text((xf(h), by1 + S(46)), f"{h:02d}", font=_font(12), fill=FAINT, anchor="mm")
    # Лента категорий: по одной ячейке на час со своим цветом оценки. Полоса
    # лётного окна показывает только «летаем / не летаем», а лента — насколько
    # хорошо, и где именно день проседает.
    ry0, ry1 = S(Ht - 38), S(Ht - 18)
    by_hour = {h.hour: h for h in assess.hours}
    for h in hrs:
        a = by_hour.get(h)
        if a is None:
            continue
        cx0, cx1 = max(x0, xf(h - 0.5)), min(x1, xf(h + 0.5))
        d.rectangle([cx0, ry0, cx1, ry1], fill=GRADE_RGB.get(a.category, MUTED) + (190,))
        if a.vetoes:  # час под вето — отметить, а не просто закрасить красным
            d.text(((cx0 + cx1) / 2, (ry0 + ry1) / 2), "×", font=_font(11, True), fill=BG, anchor="mm")
    d.text((x0 - S(10), (ry0 + ry1) / 2), "оценка", font=_font(11), fill=FAINT, anchor="rm")
    return _save(img, out, "01_meteogram.png")

# ---------------------------------------------------------------- ceiling
def ceiling_png(data, site, out):
    H, D = data["hourly"], data["daily"]
    t = H["time"]; sr, ss = D["sunrise"][0], D["sunset"][0]
    idx, h0, h1 = _daylight(t, sr, ss, pad=0)
    hrs = [_hour(t[i]) for i in idx]
    elev = site["elevation_m"]
    blh_msl = [elev + H["boundary_layer_height"][i] for i in idx]
    lcl_msl = [elev + max(0, _criteria.LCL_M_PER_C * (H["temperature_2m"][i] - H["dew_point_2m"][i]))
               for i in idx]
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
    # общая с engine таблица уровней: своя копия здесь молча теряла направления
    # на 600 и 500 гПа (там стояли None), хотя движок их запрашивает
    from engine import _GRID_LEVELS
    levels = _GRID_LEVELS
    ref = hidx[hours[len(hours)//2]]  # middle hour for heights & directions
    alt = [elev + 10 if lv[1] == "elev+10" else H[lv[1]][ref] for lv in levels]
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
    # working layer to max blh — only when the model provides it (ECMWF omits blh)
    blh_vals = [H.get("boundary_layer_height", [None] * len(t))[hidx[h]] for h in hours]
    if any(v is not None for v in blh_vals):
        top = elev + max(v for v in blh_vals if v is not None)
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

# ---------------------------------------------------------------- wind grid (altitude × hour)
# Строка сетки → параметр criteria с его порогами. Выше 850 гПа парапланерных
# порогов нет — там ветер показывается по шкале 850 как ближайшей осмысленной.
_GRID_PARAM = {"10 м": "wind_10m", "925": "wind_925"}


def _grid_cell_color(ms, level_label="10 м"):
    grade = _criteria.grade_of(_GRID_PARAM.get(level_label, "wind_850"), ms)
    return GRADE_RGB.get(grade, MUTED)


def wind_grid_png(grid, site, out):
    """Altitude (rows, high→top) × hour (cols) grid. Each cell: colored by wind speed,
    an arrow (where the wind blows to) and the speed number. Launch row highlighted."""
    hours = grid["hours"]
    levels = list(reversed(grid["levels"]))  # high altitude on top
    nrows, ncols = len(levels), len(hours)
    LabW, RowH, ColW = 120, 52, 64
    Wc = LabW + ColW * ncols + 24
    Hc = 104 + RowH * nrows + 64
    img, d = _canvas(Wc, Hc)
    x0 = S(LabW)
    y0 = S(104)
    cw, ch = S(ColW), S(RowH)
    xf = lambda c: x0 + cw * c
    yf = lambda r: y0 + ch * r
    d.text((S(36), S(28)), f"{site['name']} — ветер по высотам × часам {grid['date']}",
           font=_font(22, True), fill=INK, anchor="lm")
    d.text((S(36), S(56)), f"стрелка — куда дует · скорость м/с · {grid.get('timezone','')}",
           font=_font(13), fill=MUTED, anchor="lm")
    # hour headers
    for c, h in enumerate(hours):
        d.text((xf(c) + cw / 2, y0 - S(12)), f"{h:02d}", font=_font(12, True), fill=MUTED, anchor="mm")
    # rows
    for r, lv in enumerate(levels):
        ry0, ry1 = yf(r), yf(r + 1)
        lab = f"{lv['alt_m_msl']} м" + (" (старт)" if lv["is_launch"] else "")
        if lv["is_launch"]:
            d.rectangle([x0, ry0, xf(ncols), ry1], fill=GUST + (18,))
        d.text((x0 - S(8), (ry0 + ry1) / 2), lab, font=_font(12, lv["is_launch"]),
               fill=INK if lv["is_launch"] else MUTED, anchor="rm")
        for c, cell in enumerate(lv["hourly"]):
            cx0, cy0 = xf(c), ry0
            col = _grid_cell_color(cell["wind_ms"], lv["label"])
            d.rectangle([cx0 + S(1), cy0 + S(1), cx0 + cw - S(1), ry1 - S(1)], fill=col + (48,))
            _wind_arrow(d, cx0 + cw * 0.32, (cy0 + ry1) / 2, cell["dir_deg"], S(9), col)
            d.text((cx0 + cw * 0.66, (cy0 + ry1) / 2), f"{cell['wind_ms']:.0f}",
                   font=_font(13, True), fill=INK, anchor="mm")
    # grid lines
    for r in range(nrows + 1):
        d.line([x0, yf(r), xf(ncols), yf(r)], fill=GRID, width=1)
    for c in range(ncols + 1):
        d.line([xf(c), y0, xf(c), yf(nrows)], fill=GRID, width=1)
    # legend
    # Легенда — уровни оценки, а не числа: у каждой строки свои пороги (у земли,
    # на 925 и на 850 они разные), одна числовая шкала на всю таблицу врала бы.
    ly = yf(nrows) + S(26)
    lx = x0
    for grade in _criteria.GRADES:
        d.rectangle([lx, ly - S(7), lx + S(14), ly + S(7)], fill=GRADE_RGB[grade] + (200,))
        d.text((lx + S(20), ly), _criteria.GRADE_LABEL[grade], font=_font(11), fill=MUTED, anchor="lm")
        lx += S(int(11 * len(_criteria.GRADE_LABEL[grade]) * 0.62) + 34)
    d.text((x0, ly + S(24)), "пороги: у земли, 925 и 850 гПа — свои; выше — по шкале 850 · стрелка — куда дует",
           font=_font(11), fill=FAINT, anchor="lm")
    return _save(img, out, "05_windgrid.png")

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
    # цвет — по категории дня из скоринга; раньше он разбирался из строки эмодзи,
    # где ⚠️ означал сразу два разных вердикта
    names = {"3d": "3 дня", "week": "неделю", "2weeks": "2 недели"}
    d.text((S(36), S(28)), f"{site['name']} — обзор на {names[rng]}", font=_font(24, True), fill=INK, anchor="lm")
    d.text((S(36), S(56)), "Высота столбца — макс. порыв за светлое время (м/с); цвет и число — балл дня",
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
        col = GRADE_RGB.get(r.get("category"), MUTED)
        d.rounded_rectangle([bx0, yy, cx + bw / 2, y1], radius=S(4), fill=col + (235,))
        d.text((cx, yy - S(10)), f"{r['gmax']:.0f}", font=_font(13, True), fill=INK, anchor="mm")
        d.text((cx, y1 + S(18)), lab(r["date"]), font=_font(12, True), fill=INK, anchor="mm")
        d.text((cx, y1 + S(36)), f"{round(r['score'])}/100", font=_font(12, True), fill=col, anchor="mm")
        tail = f"{r['tmax']:.0f}°" + (f" · {r['precip']:.1f}мм" if r["precip"] > _criteria.RAIN_DAY_MM else "")
        d.text((cx, y1 + S(52)), tail, font=_font(11), fill=FAINT, anchor="mm")
    return _save(img, out, "04_overview.png")

# ---------------------------------------------------------------- разрез маршрута
ARROWS_MAX = 12             # больше стрелок в ряд слипаются в кашу


def _arrow_indexes(n):
    """Индексы точек, у которых рисуется стрелка ветра."""
    step = max(1, math.ceil(n / ARROWS_MAX))
    return list(range(0, n, step))


def _runs(xs, ys):
    """Непрерывные куски (x, y), обрывающиеся на None.

    Соединять через пропуск нельзя: это рисование данных, которых нет.
    """
    out, cur = [], []
    for x, y in zip(xs, ys):
        if y is None:
            if len(cur) > 1:
                out.append(cur)
            cur = []
        else:
            cur.append((x, y))
    if len(cur) > 1:
        out.append(cur)
    return out


def _ends(xs, ys):
    """Левый и правый концы серии — (x, y) первого и последнего не-None."""
    live = [(x, y) for x, y in zip(xs, ys) if y is not None]
    return (live[0], live[-1]) if live else (None, None)


def _collapsed_segments(floor, top):
    """Индексы участков, где рабочего коридора нет: верх не выше пола.

    Участок с неизвестными концами не считается схлопнутым — «неизвестно» и
    «негде лететь» это разные вещи, и путать их в сторону тревоги тоже плохо.
    """
    out = []
    for i in range(len(floor) - 1):
        f0, f1, t0, t1 = floor[i], floor[i + 1], top[i], top[i + 1]
        if None in (f0, f1, t0, t1):
            continue
        if t0 <= f0 or t1 <= f1:
            out.append(i)
    return out


def _terrain_at(tkm, telev, km):
    """Высота рельефа по мелкой сетке в заданном километре.

    Отметки ставятся именно на неё, а не на terrain_m точки: terrain_m —
    максимум по участку, и треугольник по нему повис бы над землёй.
    """
    i = min(range(len(tkm)), key=lambda k: abs(tkm[k] - km))
    return telev[i]


def route_section_png(profile, out):
    """Разрез вдоль маршрута: рельеф, безопасная высота, рабочий коридор,
    потолок термиков и база, ветер, время прилёта и лента лётности.

    None, если рельефа нет: без него на картинке остаётся пустая рамка.
    """
    terrain = profile.get("terrain") or {}
    tkm, telev = terrain.get("km") or [], terrain.get("elevations") or []
    if not tkm or not telev:
        return None
    pts, r = profile["points"], profile["route"]
    total = r.get("total_km") or tkm[-1] or 1.0

    skm = [p["km"] for p in pts]
    floor = [None if p.get("terrain_m") is None
             else p["terrain_m"] + _criteria.MIN_WORKING_ALT_AGL for p in pts]
    base = [p.get("cloud_base_m") for p in pts]
    ceil = [p.get("thermal_ceiling_m") for p in pts]
    top = [None if b is None and c is None
           else min(v for v in (b, c) if v is not None) for b, c in zip(base, ceil)]

    W, Ht = 1040, 660
    img, d = _canvas(W, Ht)
    L, R = 74, 30
    x0, x1 = S(L), S(W - R)
    y0, y1 = S(118), S(Ht - 176)
    highs = [v for v in list(base) + list(ceil) + list(floor) if v is not None]
    zmn = min(telev) - 100
    zmx = max(highs + [max(telev)]) + 200
    # Поле по краям: крайние точки стоят на 0 и на total, и без отступа их
    # подписи налезают на названия строк слева и вылезают за холст справа.
    pad = S(26)
    xf = lambda km: x0 + pad + (x1 - x0 - 2 * pad) * km / max(total, 0.001)
    yf = lambda z: y1 - (y1 - y0) * (z - zmn) / max(zmx - zmn, 1.0)

    title = r.get("name") or "Маршрут"
    d.text((S(40), S(28)), f"{title} — разрез маршрута {r['date']}",
           font=_font(23, True), fill=INK, anchor="lm")
    d.text((S(40), S(56)),
           f"вылет {r.get('departure') or '—'} · {total:.0f} км · "
           f"стрелки — куда дует · {r.get('timezone', '')}",
           font=_font(13), fill=MUTED, anchor="lm")

    for z in range(int((zmn // 500 + 1) * 500), int(zmx), 500):
        yy = yf(z)
        d.line([x0, yy, x1, yy], fill=GRID, width=1)
        d.text((x0 - S(10), yy), f"{z}", font=_font(12), fill=FAINT, anchor="rm")
    d.text((x0 - S(10), y0 - S(4)), "м MSL", font=_font(11), fill=FAINT, anchor="rb")

    # Рабочий коридор — по трапеции на каждый участок между расчётными точками.
    # Это главное, ради чего картинка рисуется: где он схлопывается, видно сразу.
    collapsed = _collapsed_segments(floor, top)
    for i in range(len(pts) - 1):
        f0, f1, t0, t1 = floor[i], floor[i + 1], top[i], top[i + 1]
        if None in (f0, f1, t0, t1):
            continue
        quad = [(xf(skm[i]), yf(f0)), (xf(skm[i + 1]), yf(f1)),
                (xf(skm[i + 1]), yf(t1)), (xf(skm[i]), yf(t0))]
        bad = i in collapsed
        d.polygon(quad, fill=(RAIN if bad else BAND) + (56 if bad else 40,))
        # Подписывается только ПЕРВЫЙ схлопнутый участок: дальше это видно по
        # цвету, а повторные подписи на соседних участках налезают друг на друга.
        if collapsed and i == collapsed[0]:
            d.text(((xf(skm[i]) + xf(skm[i + 1])) / 2, yf(max(f0, f1)) - S(10)),
                   f"коридора нет с {skm[i]:.0f} км", font=_font(11, True),
                   fill=RAIN, anchor="mm")

    ground = [(xf(km), yf(z)) for km, z in zip(tkm, telev)]
    d.polygon(ground + [(xf(tkm[-1]), y1), (xf(tkm[0]), y1)], fill=TERRAIN + (210,))

    # Пол рабочего коридора: ниже него working_band уходит в минус и срабатывает
    # вето. Порог берётся из criteria, своей копии здесь не заводится.
    for run in _runs(skm, floor):
        for a, b in zip(run, run[1:]):
            d.line([xf(a[0]), yf(a[1]), xf(b[0]), yf(b[1])], fill=MUTED, width=S(1))
    # Подписи ставятся у КОНЦОВ линий, а не у их максимумов: линия наклонная, и
    # подпись у максимума оказывается в стороне от того места, куда указывает.
    _lo, hi = _ends(skm, floor)
    if hi:
        d.text((xf(hi[0]), yf(hi[1]) - S(6)),
               f"безопасная высота (+{_criteria.MIN_WORKING_ALT_AGL} м)",
               font=_font(11), fill=MUTED, anchor="rb")

    for run in _runs(skm, ceil):
        d.line([(xf(x), yf(y)) for x, y in run], fill=GUST, width=S(3), joint="curve")
    for run in _runs(skm, base):
        d.line([(xf(x), yf(y)) for x, y in run], fill=WIND, width=S(3), joint="curve")
    lo, _hi = _ends(skm, ceil)
    if lo:
        d.text((xf(lo[0]), yf(lo[1]) - S(8)), "потолок термиков",
               font=_font(12, True), fill=GUST, anchor="lb")
    _lo, hi = _ends(skm, base)
    if hi:
        d.text((xf(hi[0]), yf(hi[1]) + S(8)), "база облаков",
               font=_font(12, True), fill=WIND, anchor="rt")

    # Отметки: обрыв важнее узкого места, узкое место важнее поворотной точки.
    v = profile.get("verdict") or {}
    marked = set()
    for km, colour, label in (
            (v.get("blocked_at_km"), RAIN, "обрыв"),
            ((v.get("bottleneck") or {}).get("km"), WARN, "узкое место")):
        if km is None or round(km, 1) in marked:
            continue
        marked.add(round(km, 1))
        d.line([xf(km), y0, xf(km), y1], fill=colour, width=S(2))
        d.text((xf(km), y0 - S(8)), f"{label}, {km:.0f} км",
               font=_font(11, True), fill=colour, anchor="mb")
    for p in pts:
        if not p.get("is_turnpoint") or round(p["km"], 1) in marked:
            continue
        marked.add(round(p["km"], 1))
        gy = yf(_terrain_at(tkm, telev, p["km"]))
        d.polygon([(xf(p["km"]), gy - S(9)), (xf(p["km"]) - S(5), gy),
                   (xf(p["km"]) + S(5), gy)], fill=INK)
        if p.get("name"):
            d.text((xf(p["km"]), gy - S(12)), p["name"], font=_font(11),
                   fill=INK, anchor="mb")

    # Полосы под панелью: стрелки ветра, километры, время прилёта, лента лётности.
    ya = y1 + S(26)
    for i in _arrow_indexes(len(pts)):
        p = pts[i]
        if p.get("wind_working_alt_dir") is not None:
            _wind_arrow(d, xf(p["km"]), ya, p["wind_working_alt_dir"], S(9), WIND)
            d.text((xf(p["km"]), ya + S(20)),
                   f"{p.get('wind_working_alt_kmh') or 0:.0f}",
                   font=_font(11), fill=MUTED, anchor="mm")
        d.text((xf(p["km"]), ya + S(40)), f"{p['km']:.0f}",
               font=_font(12), fill=FAINT, anchor="mm")
        d.text((xf(p["km"]), ya + S(58)), p.get("eta") or "—",
               font=_font(11), fill=FAINT, anchor="mm")
    d.text((x0 - S(10), ya), "ветер", font=_font(11), fill=FAINT, anchor="rm")
    d.text((x0 - S(10), ya + S(40)), "км", font=_font(11), fill=FAINT, anchor="rm")
    d.text((x0 - S(10), ya + S(58)), "время", font=_font(11), fill=FAINT, anchor="rm")

    ry0, ry1 = S(Ht - 42), S(Ht - 22)
    for i, p in enumerate(pts):
        lo = skm[i] if i == 0 else (skm[i - 1] + skm[i]) / 2
        hi = skm[i] if i == len(pts) - 1 else (skm[i] + skm[i + 1]) / 2
        d.rectangle([xf(lo), ry0, xf(hi), ry1],
                    fill=GRADE_RGB.get(p.get("category"), MUTED) + (190,))
        if p.get("vetoes"):
            d.text(((xf(lo) + xf(hi)) / 2, (ry0 + ry1) / 2), "×",
                   font=_font(11, True), fill=BG, anchor="mm")
    d.text((x0 - S(10), (ry0 + ry1) / 2), "лётность", font=_font(11),
           fill=FAINT, anchor="rm")
    return _save(img, out, "06_route_section.png")

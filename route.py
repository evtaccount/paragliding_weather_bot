"""Маршрут: разбор ввода, геометрия, время прибытия, маршрутные величины.

Модуль намеренно чистый — ни сети, ни aiogram, ни глобального состояния.
Всё, что здесь считается, проверяемо офлайн: геометрия и знаки ветра — ровно то
место, где ошибка выглядит правдоподобно и не ловится глазами.

ЧЕГО ЭТОТ РАСЧЁТ НЕ ВИДИТ. Список не декоративный: каждый пункт — известное
направление, в котором ответ систематически врёт, и знать их важнее, чем цифры.

1. Сетка модели 9–11 км не разрешает долинные ветры. На маршруте по ущельям
   составляющая вдоль курса будет неверна именно там, где она важнее всего — в
   узких местах, где локальный ветер расходится с синоптическим на 90° и больше.
2. Конвергенции и облачные улицы — главные «трассы» горного кросс-кантри — на
   такой сетке невидимы полностью. Хорошие дни с выраженной конвергенцией расчёт
   систематически недооценивает.
3. Маршрут считается по прямой между точками. Реальный кросс-кантри уходит к
   облакам и вдоль хребтов, фактический путь на 10–25 % длиннее прямой, и время
   прибытия соответственно позже.
4. Средняя маршрутная скорость сама зависит от условий: в слабый день она падает,
   и оценка «долечу к 15:00» становится оптимистичной вдвойне — летишь медленнее
   и окно закрывается раньше.
5. Рельеф сэмплируется с шагом 1 км по DEM 90 м. Узкий перевал шириной 500 м
   может быть пропущен, и наоборот — острая вершина рядом с трассой может дать
   ложное срабатывание ограничения по высоте.

Ещё две оговорки стоят рядом с кодом, к которому относятся: про базу облаков —
у `cloud_base_m`, про марш времени вперёд — у `march`.
"""
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace

import criteria
import engine

MIN_POINTS = 2
MAX_POINTS = 50           # потолок числа точек на входе
MAX_GPX_BYTES = 1_048_576  # 1 МБ: чужой трек на сотни тысяч точек не должен класть бота


class RouteError(Exception):
    """Ошибка разбора маршрута, показываемая пользователю как есть."""


class Point:
    __slots__ = ("lat", "lon", "name")

    def __init__(self, lat, lon, name=None):
        self.lat, self.lon, self.name = float(lat), float(lon), name or None

    def __repr__(self):
        return f"Point({self.lat}, {self.lon}, {self.name!r})"

    def __eq__(self, other):
        return (isinstance(other, Point) and self.lat == other.lat
                and self.lon == other.lon and self.name == other.name)


# Запятая допускается как дробный разделитель прямо в шаблоне числа: тогда
# «42,4776, 44,4787» разбирается как два числа, а не как четыре, и отдельное
# правило склейки не нужно.
_NUM = re.compile(r"[-+]?\d{1,3}(?:[.,]\d+)?")
_DMS = re.compile(r"(\d{1,3})\s*°\s*(\d{1,2})\s*['′]\s*(\d{1,2}(?:[.,]\d+)?)\s*[\"″]?\s*([NSEWСЮВЗ])",
                  re.IGNORECASE)


def _num(text):
    return float(text.replace(",", "."))


def _dms_value(deg, minutes, seconds, hemi):
    v = int(deg) + int(minutes) / 60.0 + _num(seconds) / 3600.0
    return -v if hemi.upper() in ("S", "W", "Ю", "З") else v


def _checked(lat, lon, name, line):
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise RouteError(f"координаты вне допустимых пределов: «{line}»")
    return Point(lat, lon, name)


def _parse_line(line):
    """Строка → Point, либо None для пустых и комментариев. RouteError на мусоре."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    dms = _DMS.findall(line)
    if len(dms) >= 2:
        return _checked(_dms_value(*dms[0]), _dms_value(*dms[1]), None, line)

    nums = list(_NUM.finditer(line))
    if len(nums) < 2:
        raise RouteError(f"не похоже на координаты: «{line}»")
    lat, lon = _num(nums[0].group()), _num(nums[1].group())
    name = line[nums[1].end():].strip(" ,;\t") or None
    return _checked(lat, lon, name, line)


def _checked_count(points):
    if len(points) < MIN_POINTS:
        raise RouteError(f"нужно минимум {MIN_POINTS} точки, прислана {len(points)}")
    if len(points) > MAX_POINTS:
        raise RouteError(f"слишком много точек: {len(points)}, максимум {MAX_POINTS}")
    return points


def parse_text(text, first_line_no=1):
    """Многострочный или однострочный список координат → точки маршрута.

    `first_line_no` — номер, под которым идёт первая строка `text` в исходном
    сообщении: бот отрезает строку с командой, а пользователь считает строки
    у себя целиком, и номер в ошибке должен совпадать с тем, что он видит.
    """
    lines = list(enumerate(text.splitlines(), first_line_no))
    meaningful = [(n, ln) for n, ln in lines
                  if ln.strip() and not ln.strip().startswith("#")]
    # Однострочный компактный вид: «lat,lon lat,lon lat,lon».
    if len(meaningful) == 1:
        n, only = meaningful[0]
        chunks = only.split()
        if len(chunks) >= MIN_POINTS and all("," in c or "." in c for c in chunks):
            lines = [(n, c) for c in chunks]

    points = []
    for n, line in lines:
        try:
            p = _parse_line(line)
        except RouteError as e:
            raise RouteError(f"строка {n}: {e}") from None
        if p is not None:
            points.append(p)
    return _checked_count(points)


# ---------------------------------------------------------------- GPX
def _tag(el):
    """Локальное имя тега без пространства имён — они у экспортёров разные."""
    return el.tag.rsplit("}", 1)[-1].lower()


def _find_all(root, name):
    return [el for el in root.iter() if _tag(el) == name]


def _child_name(el):
    for ch in el:
        if _tag(ch) == "name" and ch.text:
            return ch.text.strip()
    return None


def _points_from(elements):
    out = []
    for el in elements:
        try:
            out.append(Point(float(el.get("lat")), float(el.get("lon")), _child_name(el)))
        except (TypeError, ValueError):
            continue
    return out


def _thin(points, limit):
    """Равномерное прореживание с сохранением обоих концов."""
    if len(points) <= limit:
        return points
    step = (len(points) - 1) / (limit - 1)
    idx = sorted({round(i * step) for i in range(limit)} | {0, len(points) - 1})
    return [points[i] for i in idx][:limit]


def parse_gpx(data):
    """GPX → (точки, имя маршрута). Приоритет: <rte> → <trk> → <wpt>."""
    if len(data) > MAX_GPX_BYTES:
        raise RouteError(f"файл больше {MAX_GPX_BYTES // 1024} КБ — пришли маршрут покороче")
    # xml.etree раскрывает внутренние сущности, поэтому килобайтный файл с
    # вложенными <!ENTITY> разворачивается в гигабайты и съедает память бота
    # («billion laughs»). В настоящих GPX объявлений DTD не бывает — режем их
    # до разбора. Так обходимся без зависимости defusedxml.
    if b"<!DOCTYPE" in data[:4096].upper() or b"<!ENTITY" in data.upper():
        raise RouteError("в файле есть объявления DOCTYPE или сущностей — "
                         "такой GPX не разбираю")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise RouteError(f"не удалось разобрать GPX: {e}") from None

    name = _child_name(root)
    for tag in ("rtept", "trkpt", "wpt"):
        points = _points_from(_find_all(root, tag))
        if points:
            return _checked_count(_thin(points, MAX_POINTS)), name
    raise RouteError("в GPX нет ни маршрута, ни трека, ни путевых точек")


# ---------------------------------------------------------------- KML
def _kml_coords(text):
    """«долгота,широта[,высота] ...» → [(широта, долгота), ...].

    Порядок в KML обратный GPX, и это главная ловушка формата: перепутать —
    значит молча улететь в другое полушарие. Высота игнорируется: рельеф
    берётся из DEM, а в файлах она бывает то над геоидом, то над эллипсоидом.
    """
    out = []
    for chunk in (text or "").split():
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        out.append((lat, lon))
    return out


def _kml_points(el, name=None):
    out = []
    for c in el.iter():
        if _tag(c) == "coordinates":
            out += [Point(lat, lon, name) for lat, lon in _kml_coords(c.text)]
    return out


def parse_kml(data):
    """KML → (точки, имя маршрута). Приоритет: <LineString> → <Point> → любые
    <coordinates> — та же логика «маршрут важнее трека важнее точек», что у GPX."""
    if len(data) > MAX_GPX_BYTES:
        raise RouteError(f"файл больше {MAX_GPX_BYTES // 1024} КБ — пришли маршрут покороче")
    # Та же защита от «billion laughs», что и в parse_gpx: килобайтный файл с
    # вложенными <!ENTITY> разворачивается в гигабайты и съедает память бота.
    if b"<!DOCTYPE" in data[:4096].upper() or b"<!ENTITY" in data.upper():
        raise RouteError("в файле есть объявления DOCTYPE или сущностей — "
                         "такой KML не разбираю")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise RouteError(f"не удалось разобрать KML: {e}") from None

    marks = _find_all(root, "placemark")
    name = next((_child_name(d) for d in _find_all(root, "document")
                 if _child_name(d)), None)
    if name is None:
        name = next((_child_name(pm) for pm in marks if _child_name(pm)), None)

    line = []
    for ls in _find_all(root, "linestring"):
        line += _kml_points(ls)
    if line:
        return _checked_count(_thin(line, MAX_POINTS)), name

    pins = []
    for pm in marks:
        for pt in (el for el in pm.iter() if _tag(el) == "point"):
            pins += _kml_points(pt, _child_name(pm))
    if pins:
        return _checked_count(_thin(pins, MAX_POINTS)), name

    loose = _kml_points(root)
    if loose:
        return _checked_count(_thin(loose, MAX_POINTS)), name
    raise RouteError("в KML нет ни линии маршрута, ни точек")


# ---------------------------------------------------------------- геометрия
EARTH_R_M = 6371008.8          # средний радиус Земли (IUGG)
SAMPLE_STEP_KM = 10.0          # разрешение глобальных моделей open-meteo — 9–11 км;
                               # точки чаще сетки дают ложную детализацию
MAX_SAMPLES = 50               # потолок числа погодных сэмплов
SITE_MATCH_KM = 2.0            # радиус сопоставления точки с сохранённым стартом


def haversine(a, b):
    """(расстояние в метрах, начальный пеленг в градусах) между двумя точками."""
    f1, f2 = math.radians(a.lat), math.radians(b.lat)
    df = f2 - f1
    dl = math.radians(b.lon - a.lon)
    h = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    dist = 2 * EARTH_R_M * math.asin(min(1.0, math.sqrt(h)))
    y = math.sin(dl) * math.cos(f2)
    x = math.cos(f1) * math.sin(f2) - math.sin(f1) * math.cos(f2) * math.cos(dl)
    return dist, (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


@dataclass
class Sample:
    """Точка, в которой запрашивается погода. Поля после `track_bearing_deg`
    дозаполняются последующими шагами конвейера."""
    km: float
    lat: float
    lon: float
    name: str | None = None
    role: str = "enroute"              # takeoff | enroute | goal
    is_turnpoint: bool = False
    leg_length_km: float = 0.0         # доля маршрута, которую представляет сэмпл
    track_bearing_deg: float = 0.0
    terrain_m: float | None = None
    terrain_point_m: float | None = None
    is_terrain_peak: bool = False
    cloud_base_m: float | None = None
    working_band_m: float | None = None
    wind_kmh: float | None = None
    wind_dir_deg: float | None = None
    wind_along_kmh: float | None = None
    wind_cross_kmh: float | None = None
    eta_h: float | None = None
    eta_fixed_h: float | None = None
    gs_kmh: float | None = None
    crab_limited: bool = False
    window: dict | None = None
    time_margin_min: float | None = None
    w_star_ms: float | None = None
    site_match: str | None = None
    site_aspect_deg: float | None = None
    assessment: object | None = None       # criteria.HourAssessment, ставится спекой 2
    storm_ahead: dict | None = None
    weather: dict = field(default_factory=dict)


def total_km(points):
    """Длина ломаной по точкам в километрах."""
    return sum(haversine(a, b)[0] for a, b in zip(points, points[1:])) / 1000.0


def _lerp_point(a, b, f):
    """Точка на доле f отрезка. Линейно по широте и долготе: на плече до 100 км
    отклонение от дуги большого круга меньше 100 м, то есть на порядок меньше
    шага погодной сетки."""
    return Point(a.lat + (b.lat - a.lat) * f, a.lon + (b.lon - a.lon) * f)


def _set_leg_lengths(samples):
    """Каждому сэмплу — половина расстояния до соседа слева и справа; концам
    только их половина. Сумма при этом ровно равна длине маршрута, и её можно
    использовать как вес при усреднении по маршруту (спека 2)."""
    for i, s in enumerate(samples):
        left = (s.km - samples[i - 1].km) / 2 if i > 0 else 0.0
        right = (samples[i + 1].km - s.km) / 2 if i < len(samples) - 1 else 0.0
        s.leg_length_km = left + right


def resample(points, step_km=SAMPLE_STEP_KM, max_samples=MAX_SAMPLES):
    """Точки маршрута → погодные сэмплы. Возвращает (сэмплы, фактический шаг).

    Поворотные точки включаются всегда, даже если их одних уже `max_samples`;
    промежуточные добираются только до потолка. Шаг считается один раз, а не
    подбирается циклом, — так результат детерминирован.
    """
    legs = []
    for a, b in zip(points, points[1:]):
        d, brg = haversine(a, b)
        legs.append((a, b, d / 1000.0, brg))
    total_km = sum(leg[2] for leg in legs)
    # Свободных мест под промежуточные точки может не остаться вовсе — тогда шаг
    # бесконечен и добора не будет, а наружу уйдёт фактическое среднее расстояние
    # между сэмплами.
    free = max_samples - len(points)
    step = max(step_km, total_km / (free + 1)) if free > 0 else math.inf

    samples, km = [], 0.0
    for a, b, length, brg in legs:
        samples.append(Sample(km=km, lat=a.lat, lon=a.lon, name=a.name,
                              is_turnpoint=True, track_bearing_deg=brg))
        # Число интервалов — БЛИЖАЙШЕЕ целое, а не округление вверх: плечо ровно
        # в восемь шагов длиннее восьми шагов на доли метра, и ceil дал бы
        # девятый интервал на ровном месте.
        n_inner = 0 if math.isinf(step) else max(1, round(length / step)) - 1
        for k in range(1, n_inner + 1):
            f = k / (n_inner + 1)
            p = _lerp_point(a, b, f)
            samples.append(Sample(km=km + length * f, lat=p.lat, lon=p.lon,
                                  track_bearing_deg=brg))
        km += length
    last = points[-1]
    samples.append(Sample(km=km, lat=last.lat, lon=last.lon, name=last.name,
                          is_turnpoint=True,
                          track_bearing_deg=legs[-1][3] if legs else 0.0))

    samples[0].role = "takeoff"
    samples[-1].role = "goal"
    _set_leg_lengths(samples)
    if math.isinf(step):
        step = total_km / (len(samples) - 1) if len(samples) > 1 else total_km
    return samples, step


def reverse_samples(samples):
    """Тот же маршрут в обратную сторону: те же координаты, новый километраж и пеленги.

    Второй ресэмплинг намеренно не делается — он мог бы дать другой набор точек, и
    сравнивать «туда» с «обратно» было бы не с чем. Погодные данные привязаны к
    координатам, поэтому вызывающий переиспользует их, просто развернув список.
    Исходные сэмплы не меняются: возвращаются копии.
    """
    total = samples[-1].km
    out = [replace(s, km=total - s.km) for s in reversed(samples)]
    for i, s in enumerate(out):
        a, b = (s, out[i + 1]) if i + 1 < len(out) else (out[i - 1], s)
        s.track_bearing_deg = haversine(Point(a.lat, a.lon), Point(b.lat, b.lon))[1]
        s.role = "enroute"
    out[0].role, out[-1].role = "takeoff", "goal"
    _set_leg_lengths(out)
    return out


# ---------------------------------------------------------------- рельеф
TERRAIN_STEP_KM = 1.0          # шаг рельефной сетки для маршрутов от 50 км
TERRAIN_STEP_SHORT_KM = 0.5    # для маршрутов короче — вдвое чаще
TERRAIN_SHORT_KM = 50.0
PEAK_WINDOW_KM = 5.0           # окно поиска локального максимума рельефа
PEAK_PROMINENCE_M = 100.0      # без этого порога любая точка ровного плато —
                               # формально максимум своего окна, то есть «вершина»


def terrain_step_for(total_km):
    return TERRAIN_STEP_SHORT_KM if total_km < TERRAIN_SHORT_KM else TERRAIN_STEP_KM


def terrain_grid(points, total_km):
    """Отдельная, более частая сетка для рельефа: [(км, широта, долгота), ...].

    Она гуще погодной намеренно: погоду частить бессмысленно (сетка модели 9–11 км),
    а рельеф между погодными точками меняется на километр и решает вопрос перехода.
    """
    step = terrain_step_for(total_km)
    out, km = [], 0.0
    for a, b in zip(points, points[1:]):
        length = haversine(a, b)[0] / 1000.0
        n = max(1, int(round(length / step)))
        for k in range(n):
            p = _lerp_point(a, b, k / n)
            out.append((km + length * k / n, p.lat, p.lon))
        km += length
    out.append((km, points[-1].lat, points[-1].lon))
    return out


def attach_terrain(samples, grid, elevations, step_km):
    """Проставить сэмплам высоты. `elevations` — None, если рельеф не получен.

    `terrain_m` — МАКСИМУМ по участку сэмпла, а не высота под точкой: вопрос
    пилота на переходе решает гребень, а не долина, случайно оказавшаяся под
    точкой сетки. Высота под точкой остаётся справочной в `terrain_point_m`.
    """
    if not elevations or not grid:
        return
    half = step_km / 2.0
    for s in samples:
        near = [e for (km, _, _), e in zip(grid, elevations) if abs(km - s.km) <= half]
        s.terrain_m = max(near) if near else None
        closest = min(range(len(grid)), key=lambda i: abs(grid[i][0] - s.km))
        s.terrain_point_m = elevations[closest]
        window = [e for (km, _, _), e in zip(grid, elevations)
                  if abs(km - s.km) <= PEAK_WINDOW_KM]
        s.is_terrain_peak = (bool(window)
                             and s.terrain_point_m >= max(window)
                             and max(window) - min(window) >= PEAK_PROMINENCE_M)


# ---------------------------------------------------------------- маршрутные величины
MIN_WORKING_ALT_AGL = criteria.MIN_WORKING_ALT_AGL  # пороги живут в criteria.py
MS_TO_KMH = 3.6


def ms_to_kmh(v):
    return None if v is None else v * MS_TO_KMH


def wind_components(speed, dir_from_deg, track_bearing_deg):
    """Составляющие ветра вдоль и поперёк курса.

    θ — направление, ОТКУДА дует; φ — пеленг курса, КУДА летим.
        wind_along = −V·cos(θ − φ)   > 0 попутный,   < 0 встречный
        wind_cross = −V·sin(θ − φ)   > 0 сносит вправо от трека
    Проверка: ветер с запада (θ=270), курс на восток (φ=90) → θ−φ=180,
    cos=−1, along=+V, то есть попутный.
    """
    if speed is None or dir_from_deg is None:
        return None, None
    d = math.radians(dir_from_deg - track_bearing_deg)
    return -speed * math.cos(d), -speed * math.sin(d)


def cloud_base_m(terrain_m, t2m, dew2m):
    """База термических кучевых над уровнем моря.

    Коэффициент — `criteria.LCL_M_PER_C`, второй копии числа в репозитории нет.
    Формула неприменима при слоистой облачности; на маршруте это встречается
    чаще, чем над одним стартом, потому что маршрут пересекает разные массы.
    """
    if terrain_m is None or t2m is None or dew2m is None:
        return None
    return terrain_m + criteria.LCL_M_PER_C * (t2m - dew2m)


def working_band_m(cloud_base, terrain_m):
    """Высота между безопасной высотой над рельефом и базой облаков."""
    if cloud_base is None or terrain_m is None:
        return None
    return cloud_base - (terrain_m + MIN_WORKING_ALT_AGL)


# ---------------------------------------------------------------- интерполяция
def _bracket(series, hour):
    """(значение часа, значение следующего часа, доля) либо None вне ряда."""
    if series is None or hour is None or hour < 0:
        return None
    i = int(math.floor(hour))
    if i >= len(series):
        return None
    nxt = series[i + 1] if i + 1 < len(series) else series[i]
    return series[i], nxt, hour - i


def interp(series, hour):
    """Линейная интерполяция непрерывной величины между целыми часами."""
    br = _bracket(series, hour)
    if br is None:
        return None
    a, b, f = br
    if a is None:
        return None
    if b is None or f == 0:
        return a
    return a + f * (b - a)


def interp_wind(speeds, dirs, hour):
    """Ветер на дробный час — ТОЛЬКО через u/v.

    Линейная интерполяция самих углов на переходе через 0°/360° даёт ошибку в
    сотни градусов: между 350° и 10° она выдаёт 180°, то есть ровно
    противоположное направление.
    """
    bs, bd = _bracket(speeds, hour), _bracket(dirs, hour)
    if bs is None or bd is None:
        return None, None
    (s1, s2, f), (d1, d2, _) = bs, bd
    if s1 is None or d1 is None:
        return None, None
    if s2 is None or d2 is None:
        s2, d2 = s1, d1
    u1, v1 = engine._uv(s1, d1)
    u2, v2 = engine._uv(s2, d2)
    u, v = u1 + f * (u2 - u1), v1 + f * (v2 - v1)
    return math.hypot(u, v), (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0


def worst_of_hours(series, hour):
    """Худшее из двух соседних часов, без интерполяции.

    Осадки за час — накопление, а не мгновенное значение; интерполяция
    размазывает ливень в морось ровно там, где это опаснее всего.
    """
    br = _bracket(series, hour)
    if br is None:
        return None
    vals = [v for v in br[:2] if v is not None]
    return max(vals) if vals else None


# ---------------------------------------------------------------- термическое окно
BLH_WORKING_M = 500            # ниже пограничного слоя термичка не рабочая
RADIATION_WORKING_WM2 = 150    # ниже радиации склон не успевает греть


def thermal_window(date_iso, lat, sunrise, sunset, blh, radiation):
    """Окно термической активности в точке маршрута — ПЕРЕСЕЧЕНИЕ двух определений.

    Геометрия солнца даёт астрономическую рамку (экспозиция не передаётся: в
    воздухе склона нет, и `sun_hours` в этом случае опирается на высоту солнца).
    Пороги пограничного слоя и радиации внутри рамки отрезают часы, когда
    конвекция фактически не работает. По отдельности каждое определение врёт в
    свою сторону: солнечное растягивает окно на весь световой день, пороговое
    способно открыть окно в шесть утра.
    """
    if not blh or not radiation:
        return None
    lo, hi = engine.hour_of(sunrise), engine.hour_of(sunset)
    _rows, sun = engine.sun_hours(date_iso, lat, sunrise, sunset,
                                  list(range(lo, hi + 1)), None)
    if not sun:
        return None
    working = [h for h in range(sun["start_hour"], sun["end_hour"] + 1)
               if h < len(blh) and h < len(radiation)
               and (blh[h] or 0) > BLH_WORKING_M
               and (radiation[h] or 0) > RADIATION_WORKING_WM2]
    if not working:
        return None
    return {"start_hour": working[0], "end_hour": working[-1]}


def time_margin_min(window, eta_h):
    """Минуты до конца окна. Конец — граница последнего рабочего часа."""
    if not window or eta_h is None:
        return None
    return (window["end_hour"] + 1 - eta_h) * 60.0


# ---------------------------------------------------------------- время прибытия
MIN_GROUND_SPEED_KMH = criteria.MIN_GROUND_SPEED_KMH  # пороги живут в criteria.py
ETA_WARN_MIN = 20              # расхождение времён прилёта, с которого предупреждаем


def ground_speed(va_kmh, along_kmh, cross_kmh):
    """Путевая скорость вдоль трека с учётом крабинга → (скорость, упёрлись ли).

    Боковой ветер съедает скорость дважды: часть воздушной скорости уходит на
    компенсацию сноса (угол WCA), и только косинус этого угла работает вперёд.
    """
    along = along_kmh or 0.0
    cross = cross_kmh or 0.0
    ratio = cross / va_kmh if va_kmh else 0.0
    limited = abs(ratio) >= 1.0
    wca = math.asin(max(-1.0, min(1.0, ratio)))
    gs = va_kmh * math.cos(wca) + along
    return max(gs, MIN_GROUND_SPEED_KMH), limited


def fixed_eta(samples, speed_kmh, departure_h):
    """Время прибытия по фиксированной скорости — справочное."""
    for s in samples:
        s.eta_fixed_h = departure_h + s.km / speed_kmh


def march(samples, speed_kmh, wind_for_segment, departure_h):
    """Время прибытия с учётом ветра — одним проходом вперёд.

    `wind_for_segment(i, hour)` возвращает (вдоль, поперёк) в км/ч для сегмента
    между сэмплами i и i+1, оценённые на переданный час. Круговой зависимости
    нет: время каждой точки опирается только на уже посчитанные, итерация до
    сходимости не нужна. Побочный эффект: при резком усилении ветра ВНУТРИ
    сегмента время слегка занижается.
    """
    samples[0].eta_h = departure_h
    samples[0].gs_kmh = speed_kmh
    for i in range(len(samples) - 1):
        along, cross = wind_for_segment(i, samples[i].eta_h)
        gs, limited = ground_speed(speed_kmh, along, cross)
        leg = samples[i + 1].km - samples[i].km
        samples[i + 1].eta_h = samples[i].eta_h + leg / gs
        samples[i + 1].gs_kmh = gs
        samples[i + 1].crab_limited = limited


# ---------------------------------------------------------------- карточка
CARD_WIDTH = 32                # шире Telegram переносит моноширинный блок на телефоне
CAPE_WATCH = 800.0             # с этого значения гроза стоит отдельной строки
LI_WATCH = -2.0


# ---------------------------------------------------------------- характерные точки
KEY_POINT_LIMIT = 8            # длиннее ряд кнопок в Telegram не читается
_KM_EPS = 0.05                 # километраж округлён до десятой, сравнивать точно нельзя

# Вид точки → метка, в порядке убывания важности. Точка, подходящая под несколько
# видов, показывается ОДИН раз — с меткой самого важного из них.
_KEY_MARKS = (("blocked", "⛔"), ("bottleneck", "⚠"), ("takeoff", "△"),
              ("goal", "⚑"), ("turnpoint", "◆"), ("peak", "▲"))
# Кого выбрасывать первым, когда точек больше лимита: с хвоста этого списка.
_KEY_KEEP_ORDER = ("takeoff", "goal", "blocked", "bottleneck", "turnpoint", "peak")


def _kinds_of(p, blocked, bottleneck):
    kinds = set()
    if blocked is not None and abs(p["km"] - blocked) < _KM_EPS:
        kinds.add("blocked")
    if bottleneck is not None and abs(p["km"] - bottleneck) < _KM_EPS:
        kinds.add("bottleneck")
    if p.get("role") in ("takeoff", "goal"):
        kinds.add(p["role"])
    elif p.get("is_turnpoint"):
        kinds.add("turnpoint")
    if p.get("is_terrain_peak"):
        kinds.add("peak")
    return kinds


def key_points(profile):
    """Точки, ради которых стоит открывать подробности: старт, финиш, обрыв,
    узкое место, поворотные и вершины рельефа.

    Не больше KEY_POINT_LIMIT: расчётных точек бывает полсотни, и вываливать их
    все кнопками — значит не помочь выбрать, а переложить выбор на пилота.
    """
    pts = profile.get("points") or []
    v = profile.get("verdict") or {}
    blocked = v.get("blocked_at_km")
    bottleneck = (v.get("bottleneck") or {}).get("km")
    found = []
    for p in pts:
        kinds = _kinds_of(p, blocked, bottleneck)
        if kinds:
            mark = next(m for k, m in _KEY_MARKS if k in kinds)
            found.append({"km": p["km"], "mark": mark, "kinds": kinds})
    if len(found) <= KEY_POINT_LIMIT:
        return found
    rank = {k: i for i, k in enumerate(_KEY_KEEP_ORDER)}
    keep = sorted(found, key=lambda f: min(rank[k] for k in f["kinds"]))[:KEY_POINT_LIMIT]
    return sorted(keep, key=lambda f: f["km"])


def _signed(v):
    """Число со знаком минус-тире, без выравнивания: «+330», «−25»."""
    return "н/д" if v is None else f"{'−' if v < 0 else '+'}{abs(v):.0f}"


def plural(n, one, few, many):
    """«1 точка», «3 точки», «5 точек» — иначе карточка читается как машинный вывод."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


FEASIBILITY_RU = {
    "completable": "маршрут проходится",
    "blocked_at_km": "маршрут обрывается",
    "too_slow": "не успеваешь до закрытия окна",
    "unknown": "данных не хватает для вердикта",
}


def _wrap(text, indent="   "):
    """Разбить строку по ширине карточки, каждую часть с отступом."""
    lines, cur = [], ""
    for w in text.split():
        candidate = f"{cur} {w}" if cur else f"{indent}{w}"
        if len(candidate) > CARD_WIDTH and cur:
            lines.append(cur)
            cur = f"{indent}{w}"
        else:
            cur = candidate
    if cur:
        lines.append(cur)
    return lines


def _rows(points):
    """Колонки: километр, время, МОДУЛЬ составляющей вдоль курса (знак несёт
    стрелка), абсолютный ветер на рабочей высоте и балл точки.

    Эмодзи категории в таблицу не идёт: в моноширинном блоке он вдвое шире цифр
    и колонки разъезжаются (то же отмечено у engine.hourly_strip). Категория
    живёт на строке вердикта, где выравнивание не нужно.
    """
    scored = any(p.get("score") is not None for p in points)
    last = "балл" if scored else "поток"
    out = [f" км  время  вдоль  ветер  {last}"]
    for p in points:
        along = p.get("wind_along_kmh")
        arrow = " " if along is None else ("→" if along >= 0 else "←")
        along_txt = " н/д" if along is None else f"{abs(along):3.0f}"
        deg, spd = p.get("wind_working_alt_dir"), p.get("wind_working_alt_kmh")
        wind = "   н/д" if deg is None or spd is None else f"{engine.card(deg):>3} {spd:2.0f}"
        if scored:
            tail = "  —" if p.get("score") is None else f"{p['score']:3.0f}"
        else:
            tail = "  —" if p.get("w_star_ms") is None else f"{p['w_star_ms']:3.1f}"
        eta = p["eta"] or "  —  "      # None = расчёт оборвался на границе суток
        out.append(f"{p['km']:3.0f}  {eta}  {arrow}{along_txt}  {wind}  {tail}")
    return out


def _verdict_lines(v):
    """Блок вердикта. Когда маршрут не проходится, первой идёт причина и километр:
    балл в этом случае вторичен."""
    if not v:
        return []
    out = []
    if v["feasibility"] == "blocked_at_km":
        out.append(f"⛔ Обрывается на {v['blocked_at_km']:.0f} км:")
        out += _wrap(v["blocked_reason"] or "причина не определена")
    else:
        out.append(f"{v['emoji']} {v['label'].capitalize()} · {v['score']:.0f}")
        out.append(f"   {FEASIBILITY_RU[v['feasibility']]}")
    # «Лётно до N км» осмысленно только когда маршрут где-то обрывается: иначе
    # это повтор общей длины, ради которого пилот листает карточку.
    if v.get("blocked_at_km") is not None and v.get("flyable_until_km") is not None:
        out.append(f"   Лётно до {v['flyable_until_km']:.0f} км")
    b = v.get("bottleneck")
    if b:
        out.append(f"   Узкое место: {b['score']} на {b['km']:.0f} км")
    out.append("")
    return out


def _eta_gap_min(points):
    """Расхождение времён прилёта в минутах; 0, если сравнивать не с чем."""
    last = points[-1] if points else {}
    if not last.get("eta") or not last.get("eta_fixed"):
        return 0

    def mins(hhmm):
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    return abs(mins(last["eta"]) - mins(last["eta_fixed"]))


# ---------------------------------------------------------------- карточка точки
ROLE_RU = {"takeoff": "старт", "enroute": "маршрут", "goal": "финиш"}
SUBS_SHOWN = 3

# Категория → (эмодзи, название). Берётся из criteria.CATEGORIES, чтобы своей
# копии названий здесь не заводилось.
_CAT = {key: (emoji, label) for key, _lo, emoji, label in criteria.CATEGORIES}


def _pair(label, value):
    """Строка «подпись … значение» по ширине карточки.

    Слишком длинная подпись обрезается: перенести её на вторую строку значит
    сломать колонку значений, ради которой карточка и читается сверху вниз.
    """
    room = CARD_WIDTH - len(value) - 1
    if len(label) > room:
        label = label[:max(0, room - 1)] + "…"
    return label + " " * max(1, CARD_WIDTH - len(label) - len(value)) + value


def _qty(v, unit, fmt="{:.0f}"):
    return "н/д" if v is None else (fmt.format(v) + " " + unit).replace(".", ",")


def _point_by_km(profile, km):
    return next((p for p in profile.get("points") or []
                 if abs(p["km"] - km) < _KM_EPS), None)


def _worst_subs(p, limit=SUBS_SHOWN):
    """Самые низкие субоценки с русскими названиями параметров."""
    subs = p.get("subs") or {}
    ranked = sorted((v, k) for k, v in subs.items() if v is not None)
    out = []
    for value, key in ranked[:limit]:
        param = criteria.PARAMS.get(key)
        out.append((param.label if param else key, value))
    return out


def render_point_card(profile, km):
    """Подробности одной точки маршрута. None, если такой точки нет.

    Высоты здесь есть намеренно. Из таблицы маршрута их убрали потому, что там
    их было десять и они мешали читать погоду; сюда пилот приходит сам, чтобы
    разобраться в диапазоне и запасе, — без чисел ответить нечем.
    """
    p = _point_by_km(profile, km)
    if p is None:
        return None
    w = p.get("weather") or {}
    out = [f"📍 {p['km']:.0f} км · {p.get('eta') or '—'} · "
           f"{ROLE_RU.get(p.get('role'), p.get('role') or '')}",
           "─" * CARD_WIDTH]

    if p.get("score") is not None:
        emoji, label = _CAT.get(p.get("category"), ("", p.get("category") or ""))
        out.append(f"{emoji} {p['score']:.0f} {label}")
    if p.get("limiting"):
        out.append("Ограничивает:")
        out += _wrap(p["limiting"])
    for veto in p.get("vetoes") or []:
        out.append("⛔")
        out += _wrap(veto)
    out.append("")

    deg, spd = p.get("wind_working_alt_dir"), p.get("wind_working_alt_kmh")
    alt = p.get("thermal_ceiling_m")
    out.append(_pair("Ветер" if alt is None else f"Ветер {alt:.0f} м",
                     "н/д" if deg is None or spd is None
                     else f"{spd:.0f} км/ч {engine.card(deg)}"))
    along, cross = p.get("wind_along_kmh"), p.get("wind_cross_kmh")
    out.append(_pair("  вдоль курса",
                     "н/д" if along is None
                     else f"{abs(along):.0f} км/ч {'→' if along >= 0 else '←'}"))
    out.append(_pair("  поперёк",
                     "н/д" if cross is None
                     else f"{abs(cross):.0f} км/ч {'→' if cross >= 0 else '←'}"))
    # У точки в воздухе наземный ветер в оценке не участвует: печатать его —
    # предлагать пилоту решение по числу, которое ни на что не влияет.
    if p.get("role") in ("takeoff", "goal"):
        ground, gust = w.get("wind_speed_10m"), w.get("wind_gusts_10m")
        out.append(_pair("Земля", "н/д" if ground is None else
                         f"{ms_to_kmh(ground):.0f}"
                         + ("" if gust is None else f"/{ms_to_kmh(gust):.0f}")
                         + " км/ч"))
    out.append(_pair("Потоки", _qty(p.get("w_star_ms"), "м/с", "{:.1f}")))
    out.append(_pair("Скорость по земле",
                     _qty(p.get("effective_ground_speed_kmh"), "км/ч")))
    out.append(_pair("База", _qty(p.get("cloud_base_m"), "м")))
    out.append(_pair("Рельеф", _qty(p.get("terrain_m"), "м")
                     + (" ▲" if p.get("is_terrain_peak") else "")))
    out.append(_pair("Коридор", _qty(p.get("working_band_m"), "м")))
    out.append(_pair("Запас времени", _qty(p.get("time_margin_min"), "мин")))
    out.append("")

    out.append(f"CAPE {w.get('cape') or 0:.0f} · LI {w.get('lifted_index') or 0:.1f}"
               f" · CIN {w.get('convective_inhibition') or 0:.0f}".replace(".", ","))
    out.append(f"Облачность {w.get('cloud_cover_low') or 0:.0f}/"
               f"{w.get('cloud_cover_mid') or 0:.0f} · дождь "
               f"{w.get('precipitation') or 0:.1f}".replace(".", ","))
    vis = w.get("visibility")
    out.append(_pair("Видимость", "н/д" if vis is None else f"{vis / 1000.0:.0f} км"))

    worst = _worst_subs(p)
    if worst:
        out += ["", "Что тянет вниз:"]
        for label, value in worst:
            out.append(_pair(f"  {label}", f"{value:.0f}"))
    return "\n".join(out)


def render_card(profile):
    """Текстовая карточка маршрута. Только погода и время — высот здесь нет."""
    r, pts = profile["route"], profile["points"]
    n = len(pts)
    word = plural(n, "точка", "точки", "точек")
    head = [f"🗺 {r['name']}",
            f"{r['total_km']:.0f} км · {n} {word} · {engine.fmt_date(r['date'])}",
            ""]
    if pts and pts[-1]["eta"]:
        head.append(f"⏱ Вылет {r['departure']} → прилёт ~{pts[-1]['eta']}")
    else:
        head.append(f"⏱ Вылет {r['departure']}")
        head.append("   Прилёт за пределами суток")
    head.append("")
    head += _verdict_lines(profile.get("verdict"))
    tail = [""]

    margins = [p.get("time_margin_min") for p in pts if p.get("time_margin_min") is not None]
    if margins:
        tail.append("⏳ Запас окна, мин:")
        tail.append(f"   старт {_signed(margins[0])} · финиш {_signed(margins[-1])}")

    wet = [p for p in pts if (p["weather"].get("precipitation") or 0) > 0]
    if wet:
        mm = max(p["weather"]["precipitation"] for p in wet)
        tail.append(f"🌧 {wet[0]['km']:.0f}–{wet[-1]['km']:.0f} км: осадки "
                    f"{mm:.1f} мм".replace(".", ","))

    storm = [p for p in pts
             if (p["weather"].get("cape") or 0) >= CAPE_WATCH
             or (p["weather"].get("lifted_index") is not None
                 and p["weather"]["lifted_index"] <= LI_WATCH)]
    if storm:
        p = storm[0]
        tail.append(f"⚡ {p['km']:.0f} км: CAPE {p['weather']['cape']:.0f}, "
                    f"LI {p['weather']['lifted_index']:.1f}".replace(".", ","))

    if _eta_gap_min(pts) > ETA_WARN_MIN:
        tail.append("⚠️ Без учёта ветра прилёт был бы")
        tail.append(f"   в {pts[-1]['eta_fixed']} — раньше на "
                    f"{_eta_gap_min(pts):.0f} мин")

    best, scan = profile.get("best_departure"), profile.get("departure_scan") or []
    if best:
        tail.append(f"⏱ Лучший вылет {best['departure']} · {best['score']:.0f}")
        # Не больше двух альтернатив: третья не влезает в ширину карточки.
        alts = [e for e in scan if e["departure"] != best["departure"]][:2]
        if alts:
            tail.append("   " + " · ".join(f"{e['departure']}→{e['score']:.0f}"
                                           for e in alts))
    elif scan:
        # Лучший из непроходимых не показывается: это предложение выбрать,
        # каким способом не долететь.
        tail.append("⏱ Ни одно время вылета не даёт")
        tail.append("   проходимый маршрут")

    storm = next((p for p in pts if p.get("storm_ahead")), None)
    if storm:
        s = storm["storm_ahead"]
        tail.append(f"⚡ {storm['km']:.0f} км: гроза впереди на")
        tail.append(f"   {s['km']:.0f}-м км, подлёт {s['eta']}")

    rev, v = profile.get("reverse"), profile.get("verdict")
    if rev and rev.get("better") and v:
        tail.append(f"↩️ Обратный лучше: {rev['score']:.0f} "
                    f"против {v['score']:.0f}")

    tail.extend(profile.get("notes") or [])
    cnt = r["sample_count"]
    tail.append(f"📊 {cnt} {plural(cnt, 'точка', 'точки', 'точек')} · "
                f"шаг {r['sample_step_km']:.0f} км · {r['model'].split(' ')[0]}")
    return "\n".join(head + _rows(pts) + tail)

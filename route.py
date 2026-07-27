"""Маршрут: разбор ввода, геометрия, время прибытия, маршрутные величины.

Модуль намеренно чистый — ни сети, ни aiogram, ни глобального состояния.
Всё, что здесь считается, проверяемо офлайн: геометрия и знаки ветра — ровно то
место, где ошибка выглядит правдоподобно и не ловится глазами.
"""
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

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
    weather: dict = field(default_factory=dict)


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
MIN_WORKING_ALT_AGL = 300      # ниже пилот не идёт на переход, а ищет площадку
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

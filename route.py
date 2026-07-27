"""Маршрут: разбор ввода, геометрия, время прибытия, маршрутные величины.

Модуль намеренно чистый — ни сети, ни aiogram, ни глобального состояния.
Всё, что здесь считается, проверяемо офлайн: геометрия и знаки ветра — ровно то
место, где ошибка выглядит правдоподобно и не ловится глазами.
"""
import math
import re
import xml.etree.ElementTree as ET

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

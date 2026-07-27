"""Маршрут: разбор ввода, геометрия, время прибытия, маршрутные величины.

Модуль намеренно чистый — ни сети, ни aiogram, ни глобального состояния.
Всё, что здесь считается, проверяемо офлайн: геометрия и знаки ветра — ровно то
место, где ошибка выглядит правдоподобно и не ловится глазами.
"""
import math
import re

MIN_POINTS = 2
MAX_POINTS = 50           # потолок числа точек на входе


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

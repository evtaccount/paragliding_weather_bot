"""Сохранённые маршруты — один файл на бота, как настройки и список стартов.

Хранится ТОЛЬКО геометрия. Погода всегда считается заново, поэтому устаревать
здесь нечему: сохранённый маршрут — это набор координат, а не прогноз.
"""
import datetime as dt
import json
import os

import engine
import route

ROUTES_FILE = (os.environ.get("ROUTES_FILE")
               or os.path.join(os.path.dirname(engine.SITES) or ".", "routes.json"))
MAX_ROUTES = 20


def list_all():
    """Все маршруты; пустой словарь при отсутствии файла, порче или чужой структуре."""
    try:
        with open(ROUTES_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items()
            if isinstance(v, dict) and isinstance(v.get("points"), list)}


def _save(data):
    with open(ROUTES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def save(name, points):
    """Сохранить точки под именем. ValueError при переполнении и слишком длинном маршруте."""
    if len(points) > route.MAX_POINTS:
        raise ValueError(f"слишком много точек: {len(points)}, "
                         f"максимум {route.MAX_POINTS}")
    data = list_all()
    if name not in data and len(data) >= MAX_ROUTES:
        raise ValueError(f"сохранено уже {MAX_ROUTES} маршрутов — "
                         "удали ненужный через /delroute")
    data[name] = {"points": [[p.lat, p.lon, p.name] for p in points],
                  "saved": dt.date.today().isoformat()}
    _save(data)


def get(name):
    """Точки маршрута или None. Битая запись читается как None, а не роняет бота."""
    entry = list_all().get(name)
    if not entry:
        return None
    out = []
    for item in entry["points"]:
        try:
            lat, lon = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError, KeyError):
            return None
        out.append(route.Point(lat, lon, item[2] if len(item) > 2 else None))
    return out if len(out) >= route.MIN_POINTS else None


def delete(name):
    """True, если удалили; False, если такого маршрута не было."""
    data = list_all()
    if name not in data:
        return False
    del data[name]
    _save(data)
    return True

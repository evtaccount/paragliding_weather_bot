"""Сохранённые маршруты: разбор сырых строк и устойчивость к порче записи.

Сам круг «сохранить → перечислить → удалить» проверяет tests/test_store.py —
здесь только то, что живёт вокруг хранилища: превращение строк в точки и
поведение на записи, которую невозможно прочитать.
"""
import json

import route
import store
from conftest import TEST_USER_ID


def test_points_from_rows_builds_points():
    pts = route.points_from_rows([[42.4, 44.4, "старт"], [42.2, 44.6, None]])
    assert [p.lat for p in pts] == [42.4, 42.2]
    assert pts[0].name == "старт" and pts[1].name is None


def test_points_from_rows_rejects_corrupt():
    """Битая запись читается как None, а не роняет бота."""
    assert route.points_from_rows([["нет", 44.4, None], [42.2, 44.6, None]]) is None
    assert route.points_from_rows([[42.4], [42.2, 44.6, None]]) is None


def test_points_from_rows_rejects_too_few():
    """Маршрут из одной точки посчитать нельзя, значит и отдавать его нечего."""
    assert route.points_from_rows([[42.4, 44.4, None]]) is None


def _write_raw(name, points_json):
    with store.connect() as conn:
        conn.execute("INSERT INTO routes (user_id, name, points, saved_at)"
                     " VALUES (?,?,?,?)", (TEST_USER_ID, name, points_json, "2026-07-29"))


def test_a_corrupt_entry_is_skipped_not_crashing():
    _write_raw("Гудаури", "{это не json")
    assert store.routes_list(TEST_USER_ID) == {}
    assert store.route_rows(TEST_USER_ID, "Гудаури") is None


def test_a_foreign_structure_is_ignored():
    _write_raw("Гудаури", json.dumps({"points": "строка вместо списка"}))
    assert store.routes_list(TEST_USER_ID) == {}
    assert store.route_rows(TEST_USER_ID, "Гудаури") is None

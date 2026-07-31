"""Сохранённые маршруты: превращение сырых строк хранилища в точки.

Сам круг «сохранить → перечислить → удалить», потолок и пропуск битой записи
проверяет tests/test_store.py — здесь только разбор.
"""
import route


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

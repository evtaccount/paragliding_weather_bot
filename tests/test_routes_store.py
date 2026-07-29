"""Хранилище сохранённых маршрутов: файл рядом с sites.json."""
import json
import os

import pytest

import route
import routes

PTS = [route.Point(42.0, 44.0, "старт"),
       route.Point(42.0 + 40.0 / 111.195, 44.0, "финиш")]


def test_empty_when_there_is_no_file():
    assert routes.list_all() == {}


def test_save_then_get_round_trips_coordinates_and_names():
    routes.save("Гудаури", PTS)
    got = routes.get("Гудаури")
    assert [(p.lat, p.lon, p.name) for p in got] == [(p.lat, p.lon, p.name) for p in PTS]


def test_saved_entry_records_the_date():
    routes.save("Гудаури", PTS)
    assert routes.list_all()["Гудаури"]["saved"]


def test_get_of_an_unknown_name_is_none():
    assert routes.get("нет такого") is None


def test_delete_reports_whether_it_deleted():
    routes.save("Гудаури", PTS)
    assert routes.delete("Гудаури") is True
    assert routes.delete("Гудаури") is False
    assert routes.list_all() == {}


def test_saving_the_same_name_overwrites():
    routes.save("Гудаури", PTS)
    routes.save("Гудаури", PTS + [route.Point(41.9, 44.1, "ещё")])
    assert len(routes.get("Гудаури")) == 3
    assert len(routes.list_all()) == 1


def test_a_corrupt_file_gives_an_empty_list_not_a_crash():
    """Порча файла не должна ронять бота — как в settings.get()."""
    with open(routes.ROUTES_FILE, "w", encoding="utf-8") as f:
        f.write("{это не json")
    assert routes.list_all() == {}


def test_a_foreign_structure_is_ignored():
    with open(routes.ROUTES_FILE, "w", encoding="utf-8") as f:
        json.dump({"Гудаури": "строка вместо объекта"}, f)
    assert routes.list_all() == {}
    assert routes.get("Гудаури") is None


def test_a_broken_entry_reads_as_none():
    with open(routes.ROUTES_FILE, "w", encoding="utf-8") as f:
        json.dump({"Гудаури": {"points": [["север", "восток"]]}}, f)
    assert routes.get("Гудаури") is None


def test_an_entry_with_one_point_reads_as_none():
    """Маршрут из одной точки посчитать нельзя, значит и отдавать его нечего."""
    with open(routes.ROUTES_FILE, "w", encoding="utf-8") as f:
        json.dump({"Гудаури": {"points": [[42.0, 44.0, None]]}}, f)
    assert routes.get("Гудаури") is None


def test_the_store_has_a_ceiling():
    for i in range(routes.MAX_ROUTES):
        routes.save(f"маршрут {i}", PTS)
    with pytest.raises(ValueError, match=str(routes.MAX_ROUTES)):
        routes.save("лишний", PTS)


def test_overwriting_at_the_ceiling_still_works():
    """Потолок про число записей, а не про запрет трогать существующие."""
    for i in range(routes.MAX_ROUTES):
        routes.save(f"маршрут {i}", PTS)
    routes.save("маршрут 0", PTS)
    assert len(routes.list_all()) == routes.MAX_ROUTES


def test_too_many_points_is_refused():
    many = [route.Point(42.0 + i / 1000.0, 44.0) for i in range(route.MAX_POINTS + 1)]
    with pytest.raises(ValueError, match="точек"):
        routes.save("длинный", many)


def test_the_file_lives_next_to_sites_json():
    import engine
    assert os.path.dirname(routes.ROUTES_FILE) == os.path.dirname(engine.SITES)


def test_points_from_rows_builds_points():
    import route
    pts = route.points_from_rows([[42.4, 44.4, "старт"], [42.2, 44.6, None]])
    assert [p.lat for p in pts] == [42.4, 42.2]
    assert pts[0].name == "старт" and pts[1].name is None


def test_points_from_rows_rejects_corrupt():
    """Битая запись читается как None, а не роняет бота."""
    import route
    assert route.points_from_rows([["нет", 44.4, None], [42.2, 44.6, None]]) is None
    assert route.points_from_rows([[42.4], [42.2, 44.6, None]]) is None


def test_points_from_rows_rejects_too_few():
    import route
    assert route.points_from_rows([[42.4, 44.4, None]]) is None

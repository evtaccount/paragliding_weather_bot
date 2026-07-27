"""Разбор маршрута, присланного текстом."""
import pytest

import route


def names(pts):
    return [p.name for p in pts]


def test_plain_lines():
    pts = route.parse_text("42.4776, 44.4787, Гудаури старт\n42.2104, 44.6890, Пасанаури")
    assert [(p.lat, p.lon) for p in pts] == [(42.4776, 44.4787), (42.2104, 44.6890)]
    assert names(pts) == ["Гудаури старт", "Пасанаури"]


def test_decimal_comma():
    pts = route.parse_text("42,4776, 44,4787\n42,2104, 44,6890")
    assert (pts[0].lat, pts[0].lon) == (42.4776, 44.4787)


def test_google_maps_paste():
    pts = route.parse_text("42.4776,44.4787\n42.2104,44.6890")
    assert len(pts) == 2


def test_one_line_compact():
    pts = route.parse_text("42.4776,44.4787 42.3891,44.5512 42.2104,44.6890")
    assert len(pts) == 3
    assert (pts[1].lat, pts[1].lon) == (42.3891, 44.5512)


def test_name_with_digits_does_not_shift_coordinates():
    pts = route.parse_text("42.4776, 44.4787, Точка 3\n42.2104, 44.6890, Финиш")
    assert (pts[0].lat, pts[0].lon) == (42.4776, 44.4787)
    assert pts[0].name == "Точка 3"


def test_dms():
    pts = route.parse_text('42°28\'39"N 44°28\'43"E\n42°12\'37"N 44°41\'20"E')
    assert pts[0].lat == pytest.approx(42.4775, abs=1e-3)
    assert pts[0].lon == pytest.approx(44.4786, abs=1e-3)


def test_comments_and_blank_lines_skipped():
    pts = route.parse_text("# маршрут на завтра\n\n42.4776, 44.4787\n\n42.2104, 44.6890\n")
    assert len(pts) == 2


def test_single_point_rejected():
    with pytest.raises(route.RouteError) as e:
        route.parse_text("42.4776, 44.4787")
    assert "2" in str(e.value)


def test_too_many_points_rejected():
    body = "\n".join(f"42.{i:04d}, 44.4787" for i in range(51))
    with pytest.raises(route.RouteError):
        route.parse_text(body)


def test_bad_line_names_itself():
    with pytest.raises(route.RouteError) as e:
        route.parse_text("42.4776, 44.4787\nтут была координата")
    assert "тут была координата" in str(e.value)
    assert "2" in str(e.value)  # номер строки


def test_line_number_counts_from_the_offset():
    """Бот отрезает строку с командой, а номер должен совпадать с сообщением."""
    with pytest.raises(route.RouteError) as e:
        route.parse_text("42.4776, 44.4787\nмусор", first_line_no=2)
    assert "строка 3" in str(e.value)


def test_out_of_range_rejected():
    with pytest.raises(route.RouteError):
        route.parse_text("142.4776, 44.4787\n42.2104, 44.6890")

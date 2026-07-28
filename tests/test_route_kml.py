"""Разбор KML. Главная ловушка формата — порядок «долгота,широта»."""
import pytest

import route

LINE = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<name>Гудаури тур</name>
<Placemark><name>трек</name><LineString><coordinates>
44.4787,42.4776,2196 44.5513,42.3428,2510 44.6890,42.2104,1050
</coordinates></LineString></Placemark>
</Document></kml>"""

PINS = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>старт</name><Point><coordinates>44.4787,42.4776</coordinates></Point></Placemark>
<Placemark><name>финиш</name><Point><coordinates>44.6890,42.2104</coordinates></Point></Placemark>
</Document></kml>"""

BARE = """<?xml version="1.0"?><kml><Folder>
<coordinates>44.4787,42.4776 44.6890,42.2104</coordinates>
</Folder></kml>"""


def test_longitude_comes_first_in_kml():
    """Перепутать порядок значит молча улететь в другое полушарие."""
    pts, _name = route.parse_kml(LINE.encode())
    assert pts[0].lat == pytest.approx(42.4776)
    assert pts[0].lon == pytest.approx(44.4787)
    assert pts[-1].lat == pytest.approx(42.2104)
    assert pts[-1].lon == pytest.approx(44.6890)


def test_all_line_points_are_read():
    pts, _name = route.parse_kml(LINE.encode())
    assert len(pts) == 3


def test_altitude_in_the_third_field_is_ignored():
    """Высоту берём из DEM: в KML она бывает то над геоидом, то над эллипсоидом."""
    pts, _name = route.parse_kml(LINE.encode())
    assert pts[0].lat == pytest.approx(42.4776)
    assert pts[1].lat == pytest.approx(42.3428)


def test_document_name_wins():
    _pts, name = route.parse_kml(LINE.encode())
    assert name == "Гудаури тур"


def test_placemark_points_are_read_with_their_names():
    pts, _name = route.parse_kml(PINS.encode())
    assert [p.name for p in pts] == ["старт", "финиш"]


def test_placemark_name_is_used_when_the_document_has_none():
    _pts, name = route.parse_kml(PINS.encode())
    assert name == "старт"


def test_a_line_wins_over_scattered_points():
    both = LINE.replace("</Document>",
                        "<Placemark><Point><coordinates>1,1</coordinates>"
                        "</Point></Placemark></Document>")
    pts, _name = route.parse_kml(both.encode())
    assert len(pts) == 3
    assert all(p.lat > 40 for p in pts)


def test_bare_coordinates_are_the_last_resort():
    pts, name = route.parse_kml(BARE.encode())
    assert len(pts) == 2
    assert name is None


def test_namespaces_do_not_matter():
    ns = LINE.replace("http://www.opengis.net/kml/2.2",
                      "http://earth.google.com/kml/2.1")
    pts, _name = route.parse_kml(ns.encode())
    assert len(pts) == 3


def test_a_document_without_coordinates_is_refused():
    with pytest.raises(route.RouteError, match="нет"):
        route.parse_kml(b"<kml><Document><name>pusto</name></Document></kml>")


def test_broken_xml_is_refused():
    with pytest.raises(route.RouteError, match="разобрать"):
        route.parse_kml(b"<kml><Document>")


def test_a_single_point_is_refused():
    one = PINS.replace(
        "<Placemark><name>финиш</name><Point>"
        "<coordinates>44.6890,42.2104</coordinates></Point></Placemark>", "")
    with pytest.raises(route.RouteError, match="минимум"):
        route.parse_kml(one.encode())


def test_entity_declarations_are_refused():
    """Килобайт вложенных сущностей разворачивается в гигабайты («billion laughs»)."""
    bomb = (b'<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY a "aaaa">]>'
            b"<kml><coordinates>44,42 45,43</coordinates></kml>")
    with pytest.raises(route.RouteError, match="DOCTYPE"):
        route.parse_kml(bomb)


def test_an_oversized_file_is_refused():
    with pytest.raises(route.RouteError, match="КБ"):
        route.parse_kml(b"x" * (route.MAX_GPX_BYTES + 1))


def test_a_long_track_is_thinned_to_the_cap():
    coords = " ".join(f"{44.0 + i / 1000.0},{42.0 + i / 1000.0}" for i in range(500))
    doc = (f"<kml><Document><Placemark><LineString><coordinates>{coords}"
           "</coordinates></LineString></Placemark></Document></kml>")
    pts, _name = route.parse_kml(doc.encode())
    assert len(pts) == route.MAX_POINTS


def test_garbage_triples_are_skipped_not_fatal():
    doc = ("<kml><coordinates>44.4787,42.4776 мусор 44.6890,42.2104"
           "</coordinates></kml>")
    pts, _name = route.parse_kml(doc.encode())
    assert len(pts) == 2

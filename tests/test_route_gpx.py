"""Разбор GPX: приоритет rte → trk → wpt, прореживание трека, битые файлы."""
import pytest

import route

RTE = """<?xml version="1.0"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1"><name>Гудаури — Пасанаури</name>
<wpt lat="1.0" lon="1.0"><name>левая</name></wpt>
<rte><name>Основной</name>
<rtept lat="42.4776" lon="44.4787"><name>старт</name></rtept>
<rtept lat="42.2104" lon="44.6890"><name>финиш</name></rtept>
</rte></gpx>"""

TRK = """<?xml version="1.0"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Трек</name><trkseg>
{pts}
</trkseg></trk></gpx>"""

WPT_ONLY = """<?xml version="1.0"?>
<gpx><wpt lat="42.4776" lon="44.4787"><name>A</name></wpt>
<wpt lat="42.2104" lon="44.6890"><name>B</name></wpt></gpx>"""


def test_rte_wins_over_wpt():
    pts, name = route.parse_gpx(RTE.encode())
    assert [(p.lat, p.lon) for p in pts] == [(42.4776, 44.4787), (42.2104, 44.6890)]
    assert [p.name for p in pts] == ["старт", "финиш"]
    assert name == "Гудаури — Пасанаури"


def test_track_is_thinned_to_max_points():
    body = "\n".join(f'<trkpt lat="42.{i:04d}" lon="44.4787"/>' for i in range(2000))
    pts, _ = route.parse_gpx(TRK.format(pts=body).encode())
    assert len(pts) <= route.MAX_POINTS
    assert pts[0].lat == pytest.approx(42.0)
    assert pts[-1].lat == pytest.approx(42.1999)  # концы трека сохранены


def test_wpt_only():
    pts, _ = route.parse_gpx(WPT_ONLY.encode())
    assert len(pts) == 2


def test_no_namespace_parsed():
    xml = RTE.replace(' xmlns="http://www.topografix.com/GPX/1/1"', "")
    pts, _ = route.parse_gpx(xml.encode())
    assert len(pts) == 2


def test_broken_xml():
    with pytest.raises(route.RouteError):
        route.parse_gpx(b"<gpx><rte>")


def test_empty_gpx():
    with pytest.raises(route.RouteError) as e:
        route.parse_gpx(b'<?xml version="1.0"?><gpx></gpx>')
    assert "маршрут" in str(e.value).lower() or "точ" in str(e.value).lower()


def test_too_large_file():
    with pytest.raises(route.RouteError):
        route.parse_gpx(b"x" * (route.MAX_GPX_BYTES + 1))


def test_entity_bomb_rejected_before_parsing():
    """«Billion laughs»: килобайт разворачивается в гигабайты при разборе.
    xml.etree раскрывает внутренние сущности, поэтому объявления режутся до него."""
    bomb = (b'<?xml version="1.0"?><!DOCTYPE gpx ['
            b'<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
            b']><gpx><rte><rtept lat="42.0" lon="44.0"><name>&b;</name></rtept>'
            b'<rtept lat="42.1" lon="44.1"/></rte></gpx>')
    with pytest.raises(route.RouteError) as e:
        route.parse_gpx(bomb)
    assert "doctype" in str(e.value).lower() or "сущност" in str(e.value).lower()

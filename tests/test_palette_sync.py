"""Цвета приложения совпадают с цветами PNG из чата.

Палитра живёт в charts.py и копируется в TypeScript — иначе никак, языки
разные. Незаметное расхождение приводит к тому, что один и тот же день в чате
и в приложении раскрашен по-разному, и пилот не знает, какой картинке верить.
"""
import pathlib
import re

import charts

ROOT = pathlib.Path(__file__).resolve().parent.parent
PALETTE = ROOT / "webapp" / "src" / "charts" / "palette.ts"


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(rgb)


def _declared() -> dict[str, str]:
    """Все объявления вида `X: "#rrggbb"` и `export const X = "#rrggbb"`."""
    text = PALETTE.read_text(encoding="utf-8")
    return {m.group(1): m.group(2).lower()
            for m in re.finditer(r'(?:export const\s+)?(\w+)\s*[:=]\s*"(#[0-9a-fA-F]{6})"', text)}


def test_scalar_colors_match_charts():
    got = _declared()
    for name, rgb in [("TERRAIN", charts.TERRAIN), ("BAND", charts.BAND),
                      ("TEMP", charts.TEMP), ("WIND", charts.WIND), ("GUST", charts.GUST)]:
        assert got.get(name) == _hex(rgb), f"{name}: {got.get(name)} против {_hex(rgb)}"


def test_every_grade_colour_matches_charts():
    got = _declared()
    for category, rgb in charts.GRADE_RGB.items():
        assert got.get(category) == _hex(rgb), f"{category}: {got.get(category)} против {_hex(rgb)}"


def test_no_grade_is_missing_from_the_palette():
    """Новая категория в charts.py без цвета в приложении — молчаливо серый день."""
    got = _declared()
    assert set(charts.GRADE_RGB) <= set(got)

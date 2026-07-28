"""Разрез маршрута: рисуется, не падает, вырожденные данные переживает."""
import os

from PIL import Image

import charts


def profile(n=5, terrain=True, **over):
    pts = []
    for i in range(n):
        pts.append({
            "km": float(i * 20), "eta": f"1{i % 10}:00",
            "role": "takeoff" if i == 0 else ("goal" if i == n - 1 else "enroute"),
            "is_turnpoint": i in (0, n - 1), "is_terrain_peak": i == 2,
            "name": "старт" if i == 0 else None,
            "terrain_m": 2000 + i * 100,
            "cloud_base_m": 3600 - i * 100,
            "thermal_ceiling_m": 3800 - i * 120,
            "wind_working_alt_kmh": 18.0 + i, "wind_working_alt_dir": 230.0 + i,
            "category": ["excellent", "fair", "fair", "marginal", "no_fly"][i % 5],
            "score": 70 - i * 5, "vetoes": [],
        })
    grid_n = (n - 1) * 20 + 1
    p = {
        "route": {"name": "Гудаури → Пасанаури", "date": "2026-07-28",
                  "departure": "11:00", "total_km": float((n - 1) * 20),
                  "timezone": "Asia/Tbilisi", "sample_step_km": 20.0},
        "points": pts,
        "terrain": ({"km": [float(i) for i in range(grid_n)],
                     "elevations": [2000.0 + (i % 30) * 10 for i in range(grid_n)]}
                    if terrain else None),
        "verdict": {"blocked_at_km": None, "bottleneck": {"km": 40.0, "score": 55}},
    }
    p.update(over)
    return p


def test_a_file_is_produced(tmp_path):
    path = charts.route_section_png(profile(), str(tmp_path))
    assert path and os.path.getsize(path) > 0


def test_the_image_has_the_expected_size(tmp_path):
    path = charts.route_section_png(profile(), str(tmp_path))
    assert Image.open(path).size == (1040, 660)


def test_no_terrain_no_picture(tmp_path):
    """Разрез без рельефа — это пустая рамка, лучше честно ничего не рисовать."""
    assert charts.route_section_png(profile(terrain=False), str(tmp_path)) is None


def test_an_empty_terrain_grid_gives_nothing(tmp_path):
    p = profile()
    p["terrain"] = {"km": [], "elevations": []}
    assert charts.route_section_png(p, str(tmp_path)) is None


def test_two_points_still_draw(tmp_path):
    assert charts.route_section_png(profile(n=2), str(tmp_path))


def test_a_collapsed_corridor_draws(tmp_path):
    """Коридор в минусе — самый важный случай, он обязан рисоваться."""
    p = profile()
    for pt in p["points"]:
        pt["cloud_base_m"] = pt["terrain_m"] - 50
        pt["thermal_ceiling_m"] = pt["terrain_m"] - 50
    assert charts.route_section_png(p, str(tmp_path))


def test_collapsed_segments_are_found_in_order():
    floor = [2300.0, 2400.0, 2500.0, 2600.0]
    top = [3600.0, 3500.0, 2400.0, 2300.0]   # коридор пропадает с третьей точки
    assert charts._collapsed_segments(floor, top) == [1, 2]


def test_an_unknown_end_is_not_called_collapsed():
    """«Неизвестно» и «негде лететь» — разные вещи."""
    assert charts._collapsed_segments([2300.0, None], [3600.0, 3500.0]) == []
    assert charts._collapsed_segments([2300.0, 2400.0], [None, 3500.0]) == []


def test_a_long_collapse_draws(tmp_path):
    p = profile(n=8)
    for pt in p["points"][3:]:
        pt["cloud_base_m"] = pt["terrain_m"] + 100
        pt["thermal_ceiling_m"] = pt["terrain_m"] + 100
    assert charts.route_section_png(p, str(tmp_path))


def test_missing_base_and_ceiling_do_not_crash(tmp_path):
    p = profile()
    p["points"][2]["cloud_base_m"] = None
    p["points"][2]["thermal_ceiling_m"] = None
    assert charts.route_section_png(p, str(tmp_path))


def test_all_base_and_ceiling_missing_does_not_crash(tmp_path):
    p = profile()
    for pt in p["points"]:
        pt["cloud_base_m"] = None
        pt["thermal_ceiling_m"] = None
    assert charts.route_section_png(p, str(tmp_path))


def test_missing_terrain_on_a_point_does_not_crash(tmp_path):
    p = profile()
    p["points"][2]["terrain_m"] = None
    assert charts.route_section_png(p, str(tmp_path))


def test_missing_wind_does_not_crash(tmp_path):
    p = profile()
    for pt in p["points"]:
        pt["wind_working_alt_dir"] = None
        pt["wind_working_alt_kmh"] = None
    assert charts.route_section_png(p, str(tmp_path))


def test_a_blocked_route_draws(tmp_path):
    p = profile()
    p["verdict"] = {"blocked_at_km": 60.0, "bottleneck": {"km": 60.0, "score": 0},
                    "blocked_reason": "база ниже безопасной высоты"}
    assert charts.route_section_png(p, str(tmp_path))


def test_a_nameless_route_draws(tmp_path):
    p = profile()
    p["route"]["name"] = None
    assert charts.route_section_png(p, str(tmp_path))


def test_many_points_thin_the_arrows_instead_of_overlapping(tmp_path):
    """Пятьдесят стрелок в ряд слипаются в кашу — их должно стать не больше 12."""
    assert len(charts._arrow_indexes(50)) <= charts.ARROWS_MAX
    assert len(charts._arrow_indexes(5)) == 5
    assert charts.route_section_png(profile(n=50), str(tmp_path))


def test_points_without_eta_draw(tmp_path):
    p = profile()
    p["points"][-1]["eta"] = None
    assert charts.route_section_png(p, str(tmp_path))


def test_a_route_without_a_verdict_draws(tmp_path):
    p = profile()
    p["verdict"] = None
    assert charts.route_section_png(p, str(tmp_path))

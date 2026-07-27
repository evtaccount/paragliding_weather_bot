"""Карточка маршрута: только погода и время, ширина под мобильный экран."""
import route


def profile(**over):
    pts = []
    for i, km in enumerate([0, 20, 40]):
        pts.append({
            "km": km, "eta": f"1{i + 1}:00", "eta_fixed": f"1{i + 1}:00",
            "role": "takeoff" if i == 0 else ("goal" if i == 2 else "enroute"),
            "wind_along_kmh": [10.0, 0.0, -14.0][i],
            "wind_working_alt_kmh": [10.0, 14.0, 20.0][i],
            "wind_working_alt_dir": [330.0, 240.0, 180.0][i],
            "w_star_ms": [1.8, 2.7, 0.9][i],
            "working_band_m": [1430, 720, 380][i],
            "terrain_m": 2000, "is_terrain_peak": False,
            "time_margin_min": [330, 150, -25][i],
            "weather": {"precipitation": 0.0, "cape": 100.0, "lifted_index": 2.0},
        })
    p = {"route": {"name": "Гудаури → Пасанаури", "date": "2026-07-28",
                   "departure": "11:00", "total_km": 40.0, "sample_step_km": 20.0,
                   "sample_count": 3, "model": "Auto (best_match)",
                   "avg_route_speed_kmh": 25.0, "wind_correction_enabled": True},
         "points": pts, "notes": []}
    p.update(over)
    return p


def test_every_line_fits_the_mobile_width():
    text = route.render_card(profile())
    assert max(len(ln) for ln in text.splitlines()) <= route.CARD_WIDTH


def test_table_has_a_row_per_point():
    text = route.render_card(profile())
    assert " 0 " in text and " 20 " in text and " 40 " in text


def test_tailwind_and_headwind_arrows_differ():
    text = route.render_card(profile())
    assert "→" in text and "←" in text


def test_heights_are_not_shown():
    """Прямое требование: рабочий диапазон считается, но в карточку не идёт."""
    text = route.render_card(profile())
    for forbidden in ("1430", "720", "380", "2000"):
        assert forbidden not in text


def test_time_margin_is_a_single_line_with_both_ends():
    text = route.render_card(profile())
    assert "+330" in text
    assert "−25" in text


def test_missing_wind_direction_does_not_crash():
    p = profile()
    p["points"][1]["wind_working_alt_dir"] = None
    assert "н/д" in route.render_card(p)


def test_point_beyond_midnight_renders_without_crashing():
    p = profile()
    p["points"][-1]["eta"] = None
    text = route.render_card(p)
    assert "за пределами суток" in text


def test_plural_of_points_reads_like_russian():
    p = profile()
    p["route"]["sample_count"] = 1
    assert "1 точка" in route.render_card(p)
    p["route"]["sample_count"] = 3
    assert "3 точки" in route.render_card(p)
    p["route"]["sample_count"] = 5
    assert "5 точек" in route.render_card(p)


def test_fixed_eta_warning_only_when_divergence_is_large():
    p = profile()
    p["points"][-1]["eta"], p["points"][-1]["eta_fixed"] = "16:36", "14:37"
    assert "14:37" in route.render_card(p)
    p["points"][-1]["eta"], p["points"][-1]["eta_fixed"] = "14:40", "14:37"
    assert "14:37" not in route.render_card(p)


def test_precipitation_line_names_the_kilometre():
    p = profile()
    p["points"][1]["weather"]["precipitation"] = 0.4
    text = route.render_card(p)
    assert "20" in text and "0,4" in text


def test_storm_line_names_the_kilometre():
    p = profile()
    p["points"][1]["weather"].update({"cape": 1150.0, "lifted_index": -3.6})
    assert "CAPE" in route.render_card(p)


def test_notes_are_shown():
    assert "рельеф" in route.render_card(profile(notes=["Рельеф недоступен"])).lower()

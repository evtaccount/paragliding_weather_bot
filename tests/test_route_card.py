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


# ---------------------------------------------------------------- вердикт
def with_verdict(**over):
    p = profile()
    for i, pt in enumerate(p["points"]):
        pt["score"] = [78, 62, 44][i]
        pt["category"] = ["excellent", "fair", "marginal"][i]
        pt["limiting"] = "рабочий диапазон высот"
        pt["vetoes"] = []
        pt["storm_ahead"] = None
        pt["profile"] = ["takeoff", "enroute", "goal"][i]
    p["verdict"] = {"score": 61, "category": "fair", "emoji": "🟡",
                    "label": "удовлетворительно", "feasibility": "completable",
                    "bottleneck": {"km": 40, "score": 44, "reason": "ветер вдоль курса"},
                    "blocked_at_km": None, "blocked_reason": None,
                    "flyable_until_km": 40, "mean_score": 61.3, "confidence": 1.0}
    p["departure_scan"] = [{"departure": "11:00", "score": 69, "feasibility": "completable"},
                           {"departure": "11:30", "score": 61, "feasibility": "completable"}]
    p["best_departure"] = p["departure_scan"][0]
    p["reverse"] = {"score": 74, "feasibility": "completable", "better": True}
    p.update(over)
    return p


def test_verdict_line_shows_category_and_score():
    text = route.render_card(with_verdict())
    assert "🟡" in text and "61" in text


def test_score_column_replaces_the_thermal_column():
    text = route.render_card(with_verdict())
    assert "балл" in text
    assert "поток" not in text


def test_table_still_fits_the_mobile_width():
    assert max(len(ln) for ln in route.render_card(with_verdict()).splitlines()) \
        <= route.CARD_WIDTH


def test_bottleneck_names_the_kilometre():
    text = route.render_card(with_verdict())
    assert "40" in text and "44" in text


def test_blocked_route_leads_with_the_reason_not_the_score():
    p = with_verdict()
    p["verdict"].update({"feasibility": "blocked_at_km", "blocked_at_km": 40,
                         "blocked_reason": "база ниже безопасной высоты над рельефом",
                         "flyable_until_km": 20})
    text = route.render_card(p)
    head = "\n".join(text.splitlines()[:8])
    assert "40" in head and "база ниже" in head
    assert "Лётно до 20 км" in text


def test_blocked_reason_wraps_within_the_width():
    p = with_verdict()
    p["verdict"].update({"feasibility": "blocked_at_km", "blocked_at_km": 40,
                         "blocked_reason": "база ниже безопасной высоты над рельефом",
                         "flyable_until_km": 20})
    assert max(len(ln) for ln in route.render_card(p).splitlines()) <= route.CARD_WIDTH


def test_best_departure_and_alternatives():
    text = route.render_card(with_verdict())
    assert "11:00" in text and "11:30" in text


def test_a_long_departure_scan_still_fits_the_width():
    """Скан даёт два десятка вариантов; в карточку влезают не все."""
    p = with_verdict()
    p["departure_scan"] = [{"departure": f"{h:02d}:{m:02d}", "score": 85,
                            "feasibility": "completable"}
                           for h in range(7, 19) for m in (0, 30)]
    p["best_departure"] = p["departure_scan"][0]
    assert max(len(ln) for ln in route.render_card(p).splitlines()) <= route.CARD_WIDTH


def test_flyable_until_only_shows_when_the_route_breaks():
    """Иначе это повтор общей длины маршрута."""
    assert "Лётно до" not in route.render_card(with_verdict())
    p = with_verdict()
    p["verdict"].update({"feasibility": "blocked_at_km", "blocked_at_km": 40,
                         "blocked_reason": "туман", "flyable_until_km": 20})
    assert "Лётно до 20 км" in route.render_card(p)


def test_no_completable_departure_is_said_plainly():
    p = with_verdict(best_departure=None)
    p["departure_scan"] = [{"departure": "11:00", "score": 30, "feasibility": "blocked_at_km"}]
    assert "ни одно время" in route.render_card(p).lower()


def test_reverse_line_appears_only_when_better():
    assert "74" in route.render_card(with_verdict())
    p = with_verdict()
    p["reverse"]["better"] = False
    assert "Обратный" not in route.render_card(p)


def test_storm_ahead_line_names_kilometre_and_time():
    p = with_verdict()
    p["points"][0]["storm_ahead"] = {"km": 60, "eta": "14:20"}
    text = route.render_card(p)
    assert "60" in text and "14:20" in text


def test_card_without_a_verdict_still_renders():
    """Карточка спеки 1 (без блоков вердикта) не должна падать."""
    assert "Гудаури" in route.render_card(profile())

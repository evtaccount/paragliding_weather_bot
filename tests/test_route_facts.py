"""Сборка данных для модели: профиль плюс блок computed."""
import forecast


def profile(n=5):
    pts = []
    for i in range(n):
        pts.append({
            "km": float(i * 10), "leg_length_km": 10.0, "eta": f"1{i % 10}:00",
            "role": "takeoff" if i == 0 else ("goal" if i == n - 1 else "enroute"),
            "lat": 42.0 + i / 100.0, "lon": 44.0, "name": None,
            "track_bearing_deg": 148, "is_turnpoint": i in (0, n - 1),
            "is_terrain_peak": False, "storm_ahead": None,
            "wind_along_kmh": -8.4, "wind_cross_kmh": -24.6,
            "wind_working_alt_kmh": 26.0, "wind_working_alt_dir": 268.0,
            "effective_ground_speed_kmh": 16.6,
            "terrain_m": 2510, "cloud_base_m": 3230, "thermal_ceiling_m": 4260,
            "working_band_m": 420, "time_margin_min": 210,
            "score": 61, "category": "fair", "limiting": "рабочий диапазон",
            "vetoes": [], "subs": {"working_band": 38.0}, "groups": {},
            "weather": {"cape": 850.0},
        })
    return {"route": {"name": "Тест", "total_km": float((n - 1) * 10)},
            "points": pts,
            "verdict": {"score": 61, "feasibility": "completable",
                        "bottleneck": {"km": 20.0}, "blocked_at_km": None},
            "departure_scan": [{"departure": "11:00", "score": 61,
                                "feasibility": "completable"}],
            "reverse": {"score": 74, "feasibility": "completable", "better": True}}


def test_route_verdict_scan_and_reverse_are_carried_over():
    f = forecast.route_facts(profile())
    assert set(f) == {"route", "points", "verdict", "departure_scan", "reverse"}


def test_every_point_carries_a_computed_block():
    f = forecast.route_facts(profile())
    assert all("computed" in p for p in f["points"])
    assert f["points"][0]["computed"]["subs"]


def test_the_computed_block_holds_the_scoring_not_the_geometry():
    c = forecast.route_facts(profile())["points"][0]["computed"]
    assert set(c) == {"score", "category", "limiting", "vetoes", "subs"}


def test_a_long_route_is_trimmed():
    """Больше двадцати точек — и ответ модели обрывается на середине."""
    f = forecast.route_facts(profile(n=50))
    assert len(f["points"]) <= forecast.ROUTE_FACTS_MAX_POINTS


def test_trimming_keeps_the_characteristic_points():
    f = forecast.route_facts(profile(n=50))
    kms = [p["km"] for p in f["points"]]
    assert 0.0 in kms and 490.0 in kms and 20.0 in kms


def test_points_stay_sorted_by_kilometre():
    kms = [p["km"] for p in forecast.route_facts(profile(n=50))["points"]]
    assert kms == sorted(kms)


def test_a_short_route_is_not_trimmed():
    assert len(forecast.route_facts(profile(n=5))["points"]) == 5


def test_the_payload_carries_the_signed_wind_components():
    """Знаки — то, ради чего модель и получает готовые числа."""
    p = forecast.route_facts(profile())["points"][0]
    assert p["wind_along_kmh"] == -8.4 and p["wind_cross_kmh"] == -24.6

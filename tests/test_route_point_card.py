"""Карточка отдельной точки: почему у неё такой балл."""
import route


def profile(**over):
    pts = []
    for i, km in enumerate([0.0, 40.0, 78.0]):
        pts.append({
            "km": km, "eta": f"1{i + 1}:00", "eta_fixed": f"1{i + 1}:00",
            "role": ["takeoff", "enroute", "goal"][i],
            "is_turnpoint": i in (0, 2), "is_terrain_peak": i == 1,
            "wind_along_kmh": [5.2, -8.4, -17.2][i],
            "wind_cross_kmh": [-17.1, -24.6, -19.4][i],
            "wind_working_alt_kmh": [18.0, 26.0, 34.0][i],
            "wind_working_alt_dir": [232.0, 268.0, 272.0][i],
            "effective_ground_speed_kmh": [30.2, 16.6, 7.8][i],
            "w_star_ms": [1.8, 2.7, 0.9][i],
            "terrain_m": [2196, 2510, 1050][i],
            "cloud_base_m": [3626, 3230, 2960][i],
            "thermal_ceiling_m": [3696, 4260, 2450][i],
            "working_band_m": [1130, 420, 1610][i],
            "time_margin_min": [330, 210, 95][i],
            "score": [79, 61, 44][i],
            "category": ["excellent", "fair", "marginal"][i],
            "limiting": "рабочий диапазон высот",
            "vetoes": [], "storm_ahead": None,
            "subs": {"working_band": 38.0, "wind_along": 54.0, "w_star": 72.0,
                     "cloud_low": 90.0},
            "groups": {"wind_along": 54.0},
            "weather": {"precipitation": 0.0, "cape": 850.0, "lifted_index": -3.2,
                        "convective_inhibition": 35.0, "visibility": 25000.0,
                        "cloud_cover_low": 40.0, "cloud_cover_mid": 20.0,
                        "wind_speed_10m": 4.7, "wind_gusts_10m": 6.1},
        })
    p = {"points": pts, "route": {"name": "Тест"}, "verdict": {}}
    p.update(over)
    return p


def card(km=40.0, **over):
    return route.render_point_card(profile(**over), km)


def test_every_line_fits_the_mobile_width():
    for km in (0.0, 40.0, 78.0):
        text = route.render_point_card(profile(), km)
        assert max(len(ln) for ln in text.splitlines()) <= route.CARD_WIDTH


def test_head_names_kilometre_time_and_role():
    text = card()
    assert "40 км" in text and "12:00" in text and "маршрут" in text


def test_roles_are_named_in_russian():
    assert "старт" in card(0.0)
    assert "финиш" in card(78.0)


def test_score_and_category_are_shown():
    assert "61" in card() and "удовлетворительная" in card()


def test_limiting_factor_is_named():
    assert "рабочий диапазон" in card()


def test_heights_are_present_here_on_purpose():
    """Из таблицы маршрута высоты убраны, но эту карточку открывают ради них."""
    text = card()
    assert "3230" in text and "2510" in text and "420" in text


def test_wind_along_and_cross_carry_their_signs():
    text = card()
    assert "←" in text and "8" in text
    assert "25" in text


def test_wind_direction_is_shown_as_a_compass_point():
    assert "З" in card()


def test_ground_wind_only_for_takeoff_and_goal():
    """В воздухе наземный ветер в оценке не участвует — печатать его значит
    предлагать решение по числу, которое ни на что не влияет."""
    assert "Земля" in card(0.0)
    assert "Земля" in card(78.0)
    assert "Земля" not in card(40.0)


def test_terrain_peak_is_marked():
    assert "▲" in card(40.0)
    assert "▲" not in card(0.0)


def test_storm_numbers_are_shown():
    text = card()
    assert "CAPE" in text and "850" in text


def test_worst_subscores_are_listed_lowest_first():
    tail = card().split("Что тянет вниз:")[1]
    assert tail.index("38") < tail.index("54") < tail.index("72")


def test_only_three_subscores():
    tail = card().split("Что тянет вниз:")[1]
    assert "90" not in tail


def test_subscores_are_named_in_russian():
    """Ключи параметров английские; в карточку должны идти названия из criteria."""
    tail = card().split("Что тянет вниз:")[1]
    assert "working_band" not in tail and "w_star" not in tail
    assert "рабочий диапазон" in tail


def test_a_long_parameter_name_does_not_break_the_width():
    p = profile()
    p["points"][1]["subs"] = {"time_margin": 12.0}
    text = route.render_point_card(p, 40.0)
    assert max(len(ln) for ln in text.splitlines()) <= route.CARD_WIDTH
    assert "запас времени" in text


def test_missing_values_read_as_unknown_not_as_absent():
    p = profile()
    p["points"][1]["cloud_base_m"] = None
    p["points"][1]["wind_working_alt_dir"] = None
    text = route.render_point_card(p, 40.0)
    assert text.count("н/д") >= 2


def test_vetoes_are_shown_and_wrapped():
    p = profile()
    p["points"][1]["vetoes"] = ["база ниже безопасной высоты над рельефом"]
    text = route.render_point_card(p, 40.0)
    assert "база ниже" in text
    assert max(len(ln) for ln in text.splitlines()) <= route.CARD_WIDTH


def test_an_unknown_kilometre_gives_nothing():
    assert route.render_point_card(profile(), 999.0) is None


def test_a_point_without_a_score_still_renders():
    p = profile()
    p["points"][1].update({"score": None, "category": None, "limiting": None,
                           "subs": {}, "groups": {}})
    assert "40 км" in route.render_point_card(p, 40.0)


def test_a_point_beyond_midnight_renders():
    p = profile()
    p["points"][1]["eta"] = None
    assert "40 км" in route.render_point_card(p, 40.0)

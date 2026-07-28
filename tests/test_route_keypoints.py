"""Характерные точки маршрута: где реально что-то решается."""
import route


def profile(n=5, **over):
    pts = []
    for i in range(n):
        pts.append({"km": float(i * 10),
                    "role": ("takeoff" if i == 0 else
                             "goal" if i == n - 1 else "enroute"),
                    "is_turnpoint": i in (0, n - 1), "is_terrain_peak": False})
    p = {"points": pts, "verdict": {"blocked_at_km": None, "bottleneck": None}}
    p.update(over)
    return p


def kms(profile_):
    return [k["km"] for k in route.key_points(profile_)]


def marks(profile_):
    return {k["km"]: k["mark"] for k in route.key_points(profile_)}


def test_start_and_goal_are_always_there():
    assert kms(profile()) == [0.0, 40.0]


def test_turnpoints_are_included():
    p = profile()
    p["points"][2]["is_turnpoint"] = True
    assert kms(p) == [0.0, 20.0, 40.0]


def test_terrain_peaks_are_included():
    p = profile()
    p["points"][3]["is_terrain_peak"] = True
    assert kms(p) == [0.0, 30.0, 40.0]


def test_bottleneck_and_blocked_point_are_included():
    p = profile(verdict={"blocked_at_km": 30.0, "bottleneck": {"km": 20.0}})
    assert kms(p) == [0.0, 20.0, 30.0, 40.0]


def test_a_point_appears_once_with_the_more_important_mark():
    """Вершина рельефа, оказавшаяся узким местом, — одна кнопка, а не две."""
    p = profile(verdict={"blocked_at_km": None, "bottleneck": {"km": 20.0}})
    p["points"][2]["is_terrain_peak"] = True
    assert kms(p).count(20.0) == 1
    assert marks(p)[20.0] == "⚠"


def test_blocked_outranks_the_bottleneck_on_the_same_point():
    p = profile(verdict={"blocked_at_km": 20.0, "bottleneck": {"km": 20.0}})
    assert marks(p)[20.0] == "⛔"


def test_marks_tell_the_kinds_apart():
    p = profile()
    p["points"][2]["is_turnpoint"] = True
    p["points"][3]["is_terrain_peak"] = True
    m = marks(p)
    assert m[0.0] == "△" and m[40.0] == "⚑" and m[20.0] == "◆" and m[30.0] == "▲"


def test_never_more_than_the_limit():
    p = profile(n=30)
    for pt in p["points"]:
        pt["is_terrain_peak"] = True
    assert len(route.key_points(p)) <= route.KEY_POINT_LIMIT


def test_the_limit_keeps_the_important_kinds_first():
    """Вершин много, но старт, финиш и узкое место обязаны остаться."""
    p = profile(n=30, verdict={"blocked_at_km": None, "bottleneck": {"km": 150.0}})
    for pt in p["points"]:
        pt["is_terrain_peak"] = True
    got = kms(p)
    assert 0.0 in got and 290.0 in got and 150.0 in got


def test_result_is_sorted_by_kilometre():
    p = profile(n=30)
    for pt in p["points"]:
        pt["is_terrain_peak"] = True
    got = kms(p)
    assert got == sorted(got)


def test_no_points_no_key_points():
    assert route.key_points({"points": [], "verdict": {}}) == []


def test_missing_verdict_does_not_crash():
    assert kms({"points": profile()["points"]}) == [0.0, 40.0]

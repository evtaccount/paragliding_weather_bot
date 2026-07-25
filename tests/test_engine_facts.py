"""facts_1day: the LLM payload must include upper-level (600/500 hPa) wind direction,
now that H_1D fetches wind_direction_600hPa / _500hPa."""
import engine
from fixtures import om_1day as _full_1d, site as _site


def test_facts_1day_carries_the_thermal_window_and_per_hour_sun():
    f = engine.facts_1day(_full_1d(), _site())
    w = f["thermal_window"]
    assert w["start_hour"] >= 7 and w["end_hour"] <= 19   # sunrise 05:00 / sunset 20:00
    hours = {h["time"]: h for h in f["hourly_daytime"]}
    assert hours["12:00"]["slope_sun_index"] > hours["06:00"]["slope_sun_index"]
    assert 165 < hours["12:00"]["sun_az_deg"] < 195       # south slope, sun on the face


def test_facts_overview_carries_a_thermal_window_per_day():
    data = _full_1d()
    f = engine.facts_overview(data, _site(), "3d")
    assert f["days_daytime"][0]["thermal_window"]["start_hour"] >= 7


def test_facts_1day_includes_upper_level_directions():
    f = engine.facts_1day(_full_1d(), _site())
    prof = {r["level"]: r for r in f["wind_profile_peak_hour"]}
    # the two top levels now carry a direction (previously hard-coded None → key absent)
    assert prof["600hPa"]["dir_deg"] == 220
    assert prof["500hPa"]["dir_deg"] == 230
    # lower levels unchanged
    assert prof["700hPa"]["dir_deg"] == 210
    assert prof["10m"]["dir_deg"] == 180

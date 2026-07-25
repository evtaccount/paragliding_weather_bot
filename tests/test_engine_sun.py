"""Sun geometry → thermal window.

The LLM used to flag "risks" at sunrise because every daylight hour looked equally
thermic to it. These cover the numbers that fix that: sun azimuth/elevation per hour,
how directly the sun hits the launch slope, and the derived working window.
"""
import tempfile

import engine
from test_engine_degrade import _data, _site


DATE = "2026-07-25"   # summer, declination ~+19°
LAT = 42.0
SR, SS = "2026-07-25T05:00", "2026-07-25T20:00"   # solar noon at 12:30
DAY_HOURS = list(range(5, 21))


def _rows(aspect):
    return engine.sun_hours(DATE, LAT, SR, SS, DAY_HOURS, aspect)


def test_sun_azimuth_runs_east_to_west_through_south():
    rows, _ = _rows(180.0)
    by_hour = {r["hour"]: r for r in rows}
    assert 60 < by_hour[6]["sun_az_deg"] < 100      # morning: sun in the east
    assert 165 < by_hour[12]["sun_az_deg"] < 195    # solar noon (12:30): due south
    assert 260 < by_hour[19]["sun_az_deg"] < 300    # evening: sun in the west
    assert by_hour[13]["sun_elev_deg"] > by_hour[7]["sun_elev_deg"]


def test_south_slope_heats_at_midday_and_shades_in_the_evening():
    rows, _ = _rows(180.0)
    idx = {r["hour"]: r["slope_sun_index"] for r in rows}
    assert idx[12] == max(idx.values())             # peak heating around solar noon
    assert idx[19] < idx[12] / 2                    # sun has moved off the face by 19:00
    assert idx[6] < idx[12]


def test_west_slope_peaks_later_than_south_slope():
    south = {r["hour"]: r["slope_sun_index"] for r in _rows(180.0)[0]}
    west = {r["hour"]: r["slope_sun_index"] for r in _rows(270.0)[0]}
    peak_s = max(south, key=south.get)
    peak_w = max(west, key=west.get)
    assert peak_w > peak_s                          # west works later in the day
    assert west[18] > south[18]                     # and beats south in the evening


def test_thermal_window_excludes_the_first_and_last_daylight_hours():
    _, w = _rows(180.0)
    assert w["start_hour"] >= 7                     # sunrise 05:00 + 2h lag
    assert w["end_hour"] <= 19                      # sunset 20:00 - 1h lead
    assert w["start_hour"] < w["peak_hour"] < w["end_hour"] + 1
    assert w["solar_noon"] == "12:30"


def test_thermal_window_is_none_in_polar_night():
    _, w = engine.sun_hours("2026-12-21", 78.0, "2026-12-21T11:00", "2026-12-21T12:00",
                            [11, 12], 180.0)
    assert w is None


def test_card_window_is_clipped_to_the_thermal_window():
    """Calm all day (fixture wind 2 m/s), so only the sun bounds the window —
    it must not run sunrise-to-sunset (05:00–20:00)."""
    text, _pngs, _card = engine.report_1day(_data(), _site(), tempfile.mkdtemp())
    assert "⏱️ Лётное окно: 07:00–17:00" in text
    assert "солнце на склоне 07–17" in text


def test_card_window_shrinks_further_when_the_afternoon_blows_out():
    d = _data()
    for h in range(16, 24):                   # wind over the limit from 16:00 on
        d["hourly"]["wind_speed_10m"][h] = 9.0
    text, _pngs, _card = engine.report_1day(d, _site(), tempfile.mkdtemp())
    assert "⏱️ Лётное окно: 07:00–15:00" in text


def test_unknown_aspect_keeps_geometry_but_drops_the_slope_index():
    rows, w = _rows(None)
    assert all(r["slope_sun_index"] is None for r in rows)
    assert rows[0]["sun_az_deg"] is not None
    assert w is not None                            # window still derived from sun elevation

"""Рельеф: своя сетка, максимум по участку сэмпла, отметка вершины."""
import pytest

import route

PTS = [route.Point(42.0, 44.0), route.Point(42.0 + 40.0 / 111.195, 44.0)]


def test_grid_step_depends_on_route_length():
    grid_short = route.terrain_grid(PTS, total_km=40.0)
    assert grid_short[1][0] - grid_short[0][0] == pytest.approx(0.5, abs=0.05)
    grid_long = route.terrain_grid(PTS, total_km=120.0)
    assert grid_long[1][0] - grid_long[0][0] == pytest.approx(1.0, abs=0.05)


def test_grid_covers_whole_route():
    grid = route.terrain_grid(PTS, total_km=120.0)
    assert grid[0][0] == pytest.approx(0.0)
    assert grid[-1][0] == pytest.approx(40.0, abs=1.0)


def test_sample_terrain_is_max_over_its_segment():
    samples, step = route.resample(PTS, step_km=10.0)
    grid = route.terrain_grid(PTS, total_km=40.0)
    # ровное плато 1000 м, но на 21-м километре гребень 2500 м
    elev = [2500.0 if 20.5 <= km <= 21.5 else 1000.0 for km, _, _ in grid]
    route.attach_terrain(samples, grid, elev, step_km=step)
    at20 = next(s for s in samples if round(s.km) == 20)
    assert at20.terrain_m == 2500.0        # гребень попал в участок сэмпла
    assert at20.terrain_point_m == 1000.0  # под самой точкой — плато
    assert samples[0].terrain_m == 1000.0


def test_terrain_peak_flag():
    samples, step = route.resample(PTS, step_km=10.0)
    grid = route.terrain_grid(PTS, total_km=40.0)
    elev = [2500.0 if 19.0 <= km <= 21.0 else 1000.0 for km, _, _ in grid]
    route.attach_terrain(samples, grid, elev, step_km=step)
    assert next(s for s in samples if round(s.km) == 20).is_terrain_peak is True
    assert samples[0].is_terrain_peak is False


def test_missing_elevations_leave_none():
    samples, step = route.resample(PTS, step_km=10.0)
    route.attach_terrain(samples, [], None, step_km=step)
    assert all(s.terrain_m is None for s in samples)
    assert all(s.is_terrain_peak is False for s in samples)

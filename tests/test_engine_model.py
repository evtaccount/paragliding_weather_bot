"""engine model registry + личная настройка модели + build_url &models=."""
import engine
import store
from conftest import TEST_USER_ID


def _site():
    return {"name": "Тест", "lat": 42.0, "lon": 44.0, "elevation_m": 1500,
            "aspect": "Ю", "aspect_deg": 180.0, "notes": ""}


def test_default_model_is_auto():
    """Дефолт — best_match: только он отдаёт весь набор полей для скоринга
    (у ECMWF нет пограничного слоя, LI, CIN, видимости и ветра на 80/120 м)."""
    assert engine.DEFAULT_MODEL_KEY == "auto"
    assert store.prefs(TEST_USER_ID).model_key == "auto"
    assert engine.model_id("auto") == "best_match"
    assert engine.model_id("ecmwf") == "ecmwf_ifs025"


def test_build_url_defaults_to_the_default_model():
    assert "models=best_match" in engine.build_url(_site(), "week")
    assert "models=icon_seamless" in engine.build_url(_site(), "1d", "2026-07-25",
                                                      model="icon")


def test_cache_key_includes_model(monkeypatch):
    import asyncio

    import forecast

    calls = []

    async def fake_build(site, rng, date, model=None):
        calls.append((model or engine.DEFAULT_MODEL_KEY, rng))
        return "card", [], {}, "fb", [], None  # 6-tuple _fetch_build contract

    monkeypatch.setattr(forecast, "_fetch_build", fake_build)

    site = store.find_site("Гудаури")
    _s, _d, key1 = forecast._resolve("Гудаури", "week", None)
    asyncio.run(forecast._ensure(site, "week", None, key1))  # warm under auto
    _s, _d, key2 = forecast._resolve("Гудаури", "week", None, model="gfs")
    assert key1 != key2                       # model is part of the key
    asyncio.run(forecast._ensure(site, "week", None, key2, model="gfs"))  # rebuild, not reuse
    assert [c[0] for c in calls] == ["auto", "gfs"]


# ---------------------------------------------------------------- коды моделей


def test_model_codes_cover_every_model_and_are_unique():
    """Код едет в callback_data, где каждый байт на счету. Таблица явная, а не
    «первая буква ключа»: пятая модель с конфликтующей буквой должна падать
    здесь, а не молча переключать пользователя на чужую модель."""
    assert set(engine.MODEL_CODES) == set(engine.MODELS)
    codes = list(engine.MODEL_CODES.values())
    assert len(set(codes)) == len(codes)
    assert all(len(c) == 1 and c.isascii() for c in codes)


def test_model_code_roundtrip():
    for key in engine.MODELS:
        assert engine.model_for_code(engine.model_code(key)) == key


def test_model_for_unknown_code_is_none():
    """Устаревшая кнопка с кодом исчезнувшей модели → «разового выбора нет»."""
    assert engine.model_for_code("z") is None
    assert engine.model_for_code("") is None


# ---------------------------------------------------------------- URL потолка


def test_ceiling_url_always_gfs_and_one_variable():
    store.set_model(TEST_USER_ID, "ecmwf")
    url = engine.ceiling_url(_site(), "1d", "2026-07-29")
    assert "models=gfs_seamless" in url          # не выбранная модель
    assert "hourly=boundary_layer_height" in url  # ровно одна серия
    assert "daily=" not in url
    assert "start_date=2026-07-29&end_date=2026-07-29" in url


def test_ceiling_url_overview_uses_forecast_days():
    url = engine.ceiling_url(_site(), "week")
    assert "forecast_days=7" in url and "models=gfs_seamless" in url


def test_route_ceiling_url_keeps_explicit_timezone():
    """Явный пояс, как и в route_weather_url: под timezone=auto точки по разные
    стороны границы поясов получили бы разные часы в одной таблице."""
    url = engine.route_ceiling_url([(42.0, 44.0), (42.5, 44.5)], "2026-07-29", "Asia/Tbilisi")
    assert "timezone=Asia%2FTbilisi" in url or "timezone=Asia/Tbilisi" in url
    assert "timezone=auto" not in url
    assert "models=gfs_seamless" in url
    assert "hourly=boundary_layer_height" in url
    assert "latitude=42.0000,42.5000" in url


# ---------------------------------------------------------------- разовая модель в URL


def test_build_url_model_argument_does_not_touch_stored_preference():
    """Разовый выбор едет параметром и постоянную настройку пилота не пишет."""
    assert "models=ecmwf_ifs025" in engine.build_url(_site(), "week", model="ecmwf")
    assert store.prefs(TEST_USER_ID).model_key == "auto"


def test_route_weather_url_takes_the_model_argument():
    url = engine.route_weather_url([(42.0, 44.0)], "2026-07-29", "Asia/Tbilisi", model="gfs")
    assert "models=gfs_seamless" in url
    assert store.prefs(TEST_USER_ID).model_key == "auto"

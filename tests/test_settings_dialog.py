"""Команда /settings: показ, кнопки, ввод своего значения, валидация."""
import settings
from tg import callback_update, text_update, texts


async def test_settings_shows_current_values(feed, session):
    await feed(text_update("/settings"))
    assert "25" in texts(session)[-1]
    assert "км/ч" in texts(session)[-1]


async def test_button_sets_speed(feed, session):
    await feed(text_update("/settings"))
    await feed(callback_update("sp|30"))
    assert settings.get()["avg_route_speed_kmh"] == 30.0


async def test_toggle_switches_wind_correction(feed, session):
    await feed(callback_update("sw|0"))
    assert settings.get()["wind_correction_enabled"] is False
    await feed(callback_update("sw|1"))
    assert settings.get()["wind_correction_enabled"] is True


async def test_custom_value_via_dialog(feed, session):
    await feed(text_update("/settings"))
    await feed(callback_update("sp|custom"))
    await feed(text_update("28"))
    assert settings.get()["avg_route_speed_kmh"] == 28.0


async def test_custom_value_out_of_range_explains_itself(feed, session):
    await feed(text_update("/settings"))
    await feed(callback_update("sp|custom"))
    await feed(text_update("99"))
    assert settings.get()["avg_route_speed_kmh"] == 25.0
    assert "скорость крыла" in texts(session)[-1]


async def test_custom_value_not_a_number(feed, session):
    await feed(text_update("/settings"))
    await feed(callback_update("sp|custom"))
    await feed(text_update("быстро"))
    assert settings.get()["avg_route_speed_kmh"] == 25.0

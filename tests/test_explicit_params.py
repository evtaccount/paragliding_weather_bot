"""Модель и настройки приходят параметром: домен не должен знать, кто спрашивает.

Проверяется сигнатура, а не вызов: корутина с недостающим keyword-only
аргументом падает ещё до await, и оборачивать это в asyncio.run незачем.
"""
import inspect

import forecast

REQUIRED = [
    (forecast.get_forecast,  "model"),
    (forecast.get_wind_grid, "model"),
    (forecast.get_analysis,  "model"),
    (forecast.scan_week,     "model"),
    (forecast.get_route,     "cfg"),
]
# get_facts появляется в задаче 11 и дописывается в этот список там же.
#
# forecast.get_route НЕ получает отдельный параметр model, в отличие от брифа
# задачи 9: модель маршрута выводится из cfg.model_key (упрощение задачи 7,
# см. task-7-report.md, отклонение №3). Отдельной проверки на "model" здесь
# нет — она дублировала бы cfg и такого параметра у функции не существует.


def test_required_params_have_no_default():
    for fn, name in REQUIRED:
        p = inspect.signature(fn).parameters[name]
        assert p.default is inspect.Parameter.empty, f"{fn.__name__}: {name} с дефолтом"


def test_required_params_are_keyword_only():
    """Позиционными их делать нельзя: у get_route перед ними стоит
    departure_h со значением по умолчанию."""
    for fn, name in REQUIRED:
        p = inspect.signature(fn).parameters[name]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, f"{fn.__name__}: {name}"

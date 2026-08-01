"""ThrottleMiddleware напрямую, минуя диспетчер aiogram: только так виден
дефект «слот занят во время сетевого ответа об отказе»."""
import time
from types import SimpleNamespace

import guards


async def test_a_cooldown_refusal_does_not_hold_the_slot():
    """Пауза между набранными командами — не расчёт. Пока бот пишет «не так
    часто», пилот не занят: иначе приложение, открытое в эту секунду, получит
    429 вместо прогноза. Проверка стоит ВНУТРИ ответа — снаружи её не видно,
    finally освобождает слот в любом случае."""
    mw = guards.ThrottleMiddleware()
    mw.cooldown = 60
    mw._last[1] = time.monotonic()   # пилот только что уже набирал команду

    seen = []

    class Msg:  # минимальный набранный (не кнопочный) апдейт
        from_user = SimpleNamespace(id=1)

        async def answer(self, text, **kw):
            seen.append((text, guards.INFLIGHT.busy(1)))

    called = []

    async def handler(event, data):
        called.append(1)

    data = {"handler": SimpleNamespace(flags={"forecast": True})}
    await mw(handler, Msg(), data)

    assert not called, "обработчик не должен был запуститься"
    text, was_busy = seen[0]
    assert "Не так часто" in text
    assert not was_busy, "слот занят на время отказа по паузе"

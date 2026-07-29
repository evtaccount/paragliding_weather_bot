"""Test harness: env + temp database BEFORE the bot modules are imported,
a mocked aiogram session (records outgoing API calls, no network), and
per-test reset of every piece of stored and in-memory state.
"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmpdir = tempfile.mkdtemp(prefix="pgbot_tests_")
DB_PATH = os.path.join(_tmpdir, "test.db")

# Env must be set before importing bot/engine/store (they read it at import time).
# Pre-set vars also shield the tests from the repo's real .env: load_dotenv() in
# bot.py does not override existing variables.
os.environ["DB_PATH"] = DB_PATH
os.environ["BOT_TOKEN"] = "42:TEST"
os.environ["ALLOWED_USER_IDS"] = ""  # open mode — whitelist passes everyone
os.environ["COOLDOWN_SEC"] = "0"
os.environ["GEMINI_API_KEY"] = ""

DEFAULT_SITES = [
    {"name": "Гудаури", "aliases": ["gudauri", "гуда"], "lat": 42.47, "lon": 44.48,
     "elevation_m": 2200, "aspect": "Ю", "aspect_deg": 180.0, "notes": ""},
    {"name": "Лалискури", "aliases": ["laliskuri"], "lat": 42.1, "lon": 45.3,
     "elevation_m": 900, "aspect": "ЮЗ", "aspect_deg": 225.0, "notes": ""},
]

import pytest  # noqa: E402
from aiogram import Bot  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402

import bot as botmod  # noqa: E402
import forecast  # noqa: E402
import store  # noqa: E402

TEST_USER_ID = 1  # id, который подставляют tests/tg.py в сообщениях и колбэках


class MockSession(BaseSession):
    """Records outgoing API calls instead of hitting Telegram. Returns True for
    everything — no handler in the bot uses a call's return value."""

    def __init__(self):
        super().__init__()
        self.requests = []

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        return True

    async def stream_content(self, url, headers=None, timeout=30,
                             chunk_size=65536, raise_for_status=True):
        yield b""

    async def close(self):
        pass


def write_sites(sites: list[dict]):
    """Заменить библиотеку стартов ровно на переданный список."""
    with store.connect() as conn:
        conn.execute("DELETE FROM sites")
    for s in sites:
        store.add_site(s)


@pytest.fixture(autouse=True)
def no_ceiling_request(monkeypatch):
    """Побочный запрос за потолком заглушён по умолчанию.

    Он ходит из _fetch_build и _ensure_route_weather, которые тесты мокают
    по отдельности, — без этой заглушки каждый такой тест уходил бы в сеть и
    висел до 30-секундного таймаута httpx. Тесты самой подстановки
    переопределяют заглушку своим моком.
    """
    async def none(url):
        return None

    monkeypatch.setattr(forecast, "_fetch_ceiling", none)


@pytest.fixture(autouse=True)
def fresh_state():
    """Чистая БД, пустые кэши, пустой FSM — перед каждым тестом."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    for suffix in ("-wal", "-shm"):
        if os.path.exists(DB_PATH + suffix):
            os.remove(DB_PATH + suffix)
    store.init()
    write_sites(DEFAULT_SITES)
    forecast._fcache.clear()
    forecast._acache.clear()
    forecast._rcache.clear()
    botmod.dp.fsm.storage.storage.clear()  # MemoryStorage internals
    botmod._route_cache.clear()            # токены маршрутов под кнопками
    yield


@pytest.fixture()
def session():
    return MockSession()


@pytest.fixture()
def tg_bot(session):
    return Bot(token="42:TEST", session=session)


@pytest.fixture()
def feed(tg_bot):
    async def _feed(update):
        return await botmod.dp.feed_update(tg_bot, update)
    return _feed


@pytest.fixture()
def fc_calls(monkeypatch):
    """Patch forecast.get_forecast; returns the recorded (site, rng, date, model) calls."""
    calls = []

    async def fake(site, rng, date=None, model=None):
        calls.append((site, rng, date, model))
        return f"CARD {site} {rng} {date}", [b"png"]

    monkeypatch.setattr(forecast, "get_forecast", fake)
    return calls


@pytest.fixture()
def an_calls(monkeypatch):
    """Patch forecast.get_analysis; returns the recorded (site, rng, date, deep, model) calls."""
    calls = []

    async def fake(site, rng, date=None, deep=False, model=None):
        calls.append((site, rng, date, deep, model))
        return "АНАЛИЗ ГОТОВ"

    monkeypatch.setattr(forecast, "get_analysis", fake)
    return calls


@pytest.fixture()
def elevation(monkeypatch):
    async def fake(lat, lon):
        return 1234

    monkeypatch.setattr(forecast, "fetch_elevation", fake)

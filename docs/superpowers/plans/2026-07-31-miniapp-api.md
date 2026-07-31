# HTTP-слой мини-приложения (фаза 3) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Поднять HTTP-поверхность над существующим доменом: FastAPI с проверкой подписи Telegram, все эндпоинты из спеки, один процесс с ботом, раскатка за Caddy.

**Architecture:** `webauth.py` проверяет `initData` чистыми функциями без HTTP. `api.py` — тонкий адаптер: разбирает запрос, резолвит `store.prefs(uid)`, зовёт `forecast`, переводит исключения в коды. `app.py` запускает long polling и uvicorn в одном процессе, чтобы кэш прогнозов оставался общим для обеих поверхностей. Ни одного расчёта в HTTP-слое нет.

**Tech Stack:** FastAPI, uvicorn, pydantic v2 (транзитивно), httpx (уже есть), Caddy, SQLite через существующий `store.py`.

## Global Constraints

- **Приложение получает числа, а не картинки.** PNG-эндпоинтов нет; `charts.py` остаётся чату. Где домен сейчас отдаёт байты (`get_wind_grid`, `get_route_section`), API берёт словарь до отрисовки.
- **Домен не знает про пользователя.** `user_id` живёт в `api.py` и `store.py`. `forecast` и `engine` получают `model` / `cfg` параметрами, как после фазы 2. Ни один вызов домена из `api.py` не имеет права опускать `model=` или `cfg=`.
- **Один процесс.** `_fcache`, `_acache`, `_rcache` процессные, и на переиспользовании тёплого кэша между ботом и приложением построена вся экономия запросов к open-meteo. Разносить бот и API по процессам нельзя.
- **`initData` проверяется на каждом запросе.** Сессионных токенов нет. Заголовок `Authorization: tma <initData>`.
- **Секрет:** `secret = HMAC_SHA256(key="WebAppData", msg=BOT_TOKEN)`, затем `hash = HMAC_SHA256(key=secret, msg=data_check_string)`. `data_check_string` — пары `key=value` с **раскодированными** значениями, без `hash`, отсортированные по ключу, склеенные через `\n`.
- **`auth_date` старше 24 часов отклоняется.**
- **Allowlist общий с ботом:** тот же `ALLOWED_USER_IDS`. Пустой список = открытый режим, как у бота.
- **Коды ошибок** ровно по таблице спеки: 401 подпись, 403 не в списке, 404 старт не найден, 400 `ForecastError` / `RouteError` (текст как есть, он уже написан для человека), 502 open-meteo или Elevation недоступны, 429 запрос этого пользователя уже выполняется.
- **Троттлинг API — только in-flight, без паузы.** 10-секундный cooldown, который бот применяет к набранным командам, к приложению не применяется: там каждое действие — продолжение уже выданного результата.
- **Тексты ошибок домена не переводятся.** `ForecastError` и `RouteError` уже написаны по-русски для пилота.
- **Наружу не отдаётся диагностика подписи.** Причина отказа уходит в лог, клиент получает 401 без подробностей.
- **Тесты**: `pytest`, `asyncio_mode = auto` (уже настроено в `pytest.ini`). Каждая задача заканчивается зелёным полным прогоном.
- **Комментарии и сообщения — по-русски**, в стиле существующего кода: объясняют «почему», а не «что».

---

## Структура файлов

| Файл | Ответственность |
|---|---|
| `webauth.py` (новый) | Проверка `initData`: HMAC, срок годности, разбор `user`. Не импортирует ни FastAPI, ни `store`, ни `forecast`. |
| `api.py` (новый) | FastAPI: зависимость авторизации, эндпоинты, перевод исключений в коды. Расчётов нет. |
| `app.py` (новый) | Точка входа: bootstrap хранилища, `asyncio.gather(polling, uvicorn)`. |
| `guards.py` (правится) | `_allowed_ids` → `allowed_ids` (публичный, зовут три модуля); общий на обе поверхности реестр in-flight. |
| `forecast.py` (правится) | `wind_grid_data()` — тот же словарь, что уходит в PNG, без отрисовки. |
| `bot.py` (правится) | `main()` разбирается на `bootstrap` + `run_polling`, чтобы `app.py` мог запустить одно без другого. |
| `static/index.html` (новый) | Страница-заглушка: проверить подпись живым клиентом Telegram до React. |
| `Caddyfile` (новый) | TLS своим сертификатом, статика, `/api/*` на uvicorn. |
| `tests/tma.py` (новый) | Подписывает `initData` в тестах — общий для `test_webauth` и всех `test_api_*`. |

Зависимости: `api` → `webauth`, `guards`, `store`, `forecast`, `engine`, `route`. `webauth` не зависит ни от чего в проекте. Циклов нет.

---

### Task 1: `webauth.py` — проверка подписи Telegram

**Files:**
- Create: `webauth.py`
- Create: `tests/tma.py`
- Create: `tests/test_webauth.py`

**Interfaces:**
- Consumes: ничего из проекта (стандартная библиотека).
- Produces: `webauth.verify(raw, bot_token, *, max_age_sec=MAX_AGE_SEC, now=None) -> TelegramUser`; `webauth.AuthError`; `webauth.TelegramUser(id, first_name, last_name, username, language_code)`; `webauth.MAX_AGE_SEC`. `tests/tma.py`: `sign(fields, token="42:TEST") -> str`, `header(uid=1, token="42:TEST", **extra) -> dict`.

- [ ] **Step 1: Написать общий помощник для тестов**

`tests/tma.py`:

```python
"""Подписанная initData для тестов.

Живёт отдельным модулем, потому что нужен и тестам самой проверки, и каждому
тесту эндпоинта: без него в половине файлов завелась бы своя копия формулы
подписи, и опечатка в копии выглядела бы как баг сервера.
"""
import hashlib
import hmac
import json
import time
import urllib.parse

TOKEN = "42:TEST"  # тот же, что conftest кладёт в BOT_TOKEN


def sign(fields: dict, token: str = TOKEN) -> str:
    """Собрать initData с корректным hash.

    Значения подписываются РАСКОДИРОВАННЫМИ, а в строку уходят
    percent-encoded — ровно так делает Telegram, и ровно на этом ломаются
    наивные реализации: подпись считают по уже закодированной строке.
    """
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode({**fields, "hash": digest})


def init_data(uid: int = 1, token: str = TOKEN, *, auth_date: int | None = None,
              user_extra: dict | None = None, **fields) -> str:
    user = {"id": uid, "first_name": "Пилот", "username": "pilot",
            "language_code": "ru", **(user_extra or {})}
    base = {"auth_date": str(int(time.time()) if auth_date is None else auth_date),
            "query_id": "AAE",
            "user": json.dumps(user, ensure_ascii=False, separators=(",", ":"))}
    return sign({**base, **fields}, token)


def header(uid: int = 1, token: str = TOKEN, **kw) -> dict:
    return {"Authorization": "tma " + init_data(uid, token, **kw)}
```

- [ ] **Step 2: Написать падающие тесты**

`tests/test_webauth.py`:

```python
"""Проверка подписи Telegram Mini App."""
import json
import time
import urllib.parse

import pytest

import webauth
from tma import TOKEN, init_data, sign


def test_valid_init_data_yields_the_user():
    user = webauth.verify(init_data(uid=777), TOKEN)
    assert user.id == 777
    assert user.username == "pilot"


def test_forged_hash_is_rejected():
    raw = init_data()
    tampered = raw[:-1] + ("0" if raw[-1] != "0" else "1")
    with pytest.raises(webauth.AuthError):
        webauth.verify(tampered, TOKEN)


def test_another_bots_token_is_rejected():
    with pytest.raises(webauth.AuthError):
        webauth.verify(init_data(token="43:OTHER"), TOKEN)


def test_swapped_payload_is_rejected():
    """Подменить user, оставив чужой hash, не выходит."""
    raw = init_data(uid=1)
    pairs = dict(urllib.parse.parse_qsl(raw))
    pairs["user"] = json.dumps({"id": 2, "first_name": "Чужой"}, ensure_ascii=False,
                               separators=(",", ":"))
    with pytest.raises(webauth.AuthError):
        webauth.verify(urllib.parse.urlencode(pairs), TOKEN)


def test_expired_auth_date_is_rejected():
    old = int(time.time()) - webauth.MAX_AGE_SEC - 60
    with pytest.raises(webauth.AuthError):
        webauth.verify(init_data(auth_date=old), TOKEN)


def test_auth_date_just_inside_the_window_passes():
    fresh = int(time.time()) - webauth.MAX_AGE_SEC + 60
    assert webauth.verify(init_data(auth_date=fresh), TOKEN).id == 1


def test_missing_hash_is_rejected():
    raw = urllib.parse.urlencode({"auth_date": str(int(time.time())),
                                  "user": '{"id":1}'})
    with pytest.raises(webauth.AuthError):
        webauth.verify(raw, TOKEN)


def test_empty_init_data_is_rejected():
    with pytest.raises(webauth.AuthError):
        webauth.verify("", TOKEN)


def test_missing_user_is_rejected():
    """initData без user приходит из инлайн-режима; наши эндпоинты без id
    работать не могут, и молча подставлять ноль нельзя."""
    with pytest.raises(webauth.AuthError):
        webauth.verify(sign({"auth_date": str(int(time.time())), "query_id": "AAE"}),
                       TOKEN)


def test_empty_bot_token_is_rejected():
    """Пустой BOT_TOKEN даёт формально корректный секрет, и подпись, посчитанная
    тем же пустым токеном, сошлась бы: проверка превратилась бы в театр."""
    with pytest.raises(webauth.AuthError):
        webauth.verify(init_data(token=""), "")


def test_cyrillic_values_survive_percent_encoding():
    """Имя кириллицей и пробелы в подписи — типичный случай, и именно на нём
    ломается реализация, считающая hash по закодированной строке."""
    raw = init_data(uid=5, user_extra={"first_name": "Пётр Иванович",
                                       "last_name": "фон Дер Вааль"})
    assert webauth.verify(raw, TOKEN).id == 5


def test_field_order_does_not_matter():
    """Клиент вправе прислать поля в любом порядке — сортируем мы сами."""
    raw = init_data(uid=9)
    pairs = urllib.parse.parse_qsl(raw)
    shuffled = urllib.parse.urlencode(list(reversed(pairs)))
    assert webauth.verify(shuffled, TOKEN).id == 9


def test_duplicate_key_is_rejected():
    """Второй user= после подписанного: строка подписи и разбор полей взяли бы
    разные значения, если не запретить повтор явно."""
    raw = init_data(uid=1) + "&user=" + urllib.parse.quote('{"id":2}')
    with pytest.raises(webauth.AuthError):
        webauth.verify(raw, TOKEN)


def test_unparsable_auth_date_is_rejected():
    with pytest.raises(webauth.AuthError):
        webauth.verify(sign({"auth_date": "позавчера", "user": '{"id":1}'}), TOKEN)


def test_signature_field_stays_inside_the_checked_string():
    """Telegram добавляет signature (Ed25519 для сторонней проверки). Из
    HMAC-строки исключается только hash, поэтому подпись с signature обязана
    сходиться — иначе в проде каждый запрос получит 401."""
    raw = init_data(uid=3, signature="abcdef")
    assert webauth.verify(raw, TOKEN).id == 3
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `python -m pytest tests/test_webauth.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'webauth'`

- [ ] **Step 4: Написать `webauth.py`**

```python
"""Проверка `initData` Telegram Mini App.

Модуль ничего не знает про HTTP: на входе строка запроса и токен бота, на
выходе пользователь или AuthError. Так проверку можно тестировать без
поднятого сервера, а api.py остаётся тонким.
"""
import dataclasses
import hashlib
import hmac
import json
import logging
import time
import urllib.parse

log = logging.getLogger("pgbot.webauth")

MAX_AGE_SEC = 24 * 3600


class AuthError(Exception):
    """initData не прошла проверку.

    Текст предназначен логу, а не пилоту: наружу уходит голый 401. Подробный
    ответ помогал бы подбирать подпись, а починить её пользователь всё равно
    не может.
    """


@dataclasses.dataclass(frozen=True)
class TelegramUser:
    """Только то, что нужно адаптеру. Полный объект Telegram сюда не тащим:
    лишние поля пришлось бы поддерживать при каждом изменении Bot API."""
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    language_code: str = ""


def _secret_key(bot_token: str) -> bytes:
    """HMAC_SHA256(key="WebAppData", msg=BOT_TOKEN) — порядок именно такой.

    Переставленные местами ключ и сообщение дают правдоподобные 32 байта,
    с которыми не сойдётся ни одна настоящая подпись, а отладка выглядит как
    «Telegram шлёт что-то не то».
    """
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def data_check_string(pairs: list[tuple[str, str]]) -> str:
    """Пары key=value без `hash`, по возрастанию ключа, через перевод строки.

    Значения берутся РАСКОДИРОВАННЫМИ: Telegram подписывает их до
    percent-encoding. Поле `signature` (Ed25519 для сторонней проверки) из
    строки не убирается — по документации Telegram из HMAC-строки исключается
    только `hash`.
    """
    return "\n".join(f"{k}={v}" for k, v in sorted(pairs, key=lambda kv: kv[0])
                     if k != "hash")


def verify(raw: str, bot_token: str, *, max_age_sec: int = MAX_AGE_SEC,
           now: float | None = None) -> TelegramUser:
    """Разобрать и проверить initData. AuthError — единственный способ отказа."""
    if not raw:
        raise AuthError("пустая initData")
    if not bot_token:
        # Пустой токен даёт формально корректный секрет, и подпись, посчитанная
        # тем же пустым токеном, сошлась бы: проверка стала бы декорацией.
        raise AuthError("BOT_TOKEN не задан — проверять подпись нечем")

    pairs = urllib.parse.parse_qsl(raw, keep_blank_values=True)
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        # Повтор ключа развёл бы строку подписи и разбор полей: dict() взял бы
        # последнее значение, а в HMAC ушли бы оба.
        raise AuthError("повторяющийся ключ в initData")
    fields = dict(pairs)

    got = fields.get("hash")
    if not got:
        raise AuthError("в initData нет hash")
    expected = hmac.new(_secret_key(bot_token),
                        data_check_string(pairs).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, got):
        raise AuthError("подпись не сходится")

    try:
        auth_date = int(fields.get("auth_date", ""))
    except ValueError:
        raise AuthError("auth_date не число") from None
    age = (time.time() if now is None else now) - auth_date
    if age > max_age_sec:
        raise AuthError(f"initData просрочена: {age / 3600:.1f} ч")

    try:
        u = json.loads(fields.get("user", ""))
        uid = int(u["id"])
    except (ValueError, TypeError, KeyError) as e:
        # initData без user приходит из инлайн-режима: там подписан receiver,
        # а не отправитель. Нашим эндпоинтам без id делать нечего.
        raise AuthError(f"в initData нет пригодного user ({e})") from None

    return TelegramUser(id=uid,
                        first_name=u.get("first_name") or "",
                        last_name=u.get("last_name") or "",
                        username=u.get("username") or "",
                        language_code=u.get("language_code") or "")
```

- [ ] **Step 5: Тесты проходят**

Run: `python -m pytest tests/test_webauth.py -q`
Expected: PASS, 15 тестов.

- [ ] **Step 6: Полный прогон**

Run: `python -m pytest -q`
Expected: 846 + 15 = 861 passed.

- [ ] **Step 7: Коммит**

```bash
git add webauth.py tests/tma.py tests/test_webauth.py
git commit -m "feat(webauth): проверка подписи initData отдельно от HTTP"
```

---

### Task 2: `api.py` — каркас, авторизация, `/api/prefs`

Первый эндпоинт выбран не случайно: `/api/prefs` прогоняет всю цепочку (заголовок → подпись → allowlist → `store`) и не ходит в сеть, поэтому его тесты проверяют именно авторизацию.

**Files:**
- Create: `api.py`
- Create: `tests/test_api_auth.py`
- Create: `tests/test_api_prefs.py`
- Modify: `requirements.txt`
- Modify: `guards.py` (переименование `_allowed_ids` → `allowed_ids`, разовое предупреждение)
- Modify: `bot.py:1291` (вызов переименованной функции)
- Modify: `tests/conftest.py` (фикстура HTTP-клиента)

**Interfaces:**
- Consumes: `webauth.verify`, `webauth.AuthError`, `webauth.TelegramUser` (Task 1); `store.prefs/set_speed/set_wind_correction/set_model`; `engine.MODELS`, `engine.model_label`.
- Produces: `api.app` (FastAPI), `api.router`, `api.current_user` (зависимость), `api.PREFS_FIELDS`; `guards.allowed_ids()`; фикстура `client` в `tests/conftest.py`.

- [ ] **Step 1: Добавить зависимости**

`requirements.txt` — дописать в конец:

```
fastapi>=0.110
uvicorn>=0.29
```

`pydantic` не указываем: он приходит требованием FastAPI, и вторая, независимая версия в списке рано или поздно разойдётся с первой.

Run: `pip install -r requirements.txt`

- [ ] **Step 2: Написать падающие тесты авторизации**

`tests/test_api_auth.py`:

```python
"""Ворота HTTP-поверхности: подпись и список допущенных."""
import time

import pytest

from tma import TOKEN, header, init_data


async def test_valid_init_data_gets_through(client):
    r = await client.get("/api/prefs", headers=header(uid=1))
    assert r.status_code == 200


async def test_missing_header_is_401(client):
    assert (await client.get("/api/prefs")).status_code == 401


async def test_wrong_scheme_is_401(client):
    """Bearer <initData> — типичная ошибка клиента; молча принимать её нельзя,
    иначе схема авторизации перестаёт что-либо значить."""
    r = await client.get("/api/prefs",
                         headers={"Authorization": "Bearer " + init_data()})
    assert r.status_code == 401


async def test_forged_hash_is_401(client):
    raw = init_data()
    bad = raw[:-1] + ("0" if raw[-1] != "0" else "1")
    r = await client.get("/api/prefs", headers={"Authorization": "tma " + bad})
    assert r.status_code == 401


async def test_expired_auth_date_is_401(client):
    old = int(time.time()) - 25 * 3600
    r = await client.get("/api/prefs", headers=header(auth_date=old))
    assert r.status_code == 401


async def test_401_does_not_explain_why(client):
    """Причина отказа уходит в лог. Ответ, объясняющий «просрочено» против
    «подпись не сошлась», помогает подбирать подпись."""
    raw = init_data()
    bad = raw[:-1] + ("0" if raw[-1] != "0" else "1")
    r = await client.get("/api/prefs", headers={"Authorization": "tma " + bad})
    body = r.text.lower()
    assert "подпись" not in body and "просроч" not in body


async def test_user_outside_the_allowlist_is_403(client, allowlist):
    allowlist("1")
    r = await client.get("/api/prefs", headers=header(uid=2))
    assert r.status_code == 403
    assert "2" in r.text, "пилот должен увидеть свой id, чтобы попросить доступ"


async def test_user_inside_the_allowlist_passes(client, allowlist):
    allowlist("1,2")
    assert (await client.get("/api/prefs", headers=header(uid=2))).status_code == 200


async def test_empty_allowlist_lets_everyone_in(client, allowlist):
    """Открытый режим — тот же, что у бота: пустой список никого не отсекает."""
    allowlist("")
    assert (await client.get("/api/prefs", headers=header(uid=99))).status_code == 200


async def test_the_api_uses_the_same_allowlist_as_the_bot(client, allowlist):
    """Два независимых списка разъехались бы в первый же день: пилота добавили
    в бот, а приложение его не пускает."""
    import guards
    allowlist("7")
    assert guards.allowed_ids() == frozenset({7})
    assert (await client.get("/api/prefs", headers=header(uid=7))).status_code == 200
```

`tests/test_api_prefs.py`:

```python
"""Личные настройки через HTTP."""
import pytest

import store
from conftest import TEST_USER_ID
from tma import header


async def test_defaults_for_a_pilot_who_never_changed_anything(client):
    r = await client.get("/api/prefs", headers=header(uid=1))
    body = r.json()
    assert body["avg_route_speed_kmh"] == store.DEFAULT_PREFS.avg_route_speed_kmh
    assert body["wind_correction_enabled"] is True
    assert body["model_key"] == store.DEFAULT_PREFS.model_key


async def test_reading_prefs_creates_no_row(client):
    """Новый пилот ничего не регистрирует, чтобы посмотреть прогноз."""
    await client.get("/api/prefs", headers=header(uid=555))
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM user_prefs").fetchone()["c"] == 0


async def test_prefs_carry_the_model_list(client):
    """Список моделей приезжает вместе с настройками, а не отдельным запросом:
    выбиралка модели без подписей — это ключи вроде «icon» на экране."""
    body = (await client.get("/api/prefs", headers=header())).json()
    keys = [m["key"] for m in body["models"]]
    assert keys == ["auto", "ecmwf", "gfs", "icon"]
    assert all(m["label"] for m in body["models"])


async def test_patch_speed(client):
    r = await client.patch("/api/prefs", json={"avg_route_speed_kmh": 32.0},
                           headers=header(uid=1))
    assert r.status_code == 200
    assert store.prefs(1).avg_route_speed_kmh == 32.0
    assert r.json()["avg_route_speed_kmh"] == 32.0, "ответ должен нести новое значение"


async def test_patch_wind_correction(client):
    await client.patch("/api/prefs", json={"wind_correction_enabled": False},
                       headers=header(uid=1))
    assert store.prefs(1).wind_correction_enabled is False


async def test_patch_model(client):
    await client.patch("/api/prefs", json={"model_key": "ecmwf"}, headers=header(uid=1))
    assert store.prefs(1).model_key == "ecmwf"


async def test_patch_touches_only_what_was_sent(client):
    """PATCH, а не PUT: приложение меняет один тумблер и не обязано присылать
    остальные — иначе оно молча затрёт их дефолтами."""
    store.set_speed(1, 30.0)
    await client.patch("/api/prefs", json={"model_key": "gfs"}, headers=header(uid=1))
    assert store.prefs(1).avg_route_speed_kmh == 30.0


async def test_speed_outside_the_range_is_400_with_the_domain_text(client):
    r = await client.patch("/api/prefs", json={"avg_route_speed_kmh": 500.0},
                           headers=header(uid=1))
    assert r.status_code == 400
    assert "скорость крыла" in r.text, "текст store уже написан для пилота"
    assert store.prefs(1).avg_route_speed_kmh == store.DEFAULT_PREFS.avg_route_speed_kmh


async def test_unknown_model_is_400(client):
    r = await client.patch("/api/prefs", json={"model_key": "нет-такой"},
                           headers=header(uid=1))
    assert r.status_code == 400
    assert store.prefs(1).model_key == store.DEFAULT_PREFS.model_key


async def test_a_rejected_patch_saves_nothing_at_all(client):
    """400 означает «не сохранилось ничего». Запись по мере разбора успевала
    сохранить скорость и падала на модели: ответ говорил «не принято», а
    половина настроек уже поменялась."""
    r = await client.patch("/api/prefs",
                           json={"avg_route_speed_kmh": 33.0,
                                 "wind_correction_enabled": False,
                                 "model_key": "нет-такой"},
                           headers=header(uid=1))
    assert r.status_code == 400
    p = store.prefs(1)
    assert p.avg_route_speed_kmh == store.DEFAULT_PREFS.avg_route_speed_kmh
    assert p.wind_correction_enabled is store.DEFAULT_PREFS.wind_correction_enabled


async def test_a_rejected_speed_leaves_the_other_fields_alone(client):
    """Вторая половина того же: падает не модель, а скорость."""
    r = await client.patch("/api/prefs",
                           json={"avg_route_speed_kmh": 500.0, "model_key": "gfs"},
                           headers=header(uid=1))
    assert r.status_code == 400
    assert store.prefs(1).model_key == store.DEFAULT_PREFS.model_key


async def test_prefs_are_personal(client):
    await client.patch("/api/prefs", json={"model_key": "icon"}, headers=header(uid=1))
    body = (await client.get("/api/prefs", headers=header(uid=2))).json()
    assert body["model_key"] == store.DEFAULT_PREFS.model_key, "настройки соседа"
```

- [ ] **Step 3: Добавить фикстуры в `tests/conftest.py`**

Дописать в конец файла:

```python
@pytest.fixture()
async def client():
    """HTTP-клиент поверх ASGI-приложения: без сокета и свободного порта.

    Импорт api откладывается до вызова фикстуры — модуль тянет FastAPI, и
    падение импорта не должно ронять сбор тестов, которые до API не касаются.
    """
    import httpx

    import api
    transport = httpx.ASGITransport(app=api.app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://test") as c:
        yield c


@pytest.fixture()
def allowlist(monkeypatch):
    """Переписать ALLOWED_USER_IDS на время теста.

    guards.allowed_ids() читает окружение на каждом вызове, поэтому
    достаточно подменить переменную.
    """
    def _set(value: str):
        monkeypatch.setenv("ALLOWED_USER_IDS", value)
    return _set
```

`fresh_state` в этой задаче не трогаем: сбрасывать пока нечего. Реестр in-flight и его сброс появятся в задаче 7.

- [ ] **Step 4: Убедиться, что тесты падают**

Run: `python -m pytest tests/test_api_auth.py tests/test_api_prefs.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'api'`

- [ ] **Step 5: Сделать `guards.allowed_ids` публичной**

В `guards.py` заменить функцию:

```python
_warned_open = False


def allowed_ids() -> frozenset[int]:
    """Кому можно — общий список для чата и приложения.

    Публичная: зовут три модуля (middleware, bootstrap хранилища, HTTP-слой),
    и подчёркивание в чужом импорте означало бы, что граница проведена не там.

    Предупреждение об открытом режиме печатается один раз за процесс: HTTP-слой
    зовёт эту функцию на каждый запрос, и построчный вой в логе утопил бы всё
    остальное.
    """
    global _warned_open
    raw = os.environ.get("ALLOWED_USER_IDS", "")
    ids = frozenset(int(p) for p in raw.replace(";", ",").split(",") if p.strip())
    if not ids and not _warned_open:
        _warned_open = True
        log.warning("ALLOWED_USER_IDS не задан — бот открыт для ВСЕХ пользователей")
    return ids
```

В `guards.py:40` — `self.allowed = allowed_ids()`.
В `bot.py:1291` — `store.bootstrap(data_dir, guards.allowed_ids(), ...)`.

- [ ] **Step 6: Написать `api.py`**

```python
"""HTTP-поверхность мини-приложения.

Домен тот же, что у бота, — другой только источник `user_id`: бот берёт его из
апдейта, api из подписанной initData. Расчётов здесь нет: разбор запроса,
резолв личных настроек, вызов forecast и перевод исключений в коды.
"""
import logging
import os

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import engine
import forecast
import guards
import route
import store
import webauth

log = logging.getLogger("pgbot.api")

# Схема наружу не публикуется: единственный клиент — наше же приложение,
# а открытый /docs на публичном домене показывает всю поверхность чужим.
app = FastAPI(title="pgbot mini app", docs_url=None, redoc_url=None, openapi_url=None)
router = APIRouter(prefix="/api")


async def current_user(authorization: str = Header(default="")) -> webauth.TelegramUser:
    """Пилот за этим запросом. Каждый запрос проверяется заново — сессий нет.

    Причина отказа уходит в лог, а не в ответ: подробность вида «просрочено»
    против «подпись не сошлась» помогает подбирать подпись.
    """
    scheme, _, raw = authorization.partition(" ")
    if scheme.lower() != "tma" or not raw:
        raise HTTPException(401, "нужна авторизация Telegram Mini App")
    try:
        user = webauth.verify(raw, os.environ.get("BOT_TOKEN", ""))
    except webauth.AuthError as e:
        log.info("initData отклонена: %s", e)
        raise HTTPException(401, "initData не прошла проверку") from None

    allowed = guards.allowed_ids()
    if allowed and user.id not in allowed:
        raise HTTPException(
            403, f"Это личный бот, доступ по списку. Твой Telegram ID: {user.id} — "
                 "пришли его владельцу бота, чтобы тебя добавили.")
    return user


# ------------------------------------------------------------------ ошибки
@app.exception_handler(forecast.ForecastError)
async def _forecast_error(_request, exc: forecast.ForecastError):
    """400 с текстом как есть: сообщения ForecastError уже написаны пилоту."""
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(route.RouteError)
async def _route_error(_request, exc: route.RouteError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(httpx.HTTPError)
async def _upstream_error(_request, exc: httpx.HTTPError):
    """502. Текст наружу не отдаём: в нём бывает URL запроса целиком."""
    log.warning("upstream: %s", exc)
    return JSONResponse({"detail": "Метеосервис недоступен, попробуй позже."},
                        status_code=502)


# ------------------------------------------------------------------ настройки
def _prefs_payload(uid: int) -> dict:
    p = store.prefs(uid)
    return {"avg_route_speed_kmh": p.avg_route_speed_kmh,
            "wind_correction_enabled": p.wind_correction_enabled,
            "model_key": p.model_key,
            # Список моделей едет вместе с настройками, а не отдельным
            # эндпоинтом: выбиралка без подписей показала бы пилоту ключи.
            "models": [{"key": k, "label": engine.model_label(k)} for k in engine.MODELS]}


class PrefsPatch(BaseModel):
    """Все поля необязательные: приложение меняет один тумблер и не обязано
    присылать остальные, иначе оно молча затрёт их дефолтами."""
    avg_route_speed_kmh: float | None = None
    wind_correction_enabled: bool | None = None
    model_key: str | None = None


@router.get("/prefs")
async def read_prefs(user: webauth.TelegramUser = Depends(current_user)):
    return _prefs_payload(user.id)


@router.patch("/prefs")
async def update_prefs(body: PrefsPatch,
                       user: webauth.TelegramUser = Depends(current_user)):
    """Порядок операций держит запрос неделимым: 400 означает, что не
    сохранилось НИЧЕГО.

    Проверка ключа модели идёт первой и ничего не пишет. `set_speed` —
    единственная запись, способная бросить исключение, поэтому она вторая:
    к моменту, когда пишутся остальные поля, упасть уже нечему. Порядок
    «пишем по мере разбора» сохранял бы скорость и уходил с 400 из-за
    модели — ответ говорил бы «не принято», а половина настроек уже
    поменялась.
    """
    # Список моделей — знание домена: store ключ не проверяет намеренно.
    if body.model_key is not None and body.model_key not in engine.MODELS:
        raise HTTPException(400, f"неизвестная модель: {body.model_key}")
    if body.avg_route_speed_kmh is not None:
        try:
            store.set_speed(user.id, body.avg_route_speed_kmh)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
    if body.wind_correction_enabled is not None:
        store.set_wind_correction(user.id, body.wind_correction_enabled)
    if body.model_key is not None:
        store.set_model(user.id, body.model_key)
    return _prefs_payload(user.id)


app.include_router(router)
```

- [ ] **Step 7: Тесты проходят**

Run: `python -m pytest tests/test_api_auth.py tests/test_api_prefs.py -q`
Expected: PASS, 22 теста.

- [ ] **Step 8: Полный прогон**

Run: `python -m pytest -q`
Expected: 883 passed.

- [ ] **Step 9: Коммит**

```bash
git add api.py requirements.txt guards.py bot.py tests/conftest.py \
        tests/test_api_auth.py tests/test_api_prefs.py
git commit -m "feat(api): каркас FastAPI, авторизация по initData, /api/prefs"
```

---

### Task 3: `/api/sites` и `/api/elevation`

**Files:**
- Modify: `api.py`
- Create: `tests/test_api_sites.py`

**Interfaces:**
- Consumes: `store.load_sites/find_site/add_site/remove_site`; `forecast.fetch_elevation`; `api.current_user` (Task 2).
- Produces: `GET|POST /api/sites`, `DELETE /api/sites/{name}`, `POST /api/elevation`.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_api_sites.py`:

```python
"""Общая библиотека стартов через HTTP."""
import pytest

import store
from conftest import DEFAULT_SITES
from tma import header

NEW = {"name": "Казбеги", "lat": 42.66, "lon": 44.64, "elevation_m": 1750,
       "aspect": "Ю", "aspect_deg": 180.0, "aliases": ["kazbegi"], "notes": ""}


async def test_sites_lists_the_shared_library(client):
    body = (await client.get("/api/sites", headers=header())).json()
    assert [s["name"] for s in body] == [s["name"] for s in DEFAULT_SITES]


async def test_the_library_is_the_same_for_everyone(client):
    """Старты общие по решению: два пилота видят одно и то же."""
    a = (await client.get("/api/sites", headers=header(uid=1))).json()
    b = (await client.get("/api/sites", headers=header(uid=2))).json()
    assert a == b


async def test_add_a_site(client):
    r = await client.post("/api/sites", json=NEW, headers=header(uid=1))
    assert r.status_code == 201
    assert store.find_site("Казбеги") is not None


async def test_added_site_remembers_who_added_it(client):
    await client.post("/api/sites", json=NEW, headers=header(uid=77))
    with store.connect() as conn:
        row = conn.execute("SELECT added_by FROM sites WHERE name = ?",
                           ("Казбеги",)).fetchone()
    assert row["added_by"] == 77


async def test_adding_a_duplicate_name_is_409(client):
    await client.post("/api/sites", json=NEW, headers=header())
    r = await client.post("/api/sites", json=NEW, headers=header())
    assert r.status_code == 409


async def test_a_site_can_be_found_by_alias(client):
    body = (await client.get("/api/sites/гуда", headers=header())).json()
    assert body["name"] == "Гудаури"


async def test_unknown_site_is_404(client):
    assert (await client.get("/api/sites/нетутакого",
                             headers=header())).status_code == 404


async def test_delete_a_site(client):
    r = await client.delete("/api/sites/Гудаури", headers=header())
    assert r.status_code == 204
    assert store.find_site("Гудаури") is None


async def test_deleting_an_unknown_site_is_404(client):
    """204 на несуществующее имя соврал бы: пилот решил бы, что удалил старт,
    а на деле опечатался."""
    assert (await client.delete("/api/sites/нетутакого",
                                headers=header())).status_code == 404


async def test_a_site_name_that_breaks_buttons_is_400(client):
    """Имя приезжает в callback_data бота, у которой потолок 64 байта.
    Приложение и чат делят одну библиотеку, поэтому потолок общий."""
    r = await client.post("/api/sites", json={**NEW, "name": "я" * 40},
                          headers=header())
    assert r.status_code == 400
    assert store.load_sites() and len(store.load_sites()) == len(DEFAULT_SITES)


async def test_a_pipe_in_the_name_is_400(client):
    """`|` — разделитель полей в callback_data. Старт с таким именем не падает
    и не ругается: _split_cb получает лишнее поле, возвращает (None, None), и
    кнопки под этим стартом молча перестают работать навсегда."""
    r = await client.post("/api/sites", json={**NEW, "name": "Каз|беги"},
                          headers=header())
    assert r.status_code == 400
    assert store.find_site("Каз|беги") is None


async def test_elevation_by_coordinates(client, elevation):
    r = await client.post("/api/elevation", json={"lat": 42.5, "lon": 44.5},
                          headers=header())
    assert r.json()["elevation_m"] == 1234


async def test_elevation_needs_authorization(client, elevation):
    assert (await client.post("/api/elevation",
                              json={"lat": 42.5, "lon": 44.5})).status_code == 401
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `python -m pytest tests/test_api_sites.py -q`
Expected: FAIL, 404 на каждом эндпоинте (маршрутов ещё нет).

- [ ] **Step 3: Перенести проверку имени старта в `store.py`**

`bot.py:142-148` держит **два** правила, а не одно:

```python
def name_error(name: str) -> str | None:
    """Why a site name can't live inside inline-button callback_data, or None if it can."""
    if "|" in name:
        return "Имя не должно содержать символ «|»."
    if len(name.encode("utf-8")) > _NAME_MAX_BYTES:
        return "Слишком длинное имя — не влезет в кнопки Telegram. До ~20 символов, короче?"
    return None
```

Оба ограничения живут в чате, но относятся к **данным**: библиотека стартов общая, и имя, добавленное из приложения, обязано влезать в кнопку бота и не ломать её разбор. Переносить надо **всю функцию целиком**, а не одну константу: `_split_cb` (`bot.py:166`) режет `callback_data` по `|` и рассчитывает на фиксированное число полей. Имя с `|` даёт неверное число полей, `_split_cb` возвращает `(None, None)`, и кнопка навсегда молча перестаёт работать — без ошибки, без падения, просто ничего не происходит.

Перенести в `store.py`, рядом с `add_site`:

```python
# Имя уезжает в callback_data бота: "deep|" + name + "|2weeks|YYYY-MM-DD"
# должно уместиться в 64 байта, а поля режутся по «|». Ограничения чата, но
# проверять их обязаны обе поверхности — библиотека стартов общая, и старт,
# заведённый из приложения, ломал бы кнопки бота.
NAME_MAX_BYTES = 40


def name_error(name: str) -> str | None:
    """Почему имя не годится для callback_data, или None если годится.

    Одна функция на оба адаптера. Разнесённые проверки разъехались бы при
    первой правке, и приложение завело бы старт, невидимый для кнопок чата.
    """
    if "|" in name:
        return "Имя не должно содержать символ «|»."
    if len(name.encode("utf-8")) > NAME_MAX_BYTES:
        return "Слишком длинное имя — не влезет в кнопки Telegram. До ~20 символов, короче?"
    return None
```

В `bot.py` удалить определение `name_error` и `_NAME_MAX_BYTES`, а все обращения перевести на `store.name_error`.

Run: `grep -n "_NAME_MAX_BYTES\|def name_error" bot.py tests/*.py`
Expected после правки: пусто.

Тексты сообщений не меняются: обе поверхности обязаны объяснять отказ одинаково.

- [ ] **Step 4: Дописать эндпоинты в `api.py`**

```python
# ------------------------------------------------------------------ старты
class SiteIn(BaseModel):
    """Поля повторяют колонки store._SITE_COLUMNS, кроме added_by — его
    подставляет сервер из подписи, а не клиент из тела запроса."""
    name: str
    lat: float
    lon: float
    elevation_m: int
    aspect: str | None = None
    aspect_deg: float | None = None
    slope_deg: float | None = None
    route_top_m: float | None = None
    aliases: list[str] = []
    notes: str = ""


class Coords(BaseModel):
    lat: float
    lon: float


@router.get("/sites")
async def list_sites(_user: webauth.TelegramUser = Depends(current_user)):
    """Библиотека общая, поэтому ответ не зависит от пилота. Зависимость
    оставлена: неавторизованный запрос не должен получать список стартов."""
    return store.load_sites()


@router.get("/sites/{name}")
async def read_site(name: str, _user: webauth.TelegramUser = Depends(current_user)):
    site = store.find_site(name)
    if site is None:
        raise HTTPException(404, f"старт не найден: {name}")
    return site


@router.post("/sites", status_code=201)
async def create_site(body: SiteIn, user: webauth.TelegramUser = Depends(current_user)):
    site = body.model_dump()
    # Правило одно на оба адаптера: см. store.name_error
    bad = store.name_error(site["name"])
    if bad:
        raise HTTPException(400, bad)
    if store.find_site(site["name"]) is not None:
        raise HTTPException(409, f"Старт «{site['name']}» уже есть.")
    try:
        store.add_site(site, added_by=user.id)
    except sqlite3.IntegrityError:
        # Гонка двух добавлений одного имени: проверка выше не атомарна.
        # Сообщение своё, а не str(e): текст SQLite («UNIQUE constraint failed:
        # sites.name») написан для разработчика и наружу не идёт — ровно по той
        # же причине, по которой обработчик httpx не отдаёт текст ошибки.
        raise HTTPException(409, f"Старт «{site['name']}» уже есть.") from None
    return store.find_site(site["name"])


@router.delete("/sites/{name}", status_code=204)
async def delete_site(name: str, _user: webauth.TelegramUser = Depends(current_user)):
    site = store.find_site(name)
    if site is None:
        # 204 на опечатку соврал бы: пилот решил бы, что удалил старт
        raise HTTPException(404, f"старт не найден: {name}")
    store.remove_site(site["name"])
    return None


@router.post("/elevation")
async def elevation(body: Coords, _user: webauth.TelegramUser = Depends(current_user)):
    """Высота точки — для формы добавления старта."""
    return {"elevation_m": await forecast.fetch_elevation(body.lat, body.lon)}
```

`import bot` в `api.py` **недопустим**: `bot.py` создаёт `Dispatcher` на импорте и затащил бы aiogram в HTTP-слой. Отсюда перенос константы в `store.py` на шаге 3.

Добавить `import sqlite3` в начало `api.py`.

- [ ] **Step 5: Тесты проходят**

Run: `python -m pytest tests/test_api_sites.py -q`
Expected: PASS, 13 тестов.

- [ ] **Step 6: Полный прогон**

Run: `python -m pytest -q`
Expected: 896 passed, ни один тест бота не сломан переносом константы.

- [ ] **Step 7: Коммит**

```bash
git add api.py store.py bot.py tests/test_api_sites.py
git commit -m "feat(api): библиотека стартов и высота по координатам"
```

---

### Task 4: `/api/forecast`, `/api/forecast/wind-grid`, `/api/scan`

**Files:**
- Modify: `forecast.py` (добавить `wind_grid_data`)
- Modify: `api.py`
- Create: `tests/test_api_forecast.py`
- Modify: `tests/test_lazy_cache.py` (тест на общий кэш двух поверхностей)

**Interfaces:**
- Consumes: `forecast.get_facts(site, rng, date, *, model)`, `forecast.scan_week(*, model)`, `forecast._resolve`, `forecast._ensure`, `forecast._derive`.
- Produces: `forecast.wind_grid_data(site_name, date, *, model) -> dict`; `GET /api/forecast`, `GET /api/forecast/wind-grid`, `GET /api/scan`.

- [ ] **Step 1: Написать падающий тест на данные сетки ветра**

Дописать в `tests/test_lazy_cache.py`:

Файл уже импортирует `charts`, `forecast` и `from fixtures import DATE, om_1day`, и уже держит фикстуру `net` (подменяет `forecast._fetch_main` и считает обращения). Новые тесты пользуются ими же.

```python
async def test_wind_grid_data_returns_numbers_not_a_picture(net, monkeypatch):
    """Приложение рисует графики само. get_wind_grid отдаёт PNG — он остаётся
    чату; для HTTP нужен тот же словарь до отрисовки."""
    drawn = []
    monkeypatch.setattr(charts, "wind_grid_png",
                        lambda *a, **kw: drawn.append(1) or "/dev/null")

    grid = await forecast.wind_grid_data("Гудаури", DATE, model="auto")

    assert not drawn, "числа не должны стоить отрисовки PNG"
    assert grid["hours"], "часы светового дня"
    assert grid["levels"][0]["hourly"][0]["wind_ms"] is not None


async def test_wind_grid_png_and_data_share_the_warm_cache(net, monkeypatch):
    """Кнопка в чате и экран в приложении не должны стоить двух запросов
    к open-meteo: сетка берётся из того же тёплого кэша 1d."""
    monkeypatch.setattr(charts, "wind_grid_png", lambda *a, **kw: "/dev/null")
    monkeypatch.setattr(pathlib.Path, "read_bytes", lambda self: b"png")

    await forecast.wind_grid_data("Гудаури", DATE, model="auto")
    await forecast.get_wind_grid("Гудаури", DATE, model="auto")

    assert len(net) == 1, f"сходили в сеть {len(net)} раза вместо одного"


async def test_wind_grid_png_works_for_an_adhoc_point(net, monkeypatch):
    """Разовая точка по координатам — не запись в библиотеке стартов, а строка
    в adhoc. Резолв только через find_site теряет её: сетка успевала
    посчитаться и падала на отрисовке, уже сходив в сеть."""
    monkeypatch.setattr(charts, "wind_grid_png", lambda *a, **kw: "/dev/null")
    monkeypatch.setattr(pathlib.Path, "read_bytes", lambda self: b"png")
    name = forecast.register_adhoc(42.5, 44.5, 2000)

    assert await forecast.get_wind_grid(name, DATE, model="auto") == b"png"
```

Добавить `import pathlib` в начало файла, если его там ещё нет.

- [ ] **Step 2: Убедиться, что тест падает**

Run: `python -m pytest tests/test_lazy_cache.py -q`
Expected: FAIL, `AttributeError: module 'forecast' has no attribute 'wind_grid_data'`

- [ ] **Step 3: Добавить `wind_grid_data` в `forecast.py`**

Вставить перед `get_wind_grid`:

```python
async def wind_grid_data(site_name: str, date: str, *, model) -> dict:
    """Сетка «высота × час» числами. Тот же тёплый кэш 1d, что у карточки.

    get_wind_grid отдаёт PNG для чата; приложение рисует сетку само, и
    гонять картинку туда, где нужны числа, значит считать одно и то же
    дважды — и разойтись в оформлении с остальными графиками приложения.
    """
    site, date, key = _resolve(site_name, "1d", date, model)
    data, assessment, derived = await _ensure(site, "1d", date, key, model)
    grid = _derive(site, "1d", data, assessment, derived, "grid")
    if not grid:
        raise ForecastError("Данные по высотам недоступны для этого дня.")
    return grid
```

И переписать `get_wind_grid`, чтобы он **звал** новую функцию, а не повторял её тело:

```python
async def get_wind_grid(site_name: str, date: str, *, model) -> bytes:
    """PNG сетки для чата. Данные берутся общей функцией: две независимые
    выборки уровней разъехались бы при первой правке фильтра."""
    grid = await wind_grid_data(site_name, date, model=model)
    out = tempfile.mkdtemp(prefix="pgwg_")
    try:
        import charts
        return pathlib.Path(charts.wind_grid_png(grid, site, out)).read_bytes()
    finally:
        shutil.rmtree(out, ignore_errors=True)
```

Внимание: `charts.wind_grid_png(grid, site, out)` нуждается в `site`, а после рефакторинга он в этой функции не резолвится. Вернуть его из `wind_grid_data` нельзя — там контракт «словарь сетки».

Резолвить старт **отдельной строкой `store.find_site(site_name)` нельзя**: `_resolve` (`forecast.py:173`) делает это иначе —

```python
site = store.find_site(site_name) or store.adhoc_get(site_name)
```

Разовые точки по координатам живут в `adhoc`: пилот шлёт боту координаты, `register_adhoc` кладёт точку туда, и она становится обычным «стартом» для прогноза. С резолвом только через `find_site` такая точка успешно посчиталась бы в `wind_grid_data` и упала бы строкой ниже, уже после запроса к сети, — «Ветер по высотам» под карточкой по координатам перестал бы работать.

Поэтому резолв имени выносится в одну функцию, и обе стороны зовут её:

```python
def site_by_name(site_name: str):
    """Старт по имени: сохранённый в библиотеке или разовая точка по координатам.

    Одна функция на всех, кто резолвит имя, и публичная намеренно: её зовёт
    и HTTP-слой. Вторая строка `find_site(...)` где-нибудь ещё молча теряла
    бы разовые точки — и обнаружилось бы это не падением, а тем, что кнопка
    под карточкой по координатам не работает.

    Что считается стартом для прогноза — знание forecast, а не хранилища:
    `store` про разовые точки знает, но не знает, что они равноправны
    сохранённым.
    """
    return store.find_site(site_name) or store.adhoc_get(site_name)
```

`_resolve` переходит на неё, `get_wind_grid` тоже:

```python
    site = site_by_name(site_name)
    if site is None:
        raise ForecastError(f"Старт не найден: {site_name}. /sites — список.")
```

**Та же функция обязательна и в `api.py`** (задача 4, шаг 6): `_site_or_404` — третье место, где резолвится имя, и `store.find_site` там означал бы 404 на законную точку по координатам ещё до вызова домена.

Существующие тесты `get_wind_grid` обязаны остаться зелёными без правок.

- [ ] **Step 4: Тесты кэша проходят**

Run: `python -m pytest tests/test_lazy_cache.py -q`
Expected: PASS

- [ ] **Step 5: Написать падающие тесты эндпоинтов**

`tests/test_api_forecast.py`:

```python
"""Прогноз, сетка ветра и скан через HTTP."""
import datetime as dt

import pytest

import forecast
import store
from tma import header

TODAY = dt.date.today().isoformat()


@pytest.fixture()
def facts(monkeypatch):
    """Патчим get_facts: сам расчёт покрыт тестами домена, здесь проверяется
    адаптер — что доехало до вызова и что вернулось наружу."""
    calls = []

    async def fake(site, rng, date=None, *, model):
        calls.append((site, rng, date, model))
        return {"site": {"name": site}, "date": date or TODAY, "range": rng,
                "hourly_daytime": [{"time": "13:00", "temp_c": 21.0}]}

    monkeypatch.setattr(forecast, "get_facts", fake)
    return calls


async def test_forecast_returns_numbers(client, facts):
    body = (await client.get("/api/forecast?site=Гудаури&range=1d",
                             headers=header())).json()
    assert body["hourly_daytime"][0]["temp_c"] == 21.0


async def test_forecast_uses_the_pilots_permanent_model(client, facts):
    store.set_model(1, "ecmwf")
    await client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1))
    assert facts[-1][3] == "ecmwf"


async def test_query_model_overrides_the_permanent_one(client, facts):
    store.set_model(1, "ecmwf")
    await client.get("/api/forecast?site=Гудаури&range=1d&model=gfs",
                     headers=header(uid=1))
    assert facts[-1][3] == "gfs"


async def test_query_model_does_not_persist(client, facts):
    """Кнопка модели под прогнозом — разовый выбор, как в чате: она не должна
    менять постоянную настройку пилота."""
    store.set_model(1, "ecmwf")
    await client.get("/api/forecast?site=Гудаури&range=1d&model=gfs",
                     headers=header(uid=1))
    assert store.prefs(1).model_key == "ecmwf"


async def test_unknown_query_model_is_400(client, facts):
    r = await client.get("/api/forecast?site=Гудаури&range=1d&model=нет",
                         headers=header())
    assert r.status_code == 400
    assert not facts, "неизвестная модель не должна доехать до домена"


async def test_two_pilots_get_their_own_models(client, facts):
    store.set_model(1, "ecmwf")
    store.set_model(2, "icon")
    await client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1))
    await client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=2))
    assert [c[3] for c in facts] == ["ecmwf", "icon"]


async def test_unknown_site_is_404(client):
    r = await client.get("/api/forecast?site=нетутакого&range=1d", headers=header())
    assert r.status_code == 404


async def test_bad_range_is_400_with_the_domain_text(client, monkeypatch):
    async def boom(site, rng, date=None, *, model):
        raise forecast.ForecastError("Диапазон не понят: 5d")

    monkeypatch.setattr(forecast, "get_facts", boom)
    r = await client.get("/api/forecast?site=Гудаури&range=5d", headers=header())
    assert r.status_code == 400
    assert "5d" in r.json()["detail"]


async def test_upstream_failure_is_502(client, monkeypatch):
    import httpx

    async def boom(site, rng, date=None, *, model):
        raise httpx.ConnectError("open-meteo down")

    monkeypatch.setattr(forecast, "get_facts", boom)
    r = await client.get("/api/forecast?site=Гудаури&range=1d", headers=header())
    assert r.status_code == 502
    assert "open-meteo down" not in r.text, "внутренности наружу не отдаём"


async def test_wind_grid_returns_levels(client, monkeypatch):
    async def fake(site, date, *, model):
        return {"date": date, "launch_m": 2200, "hours": [10, 11],
                "levels": [{"label": "10m", "alt_m_msl": 2210, "is_launch": True,
                            "hourly": [{"hour": 10, "wind_ms": 3.0, "dir_deg": 180}]}]}

    monkeypatch.setattr(forecast, "wind_grid_data", fake)
    body = (await client.get(f"/api/forecast/wind-grid?site=Гудаури&date={TODAY}",
                             headers=header())).json()
    assert body["levels"][0]["hourly"][0]["wind_ms"] == 3.0


async def test_scan_returns_flyable_days(client, monkeypatch):
    async def fake(*, model):
        return {"sites": [{"name": "Гудаури", "aspect": 180.0, "days": []}],
                "empty": ["Лалискури"], "failed": []}

    monkeypatch.setattr(forecast, "scan_week", fake)
    body = (await client.get("/api/scan", headers=header())).json()
    assert body["empty"] == ["Лалискури"]


async def test_scan_uses_the_pilots_model(client, monkeypatch):
    seen = []

    async def fake(*, model):
        seen.append(model)
        return {"sites": [], "empty": [], "failed": []}

    monkeypatch.setattr(forecast, "scan_week", fake)
    store.set_model(1, "icon")
    await client.get("/api/scan", headers=header(uid=1))
    assert seen == ["icon"]


async def test_forecast_needs_authorization(client, facts):
    assert (await client.get("/api/forecast?site=Гудаури&range=1d")).status_code == 401


async def test_an_adhoc_point_is_a_site_for_the_endpoint_too(client, facts):
    """Разовая точка по координатам живёт в adhoc, а не в библиотеке стартов.
    Проверка существования только через find_site отдала бы 404 на законную
    точку ещё до вызова домена — тест на уровне forecast этого не поймал бы,
    он ходит мимо api.py."""
    name = forecast.register_adhoc(42.5, 44.5, 2000)
    r = await client.get(f"/api/forecast?site={name}&range=1d", headers=header())
    assert r.status_code == 200
    assert facts, "запрос должен был дойти до домена"
```

- [ ] **Step 6: Дописать эндпоинты в `api.py`**

```python
# ------------------------------------------------------------------ прогноз
def _model_for(uid: int, override: str | None) -> str:
    """Эффективная модель: разовый выбор из query, иначе постоянная настройка.

    Разрешается ЗДЕСЬ и передаётся домену явно: forecast обязан получать
    model= параметром, угадывать он не имеет права (см. фазу 2).
    """
    if override is None:
        return store.prefs(uid).model_key
    if override not in engine.MODELS:
        raise HTTPException(400, f"неизвестная модель: {override}")
    return override


def _site_or_404(name: str) -> dict:
    """Старт существует, или 404 до похода в сеть.

    Резолвит ТОЙ ЖЕ функцией, что и домен: `store.find_site` в одиночку
    отдал бы 404 на законную разовую точку по координатам, потому что она
    живёт в adhoc, а не в библиотеке стартов.
    """
    site = forecast.site_by_name(name)
    if site is None:
        raise HTTPException(404, f"старт не найден: {name}")
    return site


@router.get("/forecast")
async def read_forecast(site: str, range: str, date: str | None = None,
                        model: str | None = None,
                        user: webauth.TelegramUser = Depends(current_user)):
    """Факты, а не картинка: приложение рисует графики само."""
    _site_or_404(site)
    return await forecast.get_facts(site, range, date, model=_model_for(user.id, model))


@router.get("/forecast/wind-grid")
async def read_wind_grid(site: str, date: str, model: str | None = None,
                         user: webauth.TelegramUser = Depends(current_user)):
    _site_or_404(site)
    return await forecast.wind_grid_data(site, date, model=_model_for(user.id, model))


@router.get("/scan")
async def read_scan(model: str | None = None,
                    user: webauth.TelegramUser = Depends(current_user)):
    return await forecast.scan_week(model=_model_for(user.id, model))
```

`range` затеняет встроенную функцию — так названо в спеке и так приходит в query. Псевдоним через `Query(alias="range")` добавил бы третье имя одному значению; тень локальна и безвредна.

- [ ] **Step 7: Тесты проходят**

Run: `python -m pytest tests/test_api_forecast.py -q`
Expected: PASS, 14 тестов.

- [ ] **Step 8: Полный прогон**

Run: `python -m pytest -q`
Expected: 913 passed.

- [ ] **Step 9: Коммит**

```bash
git add forecast.py api.py tests/test_api_forecast.py tests/test_lazy_cache.py
git commit -m "feat(api): прогноз, сетка ветра числами, скан по стартам"
```

---

### Task 5: `/api/analysis`, `/api/route`, `/api/route/analysis`

**Files:**
- Modify: `api.py`
- Create: `tests/test_api_route.py`

**Interfaces:**
- Consumes: `forecast.get_analysis(site, rng, date, deep, *, model)`, `forecast.get_route(points, name, date, departure_h, *, cfg)`, `forecast.get_route_analysis(...)`, `route.points_from_rows`, `route.Point`, `store.prefs`.
- Produces: `POST /api/analysis`, `POST /api/route`, `POST /api/route/analysis`.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_api_route.py`:

```python
"""Разбор дня и профиль маршрута через HTTP."""
import pytest

import forecast
import store
from tma import header

ROWS = [[42.4776, 44.4787, "старт"], [42.1176, 44.4787, "финиш"]]
BODY = {"points": ROWS, "name": "Гудаури", "date": "2026-08-01", "departure": "11:30"}


async def test_analysis_returns_text(client, monkeypatch):
    async def fake(site, rng, date=None, deep=False, *, model):
        return "РАЗБОР"

    monkeypatch.setattr(forecast, "get_analysis", fake)
    r = await client.post("/api/analysis",
                          json={"site": "Гудаури", "range": "1d"}, headers=header())
    assert r.json()["text"] == "РАЗБОР"


async def test_analysis_passes_deep_through(client, monkeypatch):
    seen = []

    async def fake(site, rng, date=None, deep=False, *, model):
        seen.append(deep)
        return "РАЗБОР"

    monkeypatch.setattr(forecast, "get_analysis", fake)
    await client.post("/api/analysis",
                      json={"site": "Гудаури", "range": "1d", "deep": True},
                      headers=header())
    assert seen == [True]


async def test_route_returns_a_profile(client, monkeypatch):
    async def fake(points, name, date, departure_h=None, *, cfg):
        return {"route": {"name": name, "total_km": 40.0}, "points": [],
                "verdict": {"score": 70}, "terrain": None, "notes": []}

    monkeypatch.setattr(forecast, "get_route", fake)
    body = (await client.post("/api/route", json=BODY, headers=header())).json()
    assert body["route"]["total_km"] == 40.0


async def test_route_uses_the_pilots_own_settings(client, monkeypatch):
    """cfg резолвит адаптер: домену user_id недоступен."""
    seen = []

    async def fake(points, name, date, departure_h=None, *, cfg):
        seen.append(cfg)
        return {"route": {}, "points": [], "verdict": {}, "terrain": None, "notes": []}

    monkeypatch.setattr(forecast, "get_route", fake)
    store.set_speed(1, 33.0)
    store.set_model(1, "icon")
    await client.post("/api/route", json=BODY, headers=header(uid=1))
    assert seen[0].avg_route_speed_kmh == 33.0
    assert seen[0].model_key == "icon"


async def test_two_pilots_get_their_own_settings(client, monkeypatch):
    seen = []

    async def fake(points, name, date, departure_h=None, *, cfg):
        seen.append(cfg.avg_route_speed_kmh)
        return {"route": {}, "points": [], "verdict": {}, "terrain": None, "notes": []}

    monkeypatch.setattr(forecast, "get_route", fake)
    store.set_speed(1, 20.0)
    store.set_speed(2, 40.0)
    await client.post("/api/route", json=BODY, headers=header(uid=1))
    await client.post("/api/route", json=BODY, headers=header(uid=2))
    assert seen == [20.0, 40.0]


async def test_departure_time_reaches_the_domain(client, monkeypatch):
    seen = []

    async def fake(points, name, date, departure_h=None, *, cfg):
        seen.append(departure_h)
        return {"route": {}, "points": [], "verdict": {}, "terrain": None, "notes": []}

    monkeypatch.setattr(forecast, "get_route", fake)
    await client.post("/api/route", json=BODY, headers=header())
    assert seen == [11.5], "11:30 — это 11.5 часа"


async def test_route_without_departure_lets_the_domain_choose(client, monkeypatch):
    """Без времени вылета домен берёт начало термического окна — подставлять
    здесь свой полдень значило бы спорить с расчётом."""
    seen = []

    async def fake(points, name, date, departure_h=None, *, cfg):
        seen.append(departure_h)
        return {"route": {}, "points": [], "verdict": {}, "terrain": None, "notes": []}

    monkeypatch.setattr(forecast, "get_route", fake)
    await client.post("/api/route", json={k: v for k, v in BODY.items()
                                          if k != "departure"}, headers=header())
    assert seen == [None]


async def test_a_single_point_route_is_400(client):
    r = await client.post("/api/route", json={**BODY, "points": ROWS[:1]},
                          headers=header())
    assert r.status_code == 400


async def test_too_many_points_is_400(client):
    import route
    many = [[42.0 + i / 1000.0, 44.0, ""] for i in range(route.MAX_POINTS + 1)]
    r = await client.post("/api/route", json={**BODY, "points": many},
                          headers=header())
    assert r.status_code == 400


async def test_route_analysis_returns_text(client, monkeypatch):
    async def fake(points, name, date, departure_h=None, *, cfg):
        return "РАЗБОР МАРШРУТА"

    monkeypatch.setattr(forecast, "get_route_analysis", fake)
    r = await client.post("/api/route/analysis", json=BODY, headers=header())
    assert r.json()["text"] == "РАЗБОР МАРШРУТА"


async def test_route_needs_authorization(client):
    assert (await client.post("/api/route", json=BODY)).status_code == 401


@pytest.fixture()
def route_cfg(monkeypatch):
    """Записывает cfg, с которым позвали расчёт маршрута."""
    seen = []

    async def fake(points, name, date, departure_h=None, *, cfg):
        seen.append(cfg)
        return {"route": {}, "points": [], "verdict": {}, "terrain": None, "notes": []}

    monkeypatch.setattr(forecast, "get_route", fake)
    return seen


async def test_route_model_overrides_the_permanent_one(client, route_cfg):
    store.set_model(1, "ecmwf")
    await client.post("/api/route", json={**BODY, "model": "gfs"}, headers=header(uid=1))
    assert route_cfg[0].model_key == "gfs"


async def test_route_model_does_not_persist(client, route_cfg):
    """Разовый выбор модели не должен менять постоянную настройку пилота."""
    store.set_model(1, "ecmwf")
    await client.post("/api/route", json={**BODY, "model": "gfs"}, headers=header(uid=1))
    assert store.prefs(1).model_key == "ecmwf"


async def test_an_unknown_route_model_is_400(client, route_cfg):
    r = await client.post("/api/route", json={**BODY, "model": "нет-такой"},
                          headers=header(uid=1))
    assert r.status_code == 400
    assert not route_cfg, "неизвестная модель не должна доехать до домена"
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `python -m pytest tests/test_api_route.py -q`
Expected: FAIL, 404 (маршрутов нет).

- [ ] **Step 3: Дописать эндпоинты в `api.py`**

```python
# ------------------------------------------------------------------ разбор и маршрут
class AnalysisIn(BaseModel):
    site: str
    range: str
    date: str | None = None
    deep: bool = False
    model: str | None = None


class RouteIn(BaseModel):
    """`points` — строки [lat, lon, name?], тот же формат, в котором маршруты
    лежат в store: приложение получает их из /api/routes и шлёт обратно
    без перекладывания."""
    points: list[list]
    name: str | None = None
    date: str
    departure: str | None = None
    model: str | None = None


def _hours(hhmm: str | None) -> float | None:
    """«11:30» → 11.5. None означает «пусть домен выберет начало окна»."""
    if hhmm is None:
        return None
    try:
        h, m = hhmm.split(":")
        return int(h) + int(m) / 60.0
    except (ValueError, AttributeError):
        raise HTTPException(400, f"время вылета не понято: {hhmm}") from None


def _cfg_for(uid: int, override: str | None) -> store.Prefs:
    """Личные настройки с разовой подменой модели.

    Возвращается Prefs целиком: get_route берёт из него и скорость, и учёт
    ветра, и модель — собирать их по одному значит однажды забыть одно.

    Ключ проверяет `_model_for`, и только он: вторая такая же проверка здесь
    разъехалась бы с первой при первой правке списка моделей.
    """
    p = store.prefs(uid)
    if override is None:
        return p
    return dataclasses.replace(p, model_key=_model_for(uid, override))


def _points_or_400(rows: list[list]) -> list:
    """Строки [[lat, lon, name?], ...] → точки.

    `points_from_rows` исключений не бросает: на битой записи и нехватке точек
    он возвращает None, потому что писался для чтения из хранилища, где
    уронить бота хуже, чем показать маршрут отсутствующим. На входе из сети
    это, наоборот, ошибка запроса, и её надо назвать.

    Потолок числа точек он тоже не проверяет — только нижнюю границу, — а
    пятьдесят одна точка означает пятьдесят одну выборку погоды.
    """
    points = route.points_from_rows(rows)
    if points is None:
        raise HTTPException(400, f"Нужно минимум {route.MIN_POINTS} точки "
                                 "в формате [широта, долгота, имя].")
    if len(points) > route.MAX_POINTS:
        raise HTTPException(400, f"Слишком много точек: {len(points)}, "
                                 f"потолок {route.MAX_POINTS}.")
    return points


@router.post("/analysis")
async def read_analysis(body: AnalysisIn,
                        user: webauth.TelegramUser = Depends(current_user)):
    """Текст от Gemini. Ответ строкой, а не разметкой: она в приложении своя."""
    _site_or_404(body.site)
    text = await forecast.get_analysis(body.site, body.range, body.date, body.deep,
                                       model=_model_for(user.id, body.model))
    return {"text": text}


@router.post("/route")
async def read_route(body: RouteIn, user: webauth.TelegramUser = Depends(current_user)):
    return await forecast.get_route(_points_or_400(body.points), body.name, body.date,
                                    _hours(body.departure),
                                    cfg=_cfg_for(user.id, body.model))


@router.post("/route/analysis")
async def read_route_analysis(body: RouteIn,
                              user: webauth.TelegramUser = Depends(current_user)):
    text = await forecast.get_route_analysis(_points_or_400(body.points), body.name,
                                             body.date, _hours(body.departure),
                                             cfg=_cfg_for(user.id, body.model))
    return {"text": text}
```

Добавить `import dataclasses` в начало `api.py`.

- [ ] **Step 4: Тесты проходят**

Run: `python -m pytest tests/test_api_route.py -q`
Expected: PASS, 14 тестов.

- [ ] **Step 5: Полный прогон**

Run: `python -m pytest -q`
Expected: 927 passed.

- [ ] **Step 6: Коммит**

```bash
git add api.py tests/test_api_route.py
git commit -m "feat(api): разбор дня, профиль маршрута и разбор маршрута"
```

---

### Task 6: `/api/route/parse` и `/api/routes`

**Files:**
- Modify: `api.py`
- Modify: `requirements.txt` (`python-multipart` — FastAPI требует его для загрузки файла)
- Create: `tests/test_api_routes_crud.py`

**Interfaces:**
- Consumes: `route.parse_text/parse_gpx/parse_kml`, `route.MAX_GPX_BYTES`, `store.routes_list/route_rows/route_save/route_delete/route_exists`, `store.MAX_ROUTES`.
- Produces: `POST /api/route/parse`, `GET|POST /api/routes`, `DELETE /api/routes/{name}`.

- [ ] **Step 1: Добавить зависимость**

`requirements.txt` — дописать:

```
python-multipart>=0.0.9
```

Без него FastAPI поднимает `RuntimeError` при первом же `UploadFile`, причём **на старте**, а не при запросе.

- [ ] **Step 2: Написать падающие тесты**

`tests/test_api_routes_crud.py`:

```python
"""Разбор файлов маршрута и личные сохранённые маршруты."""
import pytest

import store
from tma import header

ROWS = [[42.4776, 44.4787, "старт"], [42.1176, 44.4787, "финиш"]]

# Кириллица внутри b"""...""" — синтаксическая ошибка: в bytes-литерал
# помещаются только ASCII-символы. Поэтому str, а потом .encode().
GPX = """<?xml version="1.0"?>
<gpx version="1.1"><rte>
<rtept lat="42.4776" lon="44.4787"><name>старт</name></rtept>
<rtept lat="42.1176" lon="44.4787"><name>финиш</name></rtept>
</rte></gpx>""".encode()


# Путь один, тело всегда multipart: файл приезжает полем file, вставленный
# список координат — полем text. Два разных типа тела на одном пути FastAPI
# не различает, а второй путь ради текста удвоил бы контракт.
async def test_parse_text(client):
    r = await client.post("/api/route/parse",
                          data={"text": "42.4776, 44.4787, старт\n"
                                        "42.1176, 44.4787, финиш"},
                          headers=header())
    assert [p[0] for p in r.json()["points"]] == [42.4776, 42.1176]


async def test_parse_gpx_upload(client):
    r = await client.post("/api/route/parse",
                          files={"file": ("track.gpx", GPX, "application/gpx+xml")},
                          headers=header())
    assert len(r.json()["points"]) == 2


async def test_parse_kmz_is_refused_with_the_same_words_as_in_chat(client):
    """KMZ — архив. Приложение и чат обязаны объяснять это одинаково."""
    r = await client.post("/api/route/parse",
                          files={"file": ("track.kmz", b"PK\x03\x04", "application/kmz")},
                          headers=header())
    assert r.status_code == 400
    assert "распакуй" in r.text.lower()


async def test_parse_rejects_an_oversized_file(client):
    """Чужой трек на сотни тысяч точек не должен класть сервер — тот же потолок,
    что стоит в чате."""
    import route
    big = b"<gpx>" + b"x" * route.MAX_GPX_BYTES
    r = await client.post("/api/route/parse",
                          files={"file": ("big.gpx", big, "application/gpx+xml")},
                          headers=header())
    assert r.status_code == 400


async def test_parse_garbage_is_400_with_the_domain_text(client):
    r = await client.post("/api/route/parse", data={"text": "это не координаты"},
                          headers=header())
    assert r.status_code == 400


async def test_parse_without_input_is_400(client):
    assert (await client.post("/api/route/parse", data={},
                              headers=header())).status_code == 400


async def test_parse_saves_nothing(client):
    """Разбор — чистое преобразование: пилот ещё не решил сохранять."""
    await client.post("/api/route/parse",
                      files={"file": ("track.gpx", GPX, "application/gpx+xml")},
                      headers=header(uid=1))
    assert store.routes_list(1) == {}


async def test_routes_lists_only_your_own(client):
    store.route_save(1, "Мой", ROWS)
    store.route_save(2, "Чужой", ROWS)
    body = (await client.get("/api/routes", headers=header(uid=1))).json()
    assert [r["name"] for r in body] == ["Мой"]


async def test_save_a_route(client):
    r = await client.post("/api/routes", json={"name": "Мой", "points": ROWS},
                          headers=header(uid=1))
    assert r.status_code == 201
    assert store.route_rows(1, "Мой") == ROWS


async def test_saving_the_same_name_overwrites_and_says_so(client):
    store.route_save(1, "Мой", ROWS)
    r = await client.post("/api/routes",
                          json={"name": "Мой", "points": list(reversed(ROWS))},
                          headers=header(uid=1))
    assert r.json()["overwritten"] is True
    assert store.route_rows(1, "Мой")[0][0] == 42.1176


async def test_the_route_limit_is_enforced(client):
    for i in range(store.MAX_ROUTES):
        store.route_save(1, f"м{i}", ROWS)
    r = await client.post("/api/routes", json={"name": "ещё", "points": ROWS},
                          headers=header(uid=1))
    assert r.status_code == 400


async def test_delete_a_route(client):
    store.route_save(1, "Мой", ROWS)
    assert (await client.delete("/api/routes/Мой",
                                headers=header(uid=1))).status_code == 204
    assert store.routes_list(1) == {}


async def test_deleting_an_unknown_route_is_404(client):
    assert (await client.delete("/api/routes/нету",
                                headers=header(uid=1))).status_code == 404


async def test_you_cannot_delete_a_teammates_route(client):
    """Маршруты личные: чужое имя для тебя просто не существует."""
    store.route_save(2, "Чужой", ROWS)
    assert (await client.delete("/api/routes/Чужой",
                                headers=header(uid=1))).status_code == 404
    assert store.route_rows(2, "Чужой") == ROWS
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `python -m pytest tests/test_api_routes_crud.py -q`
Expected: FAIL, 404.

- [ ] **Step 4: Вынести выбор разборщика в `route.py`**

`bot.py:1244` держит таблицу разборщиков, `bot.py:1252` — сообщение про KMZ:

```python
_DOC_PARSERS = ((".gpx", route.parse_gpx), (".kml", route.parse_kml))
...
        return await message.answer("KMZ — это архив. Распакуй и пришли .kml")
```

Второе, независимое определение «что такое KML» в `api.py` разъехалось бы с этим при первой правке. Перенести в `route.py`:

```python
_UPLOAD_PARSERS = ((".gpx", parse_gpx), (".kml", parse_kml))


def parse_upload(filename: str, data: bytes):
    """Точки и имя маршрута из присланного файла: `(points, name)`.

    Разборщик выбирается по расширению. Общая на чат и приложение: два
    независимых определения «что такое KML» разъедутся, и пилот получит из
    приложения ответ, которого не получил бы из чата.

    Возвращает ПАРУ, а не список: GPX и KML несут имя маршрута внутри, и
    `parse_gpx` отдаёт его вторым элементом. Присвоение результата одной
    переменной роняет любую загрузку.
    """
    name = (filename or "").lower()
    if name.endswith(".kmz"):
        # KMZ — zip с kml внутри; разворачивать архив из сети мы не будем
        raise RouteError("KMZ — это архив. Распакуй и пришли .kml")
    for suffix, parser in _UPLOAD_PARSERS:
        if name.endswith(suffix):
            return parser(data)
    raise RouteError("Не понял формат файла: пришли .gpx или .kml")
```

`bot.py` перевести на `route.parse_upload(...)`, удалив `_DOC_PARSERS` и строку про KMZ. Проверку размера в `bot.py` **оставить как есть**: там она делается по `doc.file_size` до скачивания, а в API — после чтения тела, механика разная, общая только константа `route.MAX_GPX_BYTES`.

Существующие тесты загрузки документа в чат обязаны остаться зелёными без правок — тексты сообщений не менялись.

- [ ] **Step 5: Дописать эндпоинты в `api.py`**

```python
@router.post("/route/parse")
async def parse_route(file: UploadFile | None = File(default=None),
                      text: str | None = Form(default=None),
                      _user: webauth.TelegramUser = Depends(current_user)):
    """GPX / KML / текст → точки. Ничего не сохраняет и погоду не считает.

    Тело всегда multipart: файл полем `file`, вставленные координаты полем
    `text`. Два разных типа тела на одном пути FastAPI не различает, а второй
    путь ради текста удвоил бы контракт на ровном месте.
    """
    if file is not None:
        # Читаем на байт больше потолка: так перебор виден без загрузки
        # всего файла в память.
        data = await file.read(route.MAX_GPX_BYTES + 1)
        if len(data) > route.MAX_GPX_BYTES:
            raise HTTPException(
                400, f"❌ файл больше {route.MAX_GPX_BYTES // 1024} КБ — "
                     "пришли маршрут покороче")
        # parse_upload отдаёт ПАРУ (точки, имя маршрута из файла): GPX и KML
        # несут имя внутри. Имя здесь не нужно — пилот задаёт его при
        # сохранении, — но распаковать пару обязательно.
        points, _name = route.parse_upload(file.filename or "", data)
    elif text:
        points = route.parse_text(text)
    else:
        raise HTTPException(400, "Пришли файл GPX/KML или список координат.")
    return {"points": [[p.lat, p.lon, p.name] for p in points]}


class RouteSaveIn(BaseModel):
    name: str
    points: list[list]


@router.get("/routes")
async def list_routes(user: webauth.TelegramUser = Depends(current_user)):
    saved = store.routes_list(user.id)
    return [{"name": name, **meta} for name, meta in saved.items()]


@router.post("/routes", status_code=201)
async def save_route(body: RouteSaveIn,
                     user: webauth.TelegramUser = Depends(current_user)):
    points = _points_or_400(body.points)
    existed = store.route_exists(user.id, body.name)
    if not existed and len(store.routes_list(user.id)) >= store.MAX_ROUTES:
        raise HTTPException(400, f"Сохранено уже {store.MAX_ROUTES} маршрутов — "
                                 "удали лишний через /delroute или в приложении.")
    store.route_save(user.id, body.name, [[p.lat, p.lon, p.name] for p in points])
    return {"name": body.name, "overwritten": existed}


@router.delete("/routes/{name}", status_code=204)
async def delete_route(name: str, user: webauth.TelegramUser = Depends(current_user)):
    if not store.route_delete(user.id, name):
        # Чужой маршрут для тебя просто не существует — 403 подтвердил бы,
        # что такое имя у кого-то есть.
        raise HTTPException(404, f"маршрут не найден: {name}")
    return None
```

Добавить в импорты `api.py`: `from fastapi import File, Form, UploadFile`.

`store.routes_list` возвращает `{name: {"points": [...], "saved": "<ISO>"}}`, поэтому ответ `/api/routes` — это `[{"name": ..., "points": [...], "saved": ...}]` без переупаковки.

`store.route_delete` возвращает `bool` — удалил или нет; `store.route_exists` отвечает на «имя занято» отдельно от `routes_list`, потому что тот пропускает битые записи (см. его docstring). Перезапись обязана опираться на `route_exists`, иначе она отчитается «Сохранил» там, где затёрла нечитаемую чужую запись.

- [ ] **Step 6: Тесты проходят**

Run: `python -m pytest tests/test_api_routes_crud.py -q`
Expected: PASS, 14 тестов.

- [ ] **Step 7: Полный прогон**

Run: `python -m pytest -q`
Expected: 941 passed. Тесты загрузки документа в чат зелёные без правок.

- [ ] **Step 8: Коммит**

```bash
git add api.py route.py bot.py requirements.txt tests/test_api_routes_crud.py
git commit -m "feat(api): разбор GPX/KML и личные сохранённые маршруты"
```

---

### Task 7: один расчёт на пилота — 429

**Files:**
- Modify: `guards.py`
- Modify: `api.py`
- Modify: `tests/conftest.py` (сброс реестра между тестами)
- Create: `tests/test_api_inflight.py`

**Interfaces:**
- Produces: `guards.INFLIGHT` (`acquire`, `release`, `hold`, `clear`); зависимость `api.one_at_a_time`.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_api_inflight.py`:

```python
"""Один тяжёлый запрос на пилота — на обе поверхности сразу."""
import asyncio

import pytest

import forecast
import guards
from tma import header


@pytest.fixture()
def slow(monkeypatch):
    """get_facts, который висит, пока тест не разрешит ему закончиться.

    `entered` вместо `asyncio.sleep(0)`: сколько шагов цикла нужно запросу,
    чтобы дойти до захвата слота, — деталь реализации FastAPI, и тест,
    угадывающий её, начнёт мигать при обновлении зависимостей.
    """
    class Gate:
        def __init__(self):
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

    gate = Gate()

    async def fake(site, rng, date=None, *, model):
        gate.entered.set()
        await gate.release.wait()
        return {"site": {"name": site}}

    monkeypatch.setattr(forecast, "get_facts", fake)
    return gate


async def test_a_second_request_while_the_first_runs_is_429(client, slow):
    first = asyncio.create_task(
        client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1)))
    await asyncio.wait_for(slow.entered.wait(), timeout=5)
    # wait_for, а не голый await: без троттлинга второй запрос уходит в тот же
    # висящий расчёт, и тест не падает, а зависает навсегда. Зависший тест хуже
    # упавшего — он не говорит, что сломалось, и не даёт красной фазы.
    second = await asyncio.wait_for(
        client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1)),
        timeout=5)
    assert second.status_code == 429
    slow.release.set()
    assert (await first).status_code == 200


async def test_the_slot_is_released_after_the_answer(client, slow):
    slow.release.set()
    for _ in range(3):
        r = await client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1))
        assert r.status_code == 200, "слот не освободился после успешного ответа"


async def test_the_slot_is_released_after_a_failure(client, monkeypatch):
    """Иначе одна ошибка запирает пилота до перезапуска процесса."""
    async def boom(site, rng, date=None, *, model):
        raise forecast.ForecastError("Диапазон не понят")

    monkeypatch.setattr(forecast, "get_facts", boom)
    for _ in range(2):
        r = await client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1))
        assert r.status_code == 400


async def test_another_pilot_is_not_blocked(client, slow):
    first = asyncio.create_task(
        client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1)))
    await asyncio.wait_for(slow.entered.wait(), timeout=5)
    slow.release.set()  # второму пилоту висеть незачем
    second = await client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=2))
    assert second.status_code == 200
    await first


async def test_light_endpoints_are_not_throttled(client, slow):
    """Настройки и список стартов не ходят в сеть: запирать их вместе с
    прогнозом значит гасить весь экран, пока грузится один график."""
    first = asyncio.create_task(
        client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1)))
    await asyncio.wait_for(slow.entered.wait(), timeout=5)
    assert (await client.get("/api/prefs", headers=header(uid=1))).status_code == 200
    assert (await client.get("/api/sites", headers=header(uid=1))).status_code == 200
    slow.release.set()
    await first


async def test_the_api_shares_the_registry_with_the_bot(client, slow):
    """Реестр общий по решению: открыть приложение, пока бот считает тот же
    прогноз, — это второй запрос того же пилота."""
    guards.INFLIGHT.acquire(1)
    try:
        # wait_for по той же причине, что и выше: без троттлинга запрос уходит
        # в висящий расчёт, и тест зависает вместо красной фазы.
        r = await asyncio.wait_for(
            client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1)),
            timeout=5)
        assert r.status_code == 429
    finally:
        guards.INFLIGHT.release(1)


async def test_the_api_has_no_cooldown(client, monkeypatch):
    """10-секундная пауза между командами чата к приложению не применяется:
    там каждое действие — продолжение уже выданного результата."""
    monkeypatch.setenv("COOLDOWN_SEC", "60")

    async def fake(site, rng, date=None, *, model):
        return {"site": {"name": site}}

    monkeypatch.setattr(forecast, "get_facts", fake)
    for _ in range(3):
        r = await client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1))
        assert r.status_code == 200
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `python -m pytest tests/test_api_inflight.py -q`
Expected: FAIL, `AttributeError: module 'guards' has no attribute 'INFLIGHT'`

- [ ] **Step 3: Вынести реестр в `guards.py`**

Добавить перед `ThrottleMiddleware`:

```python
class InFlight:
    """Кто из пилотов прямо сейчас чего-то ждёт.

    Общий на чат и приложение намеренно: гарантия сформулирована про пилота,
    а не про поверхность, и открыть приложение, пока бот считает тот же
    прогноз, — это второй запрос того же человека.

    Множество, а не счётчик: параллельных запросов одного пилота не бывает
    по определению, а счётчик пришлось бы чинить после каждого падения.
    """

    def __init__(self):
        self._busy: set[int] = set()

    def busy(self, uid: int) -> bool:
        """Ждёт ли пилот чего-то прямо сейчас. Ничего не занимает.

        Отдельно от `acquire` намеренно: в чате проверка занятости стоит
        раньше проверки паузы, а захват — позже неё. Слитые в один вызов,
        они держали бы слот на время ответа «не так часто», то есть на всё
        сетевое обращение к Telegram.
        """
        return uid in self._busy

    def acquire(self, uid: int) -> bool:
        """True — слот занят нами. False — пилот уже что-то ждёт."""
        if uid in self._busy:
            return False
        self._busy.add(uid)
        return True

    def release(self, uid: int) -> None:
        self._busy.discard(uid)

    def clear(self) -> None:
        """Только для тестов: реестр процессный и переживает тест."""
        self._busy.clear()


INFLIGHT = InFlight()
```

`ThrottleMiddleware.__init__` — убрать `self._inflight = set()`, тело переписать на общий реестр:

```python
        if INFLIGHT.busy(uid):
            return await event.answer("⏳ Уже готовлю — дождись ответа.")
        # ... проверка cooldown остаётся здесь, без изменений ...
        INFLIGHT.acquire(uid)
        try:
            return await handler(event, data)
        finally:
            INFLIGHT.release(uid)
```

**Порядок трёх шагов менять нельзя, и слить их в один вызов тоже нельзя.** Проверка занятости стоит до паузы, захват — после неё, ровно как в исходном коде: там `uid in self._inflight` читал, а `self._inflight.add(uid)` писал, и между ними была проверка паузы.

`acquire()` наверху вместо `busy()` выглядит короче, но меняет поведение: отказ по паузе — это `return await event.answer(...)`, то есть настоящее обращение к Telegram, и всё это время пилот числился бы занятым. Открытое в эту секунду приложение получило бы 429 вместо прогноза.

Между `busy()` и `acquire()` на успешном пути нет ни одного `await`, поэтому разрыва между проверкой и захватом в однопоточном цикле не возникает.

- [ ] **Step 4: Добавить зависимость в `api.py`**

```python
async def one_at_a_time(user: webauth.TelegramUser = Depends(current_user)):
    """Один тяжёлый запрос на пилота. Паузы нет — только занятость.

    В приложении каждое действие продолжает уже показанный результат, и
    10-секундный cooldown чата сделал бы его сломанным. Повторы гасит кэш.

    Вешается только на эндпоинты, ходящие в сеть: запереть настройки вместе
    с прогнозом значит подвесить весь экран из-за одного графика.
    """
    if not guards.INFLIGHT.acquire(user.id):
        raise HTTPException(429, "Уже считаю — дождись ответа.")
    try:
        yield user
    finally:
        # finally, а не хвост функции: без него одна ошибка запирает пилота
        # до перезапуска процесса
        guards.INFLIGHT.release(user.id)
```

Заменить `Depends(current_user)` на `Depends(one_at_a_time)` в: `read_forecast`, `read_wind_grid`, `read_scan`, `read_analysis`, `read_route`, `read_route_analysis`, `elevation`.

Оставить `current_user` в: `read_prefs`, `update_prefs`, `list_sites`, `read_site`, `create_site`, `delete_site`, `parse_route`, `list_routes`, `save_route`, `delete_route`.

`elevation` ходит в сеть — под троттлингом. Тест `test_light_endpoints_are_not_throttled` его не проверяет.

- [ ] **Step 5: Сбрасывать реестр между тестами**

`tests/conftest.py` — добавить `import guards` к остальным импортам и строку в `fresh_state` перед `yield`:

```python
    guards.INFLIGHT.clear()   # реестр процессный: упавший тест запер бы следующий
```

- [ ] **Step 6: Тесты проходят**

Run: `python -m pytest tests/test_api_inflight.py -q`
Expected: PASS, 7 тестов.

- [ ] **Step 7: Проверить, что откат ломает тесты**

Временно вернуть `ThrottleMiddleware` собственный `set()` и убрать `Depends(one_at_a_time)` с `read_forecast`. Прогнать `tests/test_api_inflight.py`.
Expected: FAIL как минимум в `test_a_second_request_while_the_first_runs_is_429` и `test_the_api_shares_the_registry_with_the_bot`.
Вернуть правку обратно.

- [ ] **Step 8: Полный прогон**

Run: `python -m pytest -q`
Expected: 948 passed. Тесты троттлинга бота остаются зелёными без правок — поведение чата не изменилось.

- [ ] **Step 9: Коммит**

```bash
git add guards.py api.py tests/conftest.py tests/test_api_inflight.py
git commit -m "feat(api): один расчёт на пилота, общий с ботом реестр"
```

---

### Task 8: `app.py` — polling и uvicorn в одном процессе

**Files:**
- Create: `app.py`
- Modify: `bot.py` (`main()` разбирается на части)
- Modify: `Dockerfile` (`CMD`)
- Create: `tests/test_app_entry.py`

**Interfaces:**
- Consumes: `bot.bootstrap()`, `bot.run_polling()`, `api.app`.
- Produces: `app.main()`, `app.API_HOST`, `app.API_PORT`.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_app_entry.py`:

```python
"""Точка входа: бот и API живут в одном процессе."""
import asyncio

import pytest


async def test_both_surfaces_start(monkeypatch):
    """Если одна из двух корутин не запущена, приложение молча работает
    наполовину: бот отвечает, приложение белое (или наоборот)."""
    import app

    started = []

    async def fake_polling():
        started.append("polling")
        await asyncio.sleep(0)

    async def fake_serve():
        started.append("http")
        await asyncio.sleep(0)

    monkeypatch.setattr(app, "_run_polling", fake_polling)
    monkeypatch.setattr(app, "_run_http", fake_serve)
    monkeypatch.setattr(app, "_bootstrap", lambda: {})

    await app.main()
    assert sorted(started) == ["http", "polling"]


async def test_a_dead_bot_takes_the_process_down(monkeypatch):
    """Иначе контейнер выглядит живым, а бот в нём молчит: restart не сработает,
    потому что процесс не упал."""
    import app

    async def boom():
        raise RuntimeError("polling умер")

    async def forever():
        await asyncio.sleep(3600)

    monkeypatch.setattr(app, "_run_polling", boom)
    monkeypatch.setattr(app, "_run_http", forever)
    monkeypatch.setattr(app, "_bootstrap", lambda: {})

    with pytest.raises(RuntimeError):
        await asyncio.wait_for(app.main(), timeout=5)


async def test_a_dead_api_takes_the_process_down(monkeypatch):
    import app

    async def boom():
        raise RuntimeError("uvicorn умер")

    async def forever():
        await asyncio.sleep(3600)

    monkeypatch.setattr(app, "_run_polling", forever)
    monkeypatch.setattr(app, "_run_http", boom)
    monkeypatch.setattr(app, "_bootstrap", lambda: {})

    with pytest.raises(RuntimeError):
        await asyncio.wait_for(app.main(), timeout=5)


async def test_storage_is_migrated_before_either_surface_starts(monkeypatch):
    """Первый запрос не должен успеть прийти в пустую базу."""
    import app

    order = []
    monkeypatch.setattr(app, "_bootstrap", lambda: order.append("bootstrap"))

    async def note_polling():
        order.append("polling")

    async def note_http():
        order.append("http")

    monkeypatch.setattr(app, "_run_polling", note_polling)
    monkeypatch.setattr(app, "_run_http", note_http)

    await app.main()
    assert order[0] == "bootstrap"


def test_api_binds_loopback_only():
    """Наружу смотрит Caddy. uvicorn на 0.0.0.0 отдал бы API без TLS всем,
    кто дотянется до порта."""
    import app
    assert app.API_HOST == "127.0.0.1"
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `python -m pytest tests/test_app_entry.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Разобрать `bot.main()` на части**

В `bot.py` заменить `main()`:

```python
def bootstrap() -> dict:
    """Всё, что должно случиться ДО первого запроса, с любой поверхности."""
    if not os.environ.get("BOT_TOKEN"):
        raise SystemExit("BOT_TOKEN не задан (см. .env.example)")
    return _bootstrap_store()


async def run_polling() -> None:
    """Long polling. Хранилище должно быть готово — см. bootstrap()."""
    bot = Bot(token=os.environ["BOT_TOKEN"])
    await bot.set_my_commands(BOT_COMMANDS)
    log.info("bot started, db: %s, sites: %s", store.DB_PATH, forecast.known_sites())
    await dp.start_polling(bot)


async def main():
    """Только чат — для запуска без HTTP-слоя (`python bot.py`)."""
    bootstrap()
    await run_polling()
```

Разделение нужно, чтобы `app.py` мог выполнить миграцию один раз и поднять обе поверхности; `bot.py` как точка входа остаётся рабочим.

- [ ] **Step 4: Написать `app.py`**

```python
"""Точка входа: чат и приложение в одном процессе.

Один процесс — не экономия, а условие: _fcache, _acache и _rcache процессные,
и на переиспользовании тёплого кэша между поверхностями построена вся
экономия запросов к open-meteo. Два сервиса удвоили бы их и убили бы
единственную оптимизацию, которая в проекте есть.
"""
import asyncio
import logging
import os

import uvicorn

import api
import bot

log = logging.getLogger("pgbot.app")

# Наружу смотрит Caddy: TLS, статика, прокси на этот порт. Слушать 0.0.0.0
# значило бы отдавать API без TLS всем, кто дотянется до порта.
API_HOST = "127.0.0.1"
API_PORT = int(os.environ.get("API_PORT", "8080"))


def _bootstrap() -> dict:
    return bot.bootstrap()


async def _run_polling() -> None:
    await bot.run_polling()


async def _run_http() -> None:
    config = uvicorn.Config(api.app, host=API_HOST, port=API_PORT,
                            log_level="info", access_log=False)
    await uvicorn.Server(config).serve()


async def main() -> None:
    _bootstrap()
    log.info("http: %s:%s", API_HOST, API_PORT)
    # Падение любой из двух корутин роняет процесс: контейнер с живым HTTP и
    # мёртвым polling выглядит здоровым, restart не срабатывает, и пилоты
    # молча остаются без бота.
    async with asyncio.TaskGroup() as tg:
        tg.create_task(_run_polling())
        tg.create_task(_run_http())


if __name__ == "__main__":
    asyncio.run(main())
```

`asyncio.TaskGroup` требует Python 3.11+; в образе 3.12 — подходит. Он же отменяет вторую задачу при падении первой, чего `asyncio.gather` без `return_exceptions=False` не делает чисто.

`TaskGroup` заворачивает исключение в `ExceptionGroup`. Тесты шага 1 ждут `RuntimeError`. Привести к одному: либо тесты ловят `ExceptionGroup`/`BaseExceptionGroup`, либо `main()` разворачивает группу. **Выбрать первое** — разворачивать группу значит терять вторую ошибку, если упали обе. Поправить два теста на:

```python
    with pytest.raises(BaseExceptionGroup):
        await asyncio.wait_for(app.main(), timeout=5)
```

- [ ] **Step 5: Обновить `Dockerfile`**

```dockerfile
CMD ["python", "-u", "app.py"]
```

- [ ] **Step 6: Тесты проходят**

Run: `python -m pytest tests/test_app_entry.py -q`
Expected: PASS, 5 тестов.

- [ ] **Step 7: Проверить руками, что процесс поднимается**

```bash
BOT_TOKEN=42:TEST DB_PATH=/tmp/pgcheck.db API_PORT=8099 timeout 5 python app.py 2>&1 | head -20
```
Expected: строка `http: 127.0.0.1:8099` в логе. Polling с фальшивым токеном отвалится — это ожидаемо и подтверждает, что процесс падает целиком, а не работает наполовину.

- [ ] **Step 8: Полный прогон**

Run: `python -m pytest -q`
Expected: 955 passed.

- [ ] **Step 9: Коммит**

```bash
git add app.py bot.py Dockerfile tests/test_app_entry.py
git commit -m "feat(app): бот и API в одном процессе, падение любого роняет оба"
```

---

### Task 9: страница-заглушка, Caddy, compose, README

Последняя задача проверяет то, что тестами не проверяется: настоящую подпись из настоящего клиента Telegram.

**Files:**
- Create: `static/index.html`
- Create: `Caddyfile`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `api.py` (отдача статики)
- Modify: `README.md`
- Create: `tests/test_api_static.py`

- [ ] **Step 1: Написать падающие тесты**

`tests/test_api_static.py`:

```python
"""Статика и здоровье процесса."""
import pytest


async def test_health_needs_no_authorization(client):
    """Проверка живости не должна требовать initData: её дёргает Docker,
    у которого никакой подписи нет."""
    r = await client.get("/api/health")
    assert r.status_code == 200


async def test_health_says_which_db_is_open(client):
    """Самая частая ошибка раскатки — том не примонтирован и база пустая.
    Число стартов в ответе показывает это одной командой."""
    body = (await client.get("/api/health")).json()
    assert body["sites"] == 2


async def test_the_smoke_page_is_served(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "telegram-web-app.js" in r.text


async def test_the_smoke_page_needs_no_authorization(client):
    """Страница обязана открыться без подписи — она её как раз и добывает."""
    assert (await client.get("/")).status_code == 200
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `python -m pytest tests/test_api_static.py -q`
Expected: FAIL, 404.

- [ ] **Step 3: Написать страницу-заглушку**

`static/index.html` — намеренно уродливая и однофайловая: её задача прожить до фазы 4 и ответить на один вопрос — сходится ли подпись на живом устройстве.

```html
<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pgbot — проверка связи</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  body { font: 15px/1.5 system-ui, sans-serif; margin: 0; padding: 16px;
         background: var(--tg-theme-bg-color, #fff);
         color: var(--tg-theme-text-color, #000); }
  pre  { white-space: pre-wrap; word-break: break-all;
         background: var(--tg-theme-secondary-bg-color, #f1f1f1);
         padding: 12px; border-radius: 8px; }
  .ok   { color: #16613A; font-weight: 600; }
  .fail { color: #C23A52; font-weight: 600; }
</style>
<h1>Проверка связи</h1>
<p id="verdict">Спрашиваю сервер…</p>
<pre id="out"></pre>
<script>
  const tg = window.Telegram?.WebApp;
  tg?.ready();
  const out = document.getElementById("out");
  const verdict = document.getElementById("verdict");

  (async () => {
    const initData = tg?.initData || "";
    if (!initData) {
      verdict.className = "fail";
      verdict.textContent = "initData пустая — страница открыта не из Telegram.";
      return;
    }
    try {
      const r = await fetch("/api/prefs", {
        headers: { Authorization: "tma " + initData },
      });
      verdict.className = r.ok ? "ok" : "fail";
      verdict.textContent = r.ok
        ? "Подпись принята, HTTP " + r.status
        : "Отказ, HTTP " + r.status;
      out.textContent = await r.text();
    } catch (e) {
      verdict.className = "fail";
      verdict.textContent = "Сеть недоступна: " + e;
    }
  })();
</script>
```

Внешний скрипт `telegram.org/js/telegram-web-app.js` обязателен: `window.Telegram.WebApp` появляется только из него.

Атрибут `integrity` на этот тег **не ставится**, и линтеры безопасности на это ругаются. Причина: адрес не версионирован, Telegram обновляет файл на месте, и любая контрольная сумма однажды перестанет сходиться — страница молча умрёт, а выглядеть это будет как сломанная авторизация. Это единственный внешний скрипт во всём проекте, и он приходит с того же домена, что подписывает `initData`.

- [ ] **Step 4: Отдавать статику и здоровье из `api.py`**

```python
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@router.get("/health")
async def health():
    """Без авторизации: дёргает Docker, у которого подписи нет.

    Число стартов показывает самую частую ошибку раскатки — не
    примонтированный том и, как следствие, пустую базу.
    """
    return {"ok": True, "db": store.DB_PATH, "sites": len(store.load_sites())}


app.include_router(router)

# Монтируется ПОСЛЕ роутера: StaticFiles на "/" перехватывает всё, до чего
# доходит, и повешенный первым съел бы /api/*.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
```

Добавить `from fastapi.staticfiles import StaticFiles`. Перенести `app.include_router(router)` в конец файла, если он стоял раньше.

В проде статику отдаёт Caddy, а не uvicorn. Монтирование оставлено, потому что оно же обслуживает тесты и запуск без Caddy, а расхождение «в тестах отдаётся, в проде нет» — источник ошибок, которые видно только на сервере.

- [ ] **Step 5: Написать `Caddyfile`**

```caddyfile
# Домен и пути к сертификату приходят из окружения (см. .env.example).
{$PUBLIC_DOMAIN} {
	# Свой купленный сертификат. Чтобы Caddy выпускал Let's Encrypt сам,
	# удалить эту строку целиком — всё остальное менять не нужно.
	tls /certs/fullchain.pem /certs/privkey.pem

	encode zstd gzip

	# Порядок обязателен: handle_path для /api/* стоит выше, иначе
	# file_server отдал бы 404 на каждый запрос приложения.
	handle /api/* {
		reverse_proxy pgbot:8080
	}

	handle {
		root * /srv/www
		try_files {path} /index.html
		file_server
	}
}
```

`try_files {path} /index.html` — задел на фазу 4: маршрутизация React работает на клиенте, и прямой заход на внутренний адрес обязан отдать `index.html`, а не 404.

- [ ] **Step 6: Обновить `docker-compose.yml`**

```yaml
services:
  pgbot:
    build: .
    restart: unless-stopped
    env_file: .env
    environment:
      - TZ=${TZ:-Asia/Tbilisi}
      - DB_PATH=/app/data/pgbot.db
      - API_PORT=8080
    volumes:
      - pgbot-data:/app/data
    expose:
      # Только внутрь сети compose: наружу смотрит Caddy, и опубликованный
      # порт отдавал бы API без TLS всем, кто дотянется до сервера.
      - "8080"
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    environment:
      - PUBLIC_DOMAIN=${PUBLIC_DOMAIN}
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - ./static:/srv/www:ro
      - ${TLS_CERT_DIR}:/certs:ro
      - caddy-data:/data
      - caddy-config:/config
    depends_on:
      - pgbot
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  pgbot-data:
  caddy-data:
  caddy-config:
```

`./static:/srv/www` — на фазе 4 заменится на `./webapp/dist:/srv/www`.

- [ ] **Step 7: Обновить `.env.example`**

Дописать:

```
# Домен приложения — тот же, что вы пропишете в BotFather на фазе 5
PUBLIC_DOMAIN=fly.example.com
# Каталог со своим сертификатом: внутри ожидаются fullchain.pem и privkey.pem
TLS_CERT_DIR=/etc/ssl/pgbot
# Порт uvicorn внутри сети compose; наружу не публикуется
API_PORT=8080
```

- [ ] **Step 8: Тесты проходят**

Run: `python -m pytest tests/test_api_static.py -q`
Expected: PASS, 4 теста.

- [ ] **Step 9: Проверить конфиг Caddy, не поднимая его**

```bash
docker run --rm -e PUBLIC_DOMAIN=fly.example.com \
  -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile
```
Expected: `Valid configuration`. Ошибка синтаксиса, найденная на сервере в момент раскатки, стоит дороже.

- [ ] **Step 10: Обновить README**

Добавить раздел о фазе 3:

- переменные `PUBLIC_DOMAIN`, `TLS_CERT_DIR`, `API_PORT`;
- `docker compose up -d` поднимает два контейнера;
- проверка: `curl -s https://$PUBLIC_DOMAIN/api/health` — должен вернуть число стартов;
- проверка подписи: временно повесить Web App кнопку на домен через BotFather и открыть `/` в клиенте Telegram — страница должна написать «Подпись принята»;
- как перейти на автоматический Let's Encrypt (удалить строку `tls`);
- отметить, что `static/` — заглушка и уедет на фазе 4.

Раздел раскатки на systemd (README:297) тоже правится: там `python bot.py` меняется на `python app.py`, и появляется оговорка, что без Caddy приложение работает только по 127.0.0.1.

- [ ] **Step 11: Полный прогон**

Run: `python -m pytest -q`
Expected: 959 passed.

- [ ] **Step 12: Коммит**

```bash
git add static Caddyfile docker-compose.yml .env.example api.py README.md \
        tests/test_api_static.py
git commit -m "feat(deploy): Caddy своим сертификатом, страница проверки подписи"
```

---

## Что остаётся невыясненным до живого клиента

**Участвует ли поле `signature` в HMAC-строке.** Документация Telegram исключает из `data_check_string` только `hash`; поле `signature` (Ed25519, для сторонней проверки) по её букве остаётся внутри. Реализация следует документации, и тест `test_signature_field_stays_inside_the_checked_string` фиксирует именно это поведение.

Если на живом устройстве каждый запрос получает 401 при верном токене — это первое, что нужно проверить: добавить `signature` в список исключаемых полей рядом с `hash` в `webauth.data_check_string` и поправить тот тест. Страница-заглушка из задачи 9 существует ровно для того, чтобы этот вопрос закрылся до того, как поверх него будет написан React.

---

## Проверка плана на себе

**Покрытие спеки.** Все эндпоинты раздела «3. API и авторизация» разобраны по задачам: `/api/sites` (3), `/api/elevation` (3), `/api/forecast` (4), `/api/forecast/wind-grid` (4), `/api/scan` (4), `/api/analysis` (5), `/api/route` (5), `/api/route/parse` (6), `/api/route/analysis` (5), `/api/routes` (6), `/api/prefs` (2). Валидация `initData` — задача 1, таблица кодов ошибок — задачи 2–7, троттлинг — задача 7, `app.py` и Caddy — задачи 8–9.

**Расхождения спеки с кодом, найденные при подготовке и учтённые:**

1. `forecast.get_wind_grid` отдаёт PNG, а спека требует числовой эндпоинт → задача 4 добавляет `wind_grid_data`, а PNG-функция начинает звать её, чтобы выборка уровней осталась одна.
2. `guards._allowed_ids` приватная, но нужна третьему модулю → задача 2 делает её публичной и убирает построчное предупреждение, которое на каждом HTTP-запросе утопило бы лог.
3. `ThrottleMiddleware` держит реестр in-flight внутри себя → задача 7 выносит его в общий, иначе гарантия «один запрос на пилота» действовала бы на каждой поверхности отдельно.
4. `bot.main()` слит из bootstrap и polling → задача 8 разделяет их, чтобы миграция выполнялась один раз до обеих поверхностей.
5. Спека называет `GET|POST|DELETE /api/routes` одной строкой; удаление по имени требует пути `/api/routes/{name}` → задача 6.
6. `route.points_from_rows` на плохих данных возвращает `None`, а не бросает `RouteError` (он писался для чтения из хранилища), и потолок числа точек не проверяет вовсе → задача 5 проверяет оба случая в адаптере, иначе битый запрос уехал бы в расчёт с `None` вместо точек.
7. Спека не упоминает `GET /api/sites/{name}`, но поиск по псевдониму («гуда» → «Гудаури») нужен приложению так же, как чату → добавлен в задаче 3.
8. Выбор разборщика файла (`_DOC_PARSERS`) и текст про KMZ живут в `bot.py` → задача 6 переносит их в `route.parse_upload`, иначе приложение отвечало бы на KMZ иначе, чем чат.
9. `GET /api/health` в спеке нет; добавлен в задаче 9, потому что раскатка за Caddy без проверки живости отлаживается только по логам, а самая частая её ошибка — не примонтированный том.

**Чего в плане намеренно нет:** PNG-эндпоинтов, вебхука, кнопки в BotFather (фаза 5), `webapp/` (фаза 4), переименования стартов (вне рамок спеки).

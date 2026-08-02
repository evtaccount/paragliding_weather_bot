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

# Кого пускает бот в тестах — ОБЕ поверхности сразу. Пустой ALLOWED_USER_IDS
# закрывает и чат (guards.WhitelistMiddleware), и приложение
# (api.current_user), поэтому список задаётся явно: иначе каждый тест проверял
# бы отказ вместо того, ради чего написан. Новому id достаётся отказ — ровно
# как чужому пилоту в проде, и вписать его сюда та же работа, что владельцу
# вписать пилота в .env.
#
# Список ОДИН на чат и на приложение намеренно: правило допуска у них общее
# (guards.allowed_ids), и вторая копия здесь означала бы, что тесты могут
# разъехаться там, где продакшен разъехаться не может. 1 — TEST_USER_ID,
# которым tests/tg.py подписывает обновления по умолчанию; остальные —
# «товарищи» из тестов на чужие маршруты, старты и настройки.
ALLOWED_IN_TESTS = "1,2,3,5,7,9,77,99,555,777"


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

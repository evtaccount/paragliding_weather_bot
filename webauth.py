"""Проверка `initData` Telegram Mini App.

Модуль ничего не знает про HTTP: на входе строка запроса и токен бота, на
выходе пользователь или AuthError. Так проверку можно тестировать без
поднятого сервера, а api.py остаётся тонким.
"""
import dataclasses
import hashlib
import hmac
import json
import time
import urllib.parse

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

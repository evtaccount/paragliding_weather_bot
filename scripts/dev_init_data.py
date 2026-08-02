#!/usr/bin/env python3
"""Подписанная initData для разработки без Telegram.

Нужна `vite dev` и Playwright: сервер проверяет подпись одинаково всегда, и
обхода проверки в продакшене нет намеренно — вместо него настоящая подпись,
выпущенная локально.

Живёт сутки: `webauth.MAX_AGE_SEC` отвергает просроченные, и перевыпуск —
это то же поведение, что у настоящего клиента Telegram.

    python scripts/dev_init_data.py --user-id 1 --token "$BOT_TOKEN"
"""
import argparse
import hashlib
import hmac
import json
import time
import urllib.parse


def build(user_id: int, token: str, *, username: str = "dev", now: int | None = None) -> str:
    user = json.dumps({"id": user_id, "first_name": "Dev", "username": username},
                      ensure_ascii=False, separators=(",", ":"))
    pairs = {"auth_date": str(now if now is not None else int(time.time())),
             "query_id": "AAA-dev",
             "user": user}
    check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(pairs)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user-id", type=int, required=True)
    ap.add_argument("--token", required=True, help="BOT_TOKEN — тот же, что у сервера")
    ap.add_argument("--username", default="dev")
    a = ap.parse_args()
    print(build(a.user_id, a.token, username=a.username))


if __name__ == "__main__":
    main()

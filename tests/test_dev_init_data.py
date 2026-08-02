"""Скрипт разработки выпускает подпись, которую принимает настоящая проверка.

Смысл теста — не в скрипте, а в границе: подпись для `vite dev` и Playwright
делается тем же алгоритмом, что проверяет сервер. Разъедутся — разработка
пойдёт против поведения, которого в продакшене нет.
"""
import subprocess
import sys
import pathlib

import webauth

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKEN = "42:TEST"


def _run(*args: str) -> str:
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "dev_init_data.py"), *args],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_generated_init_data_passes_real_verification():
    raw = _run("--user-id", "777", "--token", TOKEN)
    user = webauth.verify(raw, TOKEN)
    assert user.id == 777


def test_generated_init_data_is_rejected_by_a_different_token():
    """Подпись привязана к токену, а не просто «выглядит правильно»."""
    raw = _run("--user-id", "777", "--token", TOKEN)
    try:
        webauth.verify(raw, "43:OTHER")
    except webauth.AuthError:
        return
    raise AssertionError("подпись чужим токеном принята")

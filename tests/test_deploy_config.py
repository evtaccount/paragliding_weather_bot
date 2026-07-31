"""Текстовые контракты деплойных файлов.

Caddyfile/Dockerfile/docker-compose.yml/Makefile никто не исполняет в тестах —
их роняет только ручной прогон `docker compose up` или `make check`. Здесь
проверяется то, что видно из текста: комментарий не расходится с кодом,
healthcheck существует и упомянут в обоих файлах, порт driven из одной
переменной, а не трёх независимых копий.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_caddyfile_comment_matches_the_directive_it_uses():
    """Комментарий называл handle_path, а код — handle. handle_path срезает
    префикс пути из URL; «починка» кода под комментарий отдавала бы 404 на
    каждый запрос к /api/*. Само слово упоминать можно (контраст поясняет
    выбор) — нельзя приписывать его директиве, которая реально стоит в блоке."""
    text = _read("Caddyfile")
    assert "handle_path для /api/*" not in text
    assert "handle /api/* {" in text


def test_makefile_check_uses_the_project_venv():
    """app.py требует Python 3.11+ (asyncio.TaskGroup). Системный `python3`
    может оказаться старше и падать по причине, не имеющей отношения к
    реальному синтаксису кода."""
    for line in _read("Makefile").splitlines():
        if "py_compile" in line:
            assert ".venv/bin/python" in line, line


def test_dockerfile_declares_a_healthcheck_against_the_api():
    text = _read("Dockerfile")
    assert "HEALTHCHECK" in text
    assert "/api/health" in text


def test_compose_caddy_waits_for_pgbot_to_report_healthy():
    text = _read("docker-compose.yml")
    assert "service_healthy" in text


def test_api_port_is_driven_from_a_single_source():
    """.env.example документирует API_PORT, но compose раньше жёстко прописывал
    8080 в environment — env_file .env его не мог переопределить (позже
    значение в environment: побеждает), и правка .env ничего не меняла."""
    compose = _read("docker-compose.yml")
    caddyfile = _read("Caddyfile")
    assert compose.count("${API_PORT:-8080}") >= 3  # pgbot env, expose, caddy env
    assert "{$API_PORT" in caddyfile

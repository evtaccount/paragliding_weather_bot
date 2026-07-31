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

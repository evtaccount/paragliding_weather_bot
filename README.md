# Paragliding forecast Telegram bot

Командный Telegram-бот: лётный прогноз для параплана по сохранённым стартам —
компактный эмодзи-текст + PNG-графики. Всё считает детерминированный движок
(`engine.py` / `charts.py`, из скилла `paragliding-forecast`). **Без LLM** —
пользователь шлёт команды, бот знает что делать.

```
Telegram → bot.py (aiogram) → forecast.py → engine.py (open-meteo) → текст + PNG
```

## Команды

| Команда | Что делает |
|---|---|
| `/today [старт]` | подробный прогноз на сегодня (+3 графика) |
| `/tomorrow [старт]` | подробный прогноз на завтра |
| `/threedays [старт]` | обзор на 3 дня (+бар-график) |
| `/week [старт]` | обзор на неделю |
| `/twoweeks [старт]` | обзор на 2 недели |
| `/forecast <старт> <диапазон>` | вручную: `1d · 3d · week · 2weeks` |
| `/sites` · `/help` | список стартов · справка |

Если старт не указан, а он один — берётся автоматически. Список команд виден в
меню Telegram (ставится на старте через `set_my_commands`).

## Что нужно

- **Токен бота** — у [@BotFather](https://t.me/BotFather): `/newbot`.
- Docker **или** Python 3.10+.

---

## Раскатка — вариант A: Docker (рекомендую)

```bash
cd paragliding-bot
cp .env.example .env          # впиши BOT_TOKEN
docker compose up -d --build
docker compose logs -f
```

- Шрифты (кириллица для графиков) и `tzdata` ставятся в образ автоматически.
- `sites.json` смонтирован с хоста (`:ro`) — правишь старты и делаешь
  `docker compose restart`, пересборка не нужна.
- Часовой пояс — переменная `TZ` (по умолчанию `Asia/Tbilisi`), от неё зависит,
  какой день считается «сегодня/завтра». Задать: `TZ=Europe/Moscow` в `.env`.
- Логи ротируются (10 МБ × 3).

Обновление: `git pull && docker compose up -d --build`.

## Раскатка — вариант B: systemd + venv (bare metal / VPS)

```bash
cd paragliding-bot
./deploy.sh            # venv, зависимости, проверка шрифтов, рендер unit-файла
# затем по подсказке скрипта:
#   отредактировать .env (BOT_TOKEN)
sudo cp deploy/pgbot.service /etc/systemd/system/pgbot.service
sudo systemctl daemon-reload && sudo systemctl enable --now pgbot
journalctl -u pgbot -f
```

`deploy.sh` сам подставит в unit-файл текущий путь, пользователя и python из venv.

> ⚠️ **Шрифты для графиков.** На Linux нужен кириллический TTF, иначе подписи на
> PNG будут «квадратиками» или мелким дефолтом. Docker ставит `fonts-dejavu-core`
> сам; для bare-metal: `sudo apt-get install -y fonts-dejavu-core`. `charts.py`
> ищет DejaVu / Liberation / Arial по стандартным путям.

## Локальный запуск (dev)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # BOT_TOKEN
python bot.py
```

Или через `make`: `make install`, `make run`, `make docker-up`, `make docker-logs`.

## Добавить старт

Отредактируй `sites.json` (формат как в скилле): `name`, `aliases`, `lat`, `lon`,
`elevation_m`, `aspect_deg` (куда смотрит склон). Перезапусти бот
(`docker compose restart` или `systemctl restart pgbot`).

## Структура

```
bot.py            aiogram-обработчики команд + меню, чистка временных PNG
forecast.py       резолв старта → запрос open-meteo (httpx) → текст + PNG
engine.py         оценка лётности + текст (общий со скиллом)
charts.py         PNG, светлая тема, м/с, кроссплатформенные шрифты
sites.json        сохранённые старты
Dockerfile · docker-compose.yml · .dockerignore
deploy.sh · deploy/pgbot.service.tmpl · Makefile
requirements.txt · .env.example
```

## Заметки

- Сеть нужна только для open-meteo; на сервере она открыта (ограничение `curl`
  было лишь в песочнице Claude Code).
- Windy **не** используется — его бесплатный ключ отдаёт перемешанный demo-шум.
- Движок общий со скиллом; при желании — вынести в отдельный пакет.

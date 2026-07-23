# Paragliding forecast Telegram bot

Командный Telegram-бот: лётный прогноз для параплана по сохранённым стартам —
разбор текстом + PNG-графики. Данные берутся из **open-meteo** (факты), а
**разбор — вердикт, лётное окно, риски, лучший день — делает Gemini** по этим
реальным числам, не выдумывая их. Без ключа Gemini бот работает на встроенных
детерминированных правилах (`engine.py`).

```
Telegram → bot.py → forecast.py → open-meteo (факты)
                                    ├── Pillow  → графики (визуализация фактов)
                                    └── Gemini  → анализ   (fallback: правила engine.py)
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

## Доступ и защита API

- **Whitelist** — `ALLOWED_USER_IDS=123456789,987654321` в `.env` (Telegram user ID
  через запятую). Пусто — бот открыт всем, в лог пишется предупреждение.
  Чужому пользователю бот отвечает отказом и показывает его ID — удобно
  пересылать владельцу для добавления.
- **Кулдаун** — не чаще одного прогноза в `COOLDOWN_SEC` секунд на пользователя
  (по умолчанию 10) и не более одного одновременного запроса от пользователя.
- **Кэш** — готовые прогнозы (текст + PNG) живут в памяти `CACHE_TTL_MIN` минут
  (по умолчанию 15): повторный запрос того же старта/диапазона не тратит
  квоты open-meteo и Gemini.

## Что нужно

- **Токен бота** — у [@BotFather](https://t.me/BotFather): `/newbot`.
- **Ключ Gemini** (бесплатный) — https://aistudio.google.com/apikey. Нужен для
  анализа; без него включается встроенный разбор на правилах.
- Docker **или** Python 3.10+.

---

## Раскатка — вариант A: Docker (рекомендую)

```bash
cd paragliding-bot
cp .env.example .env          # впиши BOT_TOKEN и GEMINI_API_KEY
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
cp .env.example .env          # BOT_TOKEN (+ GEMINI_API_KEY)
python bot.py
```

Или через `make`: `make install`, `make run`, `make docker-up`, `make docker-logs`.

## Добавить старт

Отредактируй `sites.json` (формат как в скилле): `name`, `aliases`, `lat`, `lon`,
`elevation_m`, `aspect_deg` (куда смотрит склон). Перезапусти бот
(`docker compose restart` или `systemctl restart pgbot`).

## Структура

```
bot.py            aiogram-обработчики команд + меню
guards.py         whitelist (ALLOWED_USER_IDS) + кулдаун запросов на пользователя
forecast.py       резолв старта → open-meteo → факты + графики → анализ (Gemini/правила)
analysis.py       Gemini: разбор реальных данных в лётную оценку (текст для Telegram)
engine.py         факты (facts_*), правила-фолбэк (report_*), графики; общий со скиллом
charts.py         PNG, светлая тема, м/с, кроссплатформенные шрифты
sites.json        сохранённые старты
Dockerfile · docker-compose.yml · .dockerignore
deploy.sh · deploy/pgbot.service.tmpl · Makefile
requirements.txt · .env.example
```

## Заметки

- **LLM анализирует факты, а не сочиняет числа.** Данные всегда из open-meteo;
  Gemini лишь интерпретирует их (можно спросить у него нюансы, комбинации
  факторов). Если Gemini недоступен — включается разбор на правилах `engine.py`.
- Windy **не** используется — его бесплатный ключ отдаёт перемешанный demo-шум
  (вот это и есть пример «LLM/сервис выдумывает числа» — так нельзя).
- Сеть нужна для open-meteo и Gemini; на сервере она открыта (ограничение `curl`
  было лишь в песочнице Claude Code).
- Движок общий со скиллом; при желании — вынести в отдельный пакет.

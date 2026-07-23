# Paragliding forecast Telegram bot

Командный Telegram-бот: лётный прогноз для параплана по сохранённым стартам —
компактный эмодзи-текст + PNG-графики. Всё считает детерминированный движок
(`engine.py` / `charts.py`, взяты из скилла `paragliding-forecast`). **Без LLM** —
пользователь шлёт команды, бот знает что делать.

```
Telegram → bot.py (aiogram) → forecast.py → engine.py (open-meteo) → текст + PNG
```

## Что нужно

- **Токен бота** — у [@BotFather](https://t.me/BotFather): `/newbot`.
- Python 3.10+

## Установка

```bash
cd ~/paragliding-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # впиши BOT_TOKEN
python bot.py
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
| `/sites` | список стартов |
| `/help` | справка |

Если старт не указан, а он один — берётся автоматически. Список команд
показывается в меню Telegram (настраивается на старте через `set_my_commands`).

`1d` — 3 графика (метеограмма, потолок, ветер по высотам); обзоры — 1 бар-график.

## Добавить старт

Отредактируй `sites.json` (формат как в скилле): `name`, `aliases`, `lat`, `lon`,
`elevation_m`, `aspect_deg` (куда смотрит склон). Перезапусти бот.

## Деплой (systemd)

```ini
# /etc/systemd/system/pgbot.service
[Unit]
Description=Paragliding forecast bot
After=network-online.target

[Service]
WorkingDirectory=/home/<user>/paragliding-bot
ExecStart=/home/<user>/paragliding-bot/.venv/bin/python bot.py
EnvironmentFile=/home/<user>/paragliding-bot/.env
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now pgbot
journalctl -u pgbot -f
```

## Заметки

- Сеть нужна только для open-meteo; на нормальном сервере она открыта (ограничение
  `curl` было лишь в песочнице Claude Code).
- Windy **не** используется — его бесплатный ключ отдаёт перемешанный demo-шум.
- Движок общий со скиллом; при желании вынести в отдельный пакет, чтобы не дублировать.

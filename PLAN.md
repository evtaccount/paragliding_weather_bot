# PLAN: защита от абьюза API (open-meteo + Gemini)

Ветка: `feature/abuse-protection`

## Решено с пользователем
- Доступ: только whitelist (я + друзья), `ALLOWED_USER_IDS` в `.env`.
- Слои защиты: TTL-кэш прогнозов + кулдаун на пользователя.
- Дневной бюджет Gemini — НЕ делаем.
- Мелкие находки ревью (сырой текст исключения пользователю, `SystemExit` из `engine.find_site`) — не трогаем без отдельной просьбы.

## Шаги
1. [x] Ветка `feature/abuse-protection`.
2. [x] `guards.py` — новый модуль:
   - `WhitelistMiddleware` (outer): `ALLOWED_USER_IDS` (csv в env). Пусто → бот открыт + WARNING в лог. Чужому — отказ с его Telegram ID (не чаще 1 раза в 60с на юзера, чтобы бот сам не спамил).
   - `ThrottleMiddleware`: только для хендлеров с флагом `forecast` — не чаще 1 запроса в `COOLDOWN_SEC` (деф. 10с) и не более 1 запроса одновременно от юзера.
3. [x] `forecast.py` — in-memory TTL-кэш: ключ `(канон. имя старта, rng, date)`, TTL `CACHE_TTL_MIN` (деф. 15 мин); значение `(text, [png_bytes])`. PNG читаются в байты, temp-dir удаляется сразу в forecast.
4. [x] `bot.py` — регистрация middleware, флаг `forecast` на команды прогноза, отправка PNG через `BufferedInputFile`, убрать чистку temp-dir (переехала в forecast).
5. [x] `.env.example` + README: новые переменные `ALLOWED_USER_IDS`, `COOLDOWN_SEC`, `CACHE_TTL_MIN`.
6. [x] Проверка: py_compile OK; смоук-тест (whitelist / открытый режим / кулдаун / in-flight / кэш) — все прошли; `import bot` OK.
7. [x] Коммит. Мерж — только по команде пользователя.

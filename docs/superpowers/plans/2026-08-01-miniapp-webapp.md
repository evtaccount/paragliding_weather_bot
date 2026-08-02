# Интерфейс мини-приложения — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перенести макет `miniapp/prototype.html` в работающее приложение на Vite + React + TypeScript поверх готового HTTP-слоя — четыре экрана и десять шторок, с настоящей картой и настоящими графиками.

**Architecture:** Приложение живёт в `webapp/`, собирается Vite в `webapp/dist` и попадает в образ отдельным этапом сборки на Node; отдаёт его FastAPI тем же `StaticFiles`, что сейчас держит заглушку. Данные идут через тонкий клиент с подписью Telegram и TanStack Query; тяжёлые запросы проходят через одну очередь, чтобы не биться в серверное ограничение «один запрос на пилота». Графики нарисованы своими компонентами на SVG, палитра берётся из `charts.py` и сверяется питоновским тестом.

**Tech Stack:** Vite 6, React 19, TypeScript 5 (strict), TanStack Query 5, Leaflet 1.9, Vitest 3 + Testing Library, Playwright 1.5x, Node 22 LTS.

## Global Constraints

- Экраны и шторки повторяют `miniapp/prototype.html` — он в репозитории и является источником вёрстки, текстов и раскладки. Номера строк указаны в задачах.
- Весь текст интерфейса на русском, как в макете и в боте.
- TypeScript в режиме `strict`. `any` запрещён; там, где тип ответа неизвестен, используется `unknown` с сужением.
- Новые зависимости только те, что названы в Tech Stack. Ничего сверх — ни UI-библиотек, ни библиотек графиков, ни роутера, ни менеджера состояния.
- Автоматических повторов запросов нет ни у одного хука: `retry: false`. Повтор только по нажатию пилота.
- Тяжёлые запросы (`/api/forecast`, `/api/forecast/wind-grid`, `/api/scan`, `/api/analysis`, `/api/route`, `/api/route/analysis`, `/api/elevation`) идут через очередь из `api/queue.ts`. Лёгкие (`/api/prefs`, `/api/sites`, `/api/routes`, `/api/route/parse`) — мимо неё.
- Проверка подписи на сервере не ослабляется ни на строку. Для разработки подпись выпускается локально скриптом настоящим `BOT_TOKEN`.
- Тайлы карты запрашиваются только у своего домена, путём `/tiles/{z}/{x}/{y}.png`. Прямых обращений к `tile.openstreetmap.org` из клиента быть не должно.
- Цвета берутся только из `webapp/src/charts/palette.ts`; литералов цвета в компонентах нет.
- Скрипт `telegram-web-app.js` подключается с домена Telegram **без** атрибута `integrity`. Это не упущение: Telegram обновляет файл по месту и хешей не публикует, поэтому проверка целостности сломала бы приложение при первом же их обновлении. Другого способа получить `window.Telegram.WebApp` нет — это единственный внешний скрипт во всём приложении.
- После каждой задачи: `npm --prefix webapp run build` собирается, `make test` зелёный.
- Коммит после каждой задачи. Ветка `feature/miniapp-webapp`.

---

## Раскладка файлов

```
webapp/
  index.html                 корневой документ Vite
  package.json               зависимости и скрипты
  tsconfig.json              strict
  vite.config.ts             сборка и настройка Vitest
  playwright.config.ts       сквозные тесты (задача 14)
  test/
    setup.ts                 подключение jest-dom
    fixtures/*.json          настоящие ответы API, сгенерированные из tests/fixtures.py
  e2e/                       сценарии Playwright (задача 14)
  src/
    main.tsx                 провайдеры, тема, инициализация Telegram
    App.tsx                  шапка, вкладки, стек шторок
    telegram.ts              обёртка над window.Telegram.WebApp
    format.ts                числа, даты, ветер, стороны света
    api/
      types.ts               типы ответов API
      client.ts              fetch с подписью, перевод кодов ошибок
      queue.ts               очередь тяжёлых запросов
      queries.ts             хуки TanStack Query
    ui/
      Sheet.tsx  Chip.tsx  Row.tsx  Spinner.tsx  ErrorBox.tsx
    charts/
      palette.ts  HourStrip.tsx  AirColumn.tsx  Meteogram.tsx  RouteProfile.tsx
    map/
      MapView.tsx  pins.ts
    screens/
      Forecast.tsx  Overview.tsx  Route.tsx  Settings.tsx
    sheets/
      WindGridSheet.tsx  MeteogramSheet.tsx  DayAnalysisSheet.tsx
      PointCardSheet.tsx  RouteAnalysisSheet.tsx  SitePickerSheet.tsx
      ModelPickerSheet.tsx  SavedRoutesSheet.tsx  NewRouteSheet.tsx
      AddSiteSheet.tsx
scripts/
  dev_init_data.py           выпуск подписанной initData для разработки
  dump_api_fixtures.py       генерация webapp/test/fixtures/*.json
```

Изменяемые файлы вне `webapp/`: `Makefile`, `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `Caddyfile`, `api.py` (константа `STATIC_DIR`), `README.md`, `tests/test_deploy_config.py`, `tests/test_palette_sync.py` (новый), `tests/test_dev_init_data.py` (новый).

---

### Task 1: Каркас проекта и подпись для разработки

Приложение ещё ничего не показывает, но собирается, тестируется и умеет получить подпись без Telegram.

**Files:**
- Create: `webapp/package.json`, `webapp/tsconfig.json`, `webapp/vite.config.ts`, `webapp/index.html`, `webapp/src/main.tsx`, `webapp/src/App.tsx`, `webapp/test/setup.ts`, `webapp/src/App.test.tsx`
- Create: `scripts/dev_init_data.py`, `tests/test_dev_init_data.py`
- Modify: `Makefile`, `.dockerignore`, `.gitignore`

**Interfaces:**
- Consumes: `webauth.verify(raw, bot_token)` из корня репозитория — принимает строку `initData` и бросает `webauth.AuthError`.
- Produces: `scripts/dev_init_data.py` печатает в stdout строку `initData`, которую принимает `webauth.verify`. Вызов: `python scripts/dev_init_data.py --user-id 1 --token <BOT_TOKEN>`.

- [ ] **Step 1: Написать питоновский тест на скрипт подписи**

`tests/test_dev_init_data.py`:

```python
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
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv/bin/python -m pytest tests/test_dev_init_data.py -q`
Expected: FAIL — `No such file or directory: scripts/dev_init_data.py`

- [ ] **Step 3: Написать скрипт**

`scripts/dev_init_data.py`:

```python
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
```

- [ ] **Step 4: Убедиться, что тест зелёный**

Run: `.venv/bin/python -m pytest tests/test_dev_init_data.py -q`
Expected: PASS (2 теста)

- [ ] **Step 5: Создать проект webapp**

`webapp/package.json`:

```json
{
  "name": "pgbot-webapp",
  "private": true,
  "type": "module",
  "engines": { "node": ">=22" },
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "test": "vitest"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.62.0",
    "leaflet": "^1.9.4",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.0",
    "@types/leaflet": "^1.9.15",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "jsdom": "^25.0.0",
    "typescript": "^5.7.0",
    "vite": "^6.0.0",
    "vitest": "^3.0.0"
  }
}
```

`webapp/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noEmit": true,
    "skipLibCheck": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "test", "vite.config.ts"]
}
```

`webapp/vite.config.ts`:

```ts
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    // Разработка идёт против настоящего API: подпись выпускается скриптом,
    // сервер не знает, что запрос пришёл не из Telegram, и не должен знать.
    proxy: { "/api": "http://127.0.0.1:8080", "/tiles": "http://127.0.0.1:8080" },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./test/setup.ts"],
    css: false,
  },
})
```

`webapp/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest"
```

`webapp/index.html`:

```html
<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
    <title>Прогноз для парапланеристов</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Написать падающий тест на корневой компонент**

`webapp/src/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react"
import { App } from "./App"

test("приложение показывает название", () => {
  render(<App />)
  expect(screen.getByText("Прогноз")).toBeInTheDocument()
})
```

- [ ] **Step 7: Установить зависимости и убедиться, что тест падает**

Run: `cd webapp && npm install && npm run test -- --run`
Expected: FAIL — `Failed to resolve import "./App"`

- [ ] **Step 8: Написать минимальные main.tsx и App.tsx**

`webapp/src/App.tsx`:

```tsx
export function App() {
  return <h1>Прогноз</h1>
}
```

`webapp/src/main.tsx`:

```tsx
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { App } from "./App"

const root = document.getElementById("root")
if (!root) throw new Error("нет корневого элемента")
createRoot(root).render(<StrictMode><App /></StrictMode>)
```

- [ ] **Step 9: Убедиться, что тест зелёный и сборка проходит**

Run: `cd webapp && npm run test -- --run && npm run build`
Expected: PASS, затем `dist/index.html` создан

- [ ] **Step 10: Подключить фронтенд к make и git**

В `Makefile` заменить цель `test` и добавить две новые (порядок целей в файле сохранить, справку `##` не потерять):

```makefile
test:               ## run python + webapp test suites
	.venv/bin/python -m pytest -q
	npm --prefix webapp run test -- --run

webapp-install:     ## install webapp dependencies
	npm --prefix webapp ci

webapp-build:       ## build the webapp into webapp/dist
	npm --prefix webapp run build
```

Добавить `webapp-install webapp-build` в строку `.PHONY`.

В `.dockerignore` добавить строки `webapp/node_modules` и `webapp/dist`.
В `.gitignore` добавить строки `webapp/node_modules`, `webapp/dist`, `webapp/test-results`.

- [ ] **Step 11: Полный прогон**

Run: `make test`
Expected: питоновские тесты зелёные, Vitest зелёный

- [ ] **Step 12: Коммит**

```bash
git add webapp scripts/dev_init_data.py tests/test_dev_init_data.py Makefile .dockerignore .gitignore
git commit -m "feat(webapp): каркас Vite + React + TypeScript и подпись для разработки"
```

---

### Task 2: Мост в Telegram

**Files:**
- Create: `webapp/src/telegram.ts`, `webapp/src/telegram.test.ts`

**Interfaces:**
- Produces:
  - `initData(): string` — строка подписи; пустая, если приложение открыто не из Telegram.
  - `colorScheme(): "light" | "dark"`
  - `themeVars(): Record<string, string>` — CSS-переменные вида `--tg-bg`, собранные из `themeParams`.
  - `ready(): void` — `WebApp.ready()` и `WebApp.expand()`.
  - `onBack(handler: (() => void) | null): void` — вешает обработчик и показывает кнопку «назад»; `null` прячет её.
  - `haptic(kind: "light" | "medium" | "error"): void`

- [ ] **Step 1: Написать падающие тесты**

`webapp/src/telegram.test.ts`:

```ts
import { beforeEach, expect, test, vi } from "vitest"
import * as tg from "./telegram"

type BackButton = { show: () => void; hide: () => void; onClick: (f: () => void) => void; offClick: (f: () => void) => void }

function fakeWebApp(over: Record<string, unknown> = {}) {
  const back: BackButton = { show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() }
  return {
    initData: "auth_date=1&hash=deadbeef",
    colorScheme: "dark",
    themeParams: { bg_color: "#101418", text_color: "#ffffff" },
    ready: vi.fn(),
    expand: vi.fn(),
    BackButton: back,
    HapticFeedback: { impactOccurred: vi.fn(), notificationOccurred: vi.fn() },
    ...over,
  }
}

beforeEach(() => {
  // @ts-expect-error — в тестах окно подделывается целиком
  delete window.Telegram
})

test("подпись берётся у Telegram", () => {
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: fakeWebApp() }
  expect(tg.initData()).toBe("auth_date=1&hash=deadbeef")
})

test("без Telegram подпись пустая, а не исключение", () => {
  expect(tg.initData()).toBe("")
})

test("тема раскладывается в css-переменные", () => {
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: fakeWebApp() }
  expect(tg.themeVars()).toEqual({ "--tg-bg-color": "#101418", "--tg-text-color": "#ffffff" })
})

test("без Telegram схема светлая", () => {
  expect(tg.colorScheme()).toBe("light")
})

test("обработчик назад вешается и кнопка показывается", () => {
  const app = fakeWebApp()
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: app }
  const h = () => {}
  tg.onBack(h)
  expect(app.BackButton.onClick).toHaveBeenCalledWith(h)
  expect(app.BackButton.show).toHaveBeenCalled()
})

test("null снимает обработчик и прячет кнопку", () => {
  const app = fakeWebApp()
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: app }
  const h = () => {}
  tg.onBack(h)
  tg.onBack(null)
  expect(app.BackButton.offClick).toHaveBeenCalledWith(h)
  expect(app.BackButton.hide).toHaveBeenCalled()
})
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd webapp && npm run test -- --run telegram`
Expected: FAIL — модуль `./telegram` не найден

- [ ] **Step 3: Написать модуль**

`webapp/src/telegram.ts` — обёртка над `window.Telegram.WebApp`. Требования:

- Тип `WebApp` описан локально (полей нужно немного), глобальное объявление через `declare global`.
- Функция доступа возвращает `undefined`, когда объекта нет: приложение, открытое в обычном браузере, должно показать «откройте из Telegram», а не упасть белым экраном.
- `themeVars` переводит ключи `themeParams` в CSS-переменные по правилу `bg_color` → `--tg-bg-color`; неизвестные ключи проходят тем же правилом, ничего не отбрасывается.
- `onBack` хранит текущий обработчик в модульной переменной, чтобы `offClick` получил ту же ссылку.
- `haptic` переводит `"error"` в `notificationOccurred("error")`, остальные — в `impactOccurred`.

- [ ] **Step 4: Убедиться, что тесты зелёные**

Run: `cd webapp && npm run test -- --run telegram`
Expected: PASS (6 тестов)

- [ ] **Step 5: Коммит**

```bash
git add webapp/src/telegram.ts webapp/src/telegram.test.ts
git commit -m "feat(webapp): обёртка над Telegram WebApp"
```

---

### Task 3: Настоящие ответы API как фикстуры и типы

Типы пишутся не по памяти, а по настоящим ответам, снятым с домена офлайн через `tests/fixtures.py`. Те же файлы становятся моками для тестов экранов.

**Files:**
- Create: `scripts/dump_api_fixtures.py`, `webapp/test/fixtures/*.json`, `webapp/src/api/types.ts`, `webapp/src/api/types.test.ts`, `tests/test_api_fixtures_fresh.py`

**Interfaces:**
- Produces: типы `Prefs`, `Model`, `Site`, `Facts`, `Assessment`, `HourFact`, `OverviewRow`, `WindGrid`, `WindLevel`, `Scan`, `RouteResult`, `RoutePoint`, `SavedRoute`, `Elevation`.
- Produces: `scripts/dump_api_fixtures.py` — пишет `webapp/test/fixtures/{prefs,sites,facts_1d,forecast_3d,overview_3d,wind_grid,scan,route,routes}.json`.
- Внимание, две разные формы: `GET /api/forecast` с `range=1d` отдаёт `engine.facts_1day`, а с `3d`/`week`/`2weeks` — `engine.facts_overview` (`forecast.py:347-349`). Это разные структуры. `engine.overview_rows` в ответ этого эндпоинта не попадает вовсе — он идёт только внутрь `/api/scan`. Фикстура `forecast_3d.json` описывает первое, `overview_3d.json` — второе, и путать их нельзя: экран обзора читает именно `forecast_3d`.

- [ ] **Step 1: Написать скрипт снятия фикстур**

`scripts/dump_api_fixtures.py` строит ответы теми же функциями домена, что и API, но на данных из `tests/fixtures.py` — без сети:

```python
#!/usr/bin/env python3
"""Настоящие ответы API в файлы, без сети.

Типы фронтенда и моки его тестов должны описывать то, что домен отдаёт на
самом деле. Написанные по памяти, они расходятся с бэкендом молча: экран
читает поле, которого нет, и показывает пустоту вместо числа.

Данные берутся из tests/fixtures.py — тех же, на которых стоят тесты домена.

    python scripts/dump_api_fixtures.py
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import engine  # noqa: E402
from tests import fixtures as fx  # noqa: E402

OUT = ROOT / "webapp" / "test" / "fixtures"

SITE = {"name": "Гудаури", "lat": 42.47, "lon": 44.48, "elevation_m": 2200,
        "aspect": "Ю", "aspect_deg": 180.0, "slope_deg": 25.0, "route_top_m": 3000.0,
        "aliases": ["gudauri"], "notes": ""}


def write(name: str, payload) -> None:
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path.relative_to(ROOT))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    day = fx.om_1day()
    week = fx.om_overview([f"2026-07-{d:02d}" for d in range(25, 32)])

    write("facts_1d", engine.facts_1day(day, SITE))
    write("wind_grid", engine.wind_grid(day, SITE))
    write("overview_3d", engine.overview_rows(week, SITE))
    write("sites", [SITE])
    write("prefs", {"avg_route_speed_kmh": 25.0, "wind_correction_enabled": True,
                    "model_key": "ecmwf",
                    "models": [{"key": k, "label": engine.model_label(k)} for k in engine.MODELS]})
    write("scan", {"sites": [{"name": SITE["name"], "aspect": SITE["aspect"],
                              "days": engine.overview_rows(week, SITE)[:2]}],
                   "empty": [], "failed": []})
    write("routes", [{"name": "Гудаури — Коби",
                      "points": [[42.47, 44.48, "старт"], [42.53, 44.51, "Коби"]],
                      "saved_at": "2026-07-25"}])


if __name__ == "__main__":
    main()
```

Для маршрута (`route.json`) данных `tests/fixtures.py` недостаточно: `forecast.get_route` ходит в сеть двумя запросами. Снять его нужно из существующего теста маршрута — в `tests/test_api_route.py` уже собран полный ответ; скопировать оттуда полезную нагрузку в `webapp/test/fixtures/route.json` вручную, сохранив все ключи.

- [ ] **Step 2: Снять фикстуры**

Run: `.venv/bin/python scripts/dump_api_fixtures.py`
Expected: семь путей напечатаны, файлы созданы

- [ ] **Step 3: Написать тест, что фикстуры не устарели**

`tests/test_api_fixtures_fresh.py`:

```python
"""Фикстуры фронтенда пересняты после правки домена.

Типы TypeScript и моки экранов описывают ЭТИ файлы. Домен поменял поле, файлы
остались старыми — фронтенд продолжает собираться и зеленеть на устаревшем
контракте, а ломается только в проде, у пилота.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "webapp" / "test" / "fixtures"


def test_fixtures_match_what_the_domain_returns_now(tmp_path):
    before = {p.name: json.loads(p.read_text(encoding="utf-8"))
              for p in FIX.glob("*.json") if p.name != "route.json"}
    subprocess.run([sys.executable, str(ROOT / "scripts" / "dump_api_fixtures.py")],
                   capture_output=True, text=True, check=True)
    after = {p.name: json.loads(p.read_text(encoding="utf-8"))
             for p in FIX.glob("*.json") if p.name != "route.json"}
    stale = sorted(n for n in after if before.get(n) != after[n])
    assert not stale, ("фикстуры устарели, переснимите: "
                       "python scripts/dump_api_fixtures.py — " + ", ".join(stale))
```

`route.json` исключён намеренно: он снят руками из теста маршрута, скрипт его не генерирует.

- [ ] **Step 4: Убедиться, что тест зелёный, и что он краснеет**

Run: `.venv/bin/python -m pytest tests/test_api_fixtures_fresh.py -q`
Expected: PASS

Проверить, что тест не пустой: временно поменять `"model_key": "ecmwf"` на `"gfs"` в `scripts/dump_api_fixtures.py`, прогнать — ожидается FAIL со списком файлов; вернуть обратно.

- [ ] **Step 5: Написать типы по фикстурам**

`webapp/src/api/types.ts` — типы, описывающие снятые файлы. Каждое поле берётся из фикстуры, не из головы. Обязательно:

```ts
export type Model = { key: string; label: string }

export type Prefs = {
  avg_route_speed_kmh: number
  wind_correction_enabled: boolean
  model_key: string
  models: Model[]
}

export type Site = {
  name: string
  lat: number
  lon: number
  elevation_m: number
  aspect: string | null
  aspect_deg: number | null
  slope_deg: number | null
  route_top_m: number | null
  aliases: string[]
  notes: string
}

export type Assessment = {
  score: number | null
  category: string
  label_ru: string
  limiting_factor: string | null
  limiting_factor_ru: string | null
  fly_window: number[] | null
  confidence: number
  warnings: string[]
  vetoes_in_window: string[]
  unchecked_vetoes: string[]
}

export type WindLevel = {
  label: string
  alt_m_msl: number
  is_launch: boolean
  hourly: { hour: number; wind_ms: number; dir_deg: number }[]
}

export type WindGrid = {
  date: string
  timezone: string | null
  launch_m: number
  hours: number[]
  levels: WindLevel[]
}

export type OverviewRow = {
  date: string
  emoji: string
  label: string
  score: number
  category: string
  limiting: string | null
  confidence: number
  fly_window: number[] | null
  tmax: number
  wmax: number
  gmax: number
  dom: number
  precip: number
  wc: number
}

export type Scan = {
  sites: { name: string; aspect: string | null; days: OverviewRow[] }[]
  empty: string[]
  failed: string[]
}

export type SavedRoute = { name: string; points: (number | string)[][]; saved_at: string }

export type Elevation = { elevation_m: number }
```

Остальные типы (`Facts`, `HourFact`, `RouteResult`, `RoutePoint`) выписать так же — по ключам файлов `facts_1d.json` и `route.json`, все поля обязательные, кроме тех, что в фикстуре равны `null` (у них тип с `| null`).

- [ ] **Step 6: Написать тест, что фикстуры сходятся с типами**

`webapp/src/api/types.test.ts`:

```ts
import prefs from "../../test/fixtures/prefs.json"
import sites from "../../test/fixtures/sites.json"
import facts from "../../test/fixtures/facts_1d.json"
import grid from "../../test/fixtures/wind_grid.json"
import overview from "../../test/fixtures/overview_3d.json"
import scan from "../../test/fixtures/scan.json"
import routes from "../../test/fixtures/routes.json"
import type { Prefs, Site, Facts, WindGrid, OverviewRow, Scan, SavedRoute } from "./types"

/* Проверка на этапе компиляции: `tsc --noEmit` в npm run build упадёт, если тип
   разошёлся с настоящим ответом. Тело теста нужно, чтобы файл считался тестом. */
test("фикстуры описываются типами", () => {
  const p: Prefs = prefs
  const s: Site[] = sites as Site[]
  const f: Facts = facts as unknown as Facts
  const g: WindGrid = grid as unknown as WindGrid
  const o: OverviewRow[] = overview as unknown as OverviewRow[]
  const c: Scan = scan as unknown as Scan
  const r: SavedRoute[] = routes
  expect([p, s, f, g, o, c, r].every(Boolean)).toBe(true)
})
```

В `webapp/tsconfig.json` добавить `"resolveJsonModule": true`.

- [ ] **Step 7: Прогон**

Run: `cd webapp && npm run build && npm run test -- --run types`
Expected: сборка проходит, тест зелёный

- [ ] **Step 8: Коммит**

```bash
git add scripts/dump_api_fixtures.py tests/test_api_fixtures_fresh.py webapp/test/fixtures webapp/src/api/types.ts webapp/src/api/types.test.ts webapp/tsconfig.json
git commit -m "feat(webapp): типы API по настоящим ответам домена"
```

---

### Task 4: Клиент API и перевод ошибок

**Files:**
- Create: `webapp/src/api/client.ts`, `webapp/src/api/client.test.ts`

**Interfaces:**
- Produces:
  - `class ApiError extends Error` с конструктором `(status: number, userMessage: string)` и одноимёнными полями. Порядок аргументов важен: его используют тесты задачи 6.
  - `async function apiGet<T>(path: string, params?: Record<string, string | undefined>): Promise<T>`
  - `async function apiSend<T>(method: "POST" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T>`
  - `async function apiUpload<T>(path: string, form: FormData): Promise<T>`

- [ ] **Step 1: Написать падающие тесты**

`webapp/src/api/client.test.ts`:

```ts
import { beforeEach, expect, test, vi } from "vitest"
import { ApiError, apiGet, apiSend } from "./client"

function reply(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json" },
  }))
}

beforeEach(() => {
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: { initData: "auth_date=1&hash=abc" } }
})

test("подпись уходит заголовком на каждом запросе", async () => {
  const fetchMock = vi.fn(() => reply(200, { ok: true }))
  vi.stubGlobal("fetch", fetchMock)
  await apiGet("/api/prefs")
  const [, init] = fetchMock.mock.calls[0]!
  expect((init as RequestInit).headers).toMatchObject({ Authorization: "tma auth_date=1&hash=abc" })
})

test("параметры со значением undefined в запрос не попадают", async () => {
  const fetchMock = vi.fn(() => reply(200, {}))
  vi.stubGlobal("fetch", fetchMock)
  await apiGet("/api/forecast", { site: "Гудаури", range: "1d", model: undefined })
  const [url] = fetchMock.mock.calls[0]!
  expect(String(url)).toBe("/api/forecast?site=%D0%93%D1%83%D0%B4%D0%B0%D1%83%D1%80%D0%B8&range=1d")
})

test("401 переводится в приглашение открыть из Telegram", async () => {
  vi.stubGlobal("fetch", () => reply(401, { detail: "initData не прошла проверку" }))
  await expect(apiGet("/api/prefs")).rejects.toMatchObject({
    status: 401, userMessage: "Откройте приложение из Telegram.",
  })
})

test("403 показывает текст сервера — в нём Telegram ID пилота", async () => {
  vi.stubGlobal("fetch", () => reply(403, { detail: "Это личный бот, доступ по списку. Твой Telegram ID: 7 — пришли его владельцу бота, чтобы тебя добавили." }))
  await expect(apiGet("/api/prefs")).rejects.toMatchObject({
    status: 403,
    userMessage: "Это личный бот, доступ по списку. Твой Telegram ID: 7 — пришли его владельцу бота, чтобы тебя добавили.",
  })
})

test("429 переводится в «уже считаю»", async () => {
  vi.stubGlobal("fetch", () => reply(429, { detail: "Уже считаю — дождись ответа." }))
  await expect(apiGet("/api/scan")).rejects.toMatchObject({
    status: 429, userMessage: "Уже считаю — дождись ответа.",
  })
})

test("502 переводится в сообщение про источник данных", async () => {
  vi.stubGlobal("fetch", () => reply(502, { detail: "источник данных недоступен" }))
  await expect(apiGet("/api/forecast")).rejects.toMatchObject({
    status: 502, userMessage: "open-meteo сейчас недоступна. Попробуйте ещё раз.",
  })
})

test("400 отдаёт текст сервера дословно — он написан для пилота", async () => {
  vi.stubGlobal("fetch", () => reply(400, { detail: "неизвестная модель: марс" }))
  await expect(apiSend("PATCH", "/api/prefs", { model_key: "марс" })).rejects.toMatchObject({
    status: 400, userMessage: "неизвестная модель: марс",
  })
})

test("204 не пытается разобрать пустое тело", async () => {
  vi.stubGlobal("fetch", () => Promise.resolve(new Response(null, { status: 204 })))
  await expect(apiSend("DELETE", "/api/sites/Гудаури")).resolves.toBeNull()
})

test("ответ не в json не роняет разбор", async () => {
  vi.stubGlobal("fetch", () => Promise.resolve(new Response("<html>502</html>", { status: 502 })))
  await expect(apiGet("/api/forecast")).rejects.toBeInstanceOf(ApiError)
})
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd webapp && npm run test -- --run client`
Expected: FAIL — модуль `./client` не найден

- [ ] **Step 3: Написать клиент**

`webapp/src/api/client.ts`. Требования:

- Заголовок `Authorization: tma <initData>` вешается на каждый запрос из `telegram.initData()`.
- Тело ошибки читается как json; если разбор не удался — `detail` считается пустым.
- Таблица перевода кодов (`userMessage`):
  - 401 → `"Откройте приложение из Telegram."`
  - 403 → текст `detail` как есть (в нём Telegram ID пилота, который надо переслать владельцу)
  - 429 → текст `detail`, а при пустом — `"Уже считаю — дождись ответа."`
  - 502 → `"open-meteo сейчас недоступна. Попробуйте ещё раз."`
  - 400 и прочие 4xx → текст `detail`, а при пустом — `"Запрос не принят."`
  - 5xx кроме 502 → `"Сервер не ответил. Попробуйте ещё раз."`
- Статус 204 возвращает `null` без разбора тела.
- `apiGet` собирает строку запроса, отбрасывая параметры со значением `undefined`.
- `apiUpload` шлёт `FormData` и **не** ставит `Content-Type` — его выставляет браузер вместе с границей раздела.

- [ ] **Step 4: Убедиться, что тесты зелёные**

Run: `cd webapp && npm run test -- --run client`
Expected: PASS (9 тестов)

- [ ] **Step 5: Коммит**

```bash
git add webapp/src/api/client.ts webapp/src/api/client.test.ts
git commit -m "feat(webapp): клиент API с подписью и переводом кодов ошибок"
```

---

### Task 5: Очередь тяжёлых запросов и хуки данных

**Files:**
- Create: `webapp/src/api/queue.ts`, `webapp/src/api/queue.test.ts`, `webapp/src/api/queries.ts`, `webapp/src/api/queries.test.tsx`

**Interfaces:**
- Produces: `function heavy<T>(task: () => Promise<T>): Promise<T>` — выполняет задачи по одной в порядке поступления.
- Produces хуки: `usePrefs()`, `useUpdatePrefs()`, `useSites()`, `useCreateSite()`, `useDeleteSite()`, `useForecast(site, range, date, model)`, `useWindGrid(site, date, model)`, `useScan(model)`, `useAnalysis()`, `useRoute()`, `useRouteAnalysis()`, `useParseRoute()`, `useSavedRoutes()`, `useSaveRoute()`, `useDeleteRoute()`, `useElevation()`.

- [ ] **Step 1: Написать падающие тесты очереди**

`webapp/src/api/queue.test.ts`:

```ts
import { expect, test } from "vitest"
import { heavy } from "./queue"

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

test("второй запрос ждёт первого, а не уходит параллельно", async () => {
  const first = deferred<string>()
  const started: string[] = []

  const a = heavy(() => { started.push("a"); return first.promise })
  const b = heavy(() => { started.push("b"); return Promise.resolve("b") })

  expect(started).toEqual(["a"])   // b ещё не начинался
  first.resolve("a")
  await expect(a).resolves.toBe("a")
  await expect(b).resolves.toBe("b")
  expect(started).toEqual(["a", "b"])
})

test("падение задачи не запирает очередь навсегда", async () => {
  const boom = heavy(() => Promise.reject(new Error("сеть")))
  await expect(boom).rejects.toThrow("сеть")
  await expect(heavy(() => Promise.resolve(7))).resolves.toBe(7)
})

test("порядок сохраняется", async () => {
  const done: number[] = []
  await Promise.all([1, 2, 3].map((n) => heavy(async () => { done.push(n) })))
  expect(done).toEqual([1, 2, 3])
})
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd webapp && npm run test -- --run queue`
Expected: FAIL — модуль `./queue` не найден

- [ ] **Step 3: Написать очередь**

`webapp/src/api/queue.ts`. Требования: одна модульная цепочка промисов; следующая задача стартует в `finally` предыдущей, поэтому отказ не запирает очередь; порядок — строго тот, в котором вызвали. В комментарии объяснить, зачем: сервер отвечает 429 на второй одновременный тяжёлый запрос пилота (`api.one_at_a_time`), и очередь на клиенте нужна, чтобы приложение в это ограничение не билось.

- [ ] **Step 4: Убедиться, что тесты очереди зелёные**

Run: `cd webapp && npm run test -- --run queue`
Expected: PASS (3 теста)

- [ ] **Step 5: Написать тест на хуки**

`webapp/src/api/queries.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook, waitFor } from "@testing-library/react"
import { expect, test, vi, beforeEach } from "vitest"
import type { ReactNode } from "react"
import { usePrefs, useForecast } from "./queries"
import prefsFixture from "../../test/fixtures/prefs.json"

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

beforeEach(() => {
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: { initData: "auth_date=1&hash=abc" } }
})

test("настройки приходят и отдаются как есть", async () => {
  vi.stubGlobal("fetch", () => Promise.resolve(new Response(JSON.stringify(prefsFixture),
    { status: 200, headers: { "content-type": "application/json" } })))
  const { result } = renderHook(() => usePrefs(), { wrapper })
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  expect(result.current.data?.model_key).toBe("ecmwf")
})

test("прогноз не запрашивается, пока старт не выбран", () => {
  const fetchMock = vi.fn()
  vi.stubGlobal("fetch", fetchMock)
  renderHook(() => useForecast(null, "1d", null, null), { wrapper })
  expect(fetchMock).not.toHaveBeenCalled()
})

test("ошибка не повторяется автоматически", async () => {
  const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail: "нет" }),
    { status: 500, headers: { "content-type": "application/json" } })))
  vi.stubGlobal("fetch", fetchMock)
  const { result } = renderHook(() => usePrefs(), { wrapper })
  await waitFor(() => expect(result.current.isError).toBe(true))
  expect(fetchMock).toHaveBeenCalledTimes(1)
})
```

- [ ] **Step 6: Убедиться, что тест падает**

Run: `cd webapp && npm run test -- --run queries`
Expected: FAIL — модуль `./queries` не найден

- [ ] **Step 7: Написать хуки**

`webapp/src/api/queries.ts`. Требования:

- Ключи запросов начинаются с имени ресурса: `["prefs"]`, `["sites"]`, `["routes"]`, `["forecast", site, range, date, model]`, `["windGrid", site, date, model]`, `["scan", model]`.
- Все запросы: `retry: false`, `staleTime: 5 * 60_000`, `gcTime: 30 * 60_000`. Причина в комментарии: серверный кэш живёт `CACHE_TTL_MIN` (по умолчанию 15 минут), клиентский держится вдвое короче, чтобы не показывать устаревшее дольше сервера.
- Тяжёлые запросы оборачиваются в `heavy(...)`, лёгкие — нет. Перечень тяжёлых — в Global Constraints.
- Запросы с недостающими данными не уходят: `enabled: site !== null` и подобное.
- Мутации, меняющие настройки или списки, инвалидируют соответствующий ключ (`prefs`, `sites`, `routes`).

- [ ] **Step 8: Прогон**

Run: `cd webapp && npm run test -- --run && npm run build`
Expected: всё зелёное

- [ ] **Step 9: Коммит**

```bash
git add webapp/src/api/queue.ts webapp/src/api/queue.test.ts webapp/src/api/queries.ts webapp/src/api/queries.test.tsx
git commit -m "feat(webapp): очередь тяжёлых запросов и хуки данных"
```

---

### Task 6: Оболочка приложения

Шапка с контекстом, четыре вкладки, стек шторок, тема Telegram. Экраны пока заглушки — их наполняют следующие задачи.

**Files:**
- Create: `webapp/src/ui/Sheet.tsx`, `webapp/src/ui/Chip.tsx`, `webapp/src/ui/Row.tsx`, `webapp/src/ui/Spinner.tsx`, `webapp/src/ui/ErrorBox.tsx`, `webapp/src/ui/ui.test.tsx`, `webapp/src/format.ts`, `webapp/src/format.test.ts`, `webapp/src/styles.css`
- Modify: `webapp/src/App.tsx`, `webapp/src/App.test.tsx`, `webapp/src/main.tsx`

**Interfaces:**
- Produces: `useSheets()` — стек шторок: `{ push(node, title), pop(), stack }`. Живёт в `App.tsx` и передаётся через контекст `SheetsContext`.
- Produces из `format.ts`: `fmtNum(v, dec?)`, `fmtDate(iso)`, `compass(deg)`, `fmtWind(ms)`, `fmtHour(h)`.

- [ ] **Step 1: Написать тесты форматирования**

`webapp/src/format.test.ts`:

```ts
import { expect, test } from "vitest"
import { compass, fmtDate, fmtHour, fmtNum } from "./format"

test("дробная часть отделяется запятой, как в боте", () => {
  expect(fmtNum(3.14, 1)).toBe("3,1")
  expect(fmtNum(7)).toBe("7")
})

test("направление ветра переводится в румб", () => {
  expect(compass(0)).toBe("С")
  expect(compass(180)).toBe("Ю")
  expect(compass(359)).toBe("С")
  expect(compass(-1)).toBe("С")     // отрицательные градусы нормализуются
})

test("дата показывается коротко и с днём недели", () => {
  expect(fmtDate("2026-07-25")).toBe("сб, 25 июля")
})

test("час дополняется нулём", () => {
  expect(fmtHour(9)).toBe("09:00")
  expect(fmtHour(14)).toBe("14:00")
})
```

- [ ] **Step 2: Убедиться, что тест падает, и написать format.ts**

Run: `cd webapp && npm run test -- --run format` → FAIL.
Написать `webapp/src/format.ts`; румбы взять из макета (`CARD16` и `compass`, `miniapp/prototype.html:497-499`), формат числа — оттуда же (`num`, строка 715).
Run снова: PASS (4 теста).

- [ ] **Step 3: Написать тесты оболочки**

`webapp/src/App.test.tsx` (заменяет содержимое из задачи 1):

```tsx
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import { App } from "./App"

beforeEach(() => {
  const back = { show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() }
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: {
    initData: "auth_date=1&hash=abc", colorScheme: "dark",
    themeParams: { bg_color: "#101418" }, ready: vi.fn(), expand: vi.fn(),
    BackButton: back, HapticFeedback: { impactOccurred: vi.fn(), notificationOccurred: vi.fn() },
  } }
  vi.stubGlobal("fetch", () => Promise.resolve(new Response("{}", {
    status: 200, headers: { "content-type": "application/json" } })))
})

test("видны четыре вкладки", () => {
  render(<App />)
  for (const name of ["Прогноз", "Обзор", "Маршрут", "Настройки"]) {
    expect(screen.getByRole("tab", { name })).toBeInTheDocument()
  }
})

test("нажатие вкладки меняет активную", async () => {
  render(<App />)
  await userEvent.click(screen.getByRole("tab", { name: "Настройки" }))
  expect(screen.getByRole("tab", { name: "Настройки" })).toHaveAttribute("aria-selected", "true")
  expect(screen.getByRole("tab", { name: "Прогноз" })).toHaveAttribute("aria-selected", "false")
})

test("без Telegram приложение объясняет, что делать, а не показывает пустоту", () => {
  // @ts-expect-error — Telegram отсутствует
  delete window.Telegram
  render(<App />)
  expect(screen.getByText(/Откройте приложение из Telegram/)).toBeInTheDocument()
})
```

`webapp/src/ui/ui.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, test, vi } from "vitest"
import { Sheet } from "./Sheet"
import { ErrorBox } from "./ErrorBox"
import { ApiError } from "../api/client"

test("шторка показывает заголовок и содержимое", () => {
  render(<Sheet title="Ветер по высотам" onClose={() => {}}><p>тело</p></Sheet>)
  expect(screen.getByText("Ветер по высотам")).toBeInTheDocument()
  expect(screen.getByText("тело")).toBeInTheDocument()
})

test("крестик закрывает шторку", async () => {
  const onClose = vi.fn()
  render(<Sheet title="Заголовок" onClose={onClose}><p>тело</p></Sheet>)
  await userEvent.click(screen.getByRole("button", { name: "Закрыть" }))
  expect(onClose).toHaveBeenCalled()
})

test("ошибка показывает понятный текст и кнопку повтора", async () => {
  const onRetry = vi.fn()
  render(<ErrorBox error={new ApiError(502, "open-meteo сейчас недоступна. Попробуйте ещё раз.")} onRetry={onRetry} />)
  expect(screen.getByText(/open-meteo сейчас недоступна/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Повторить" }))
  expect(onRetry).toHaveBeenCalled()
})

test("при 401 повтора нет — повторять нечего, надо открыть из Telegram", () => {
  render(<ErrorBox error={new ApiError(401, "Откройте приложение из Telegram.")} onRetry={() => {}} />)
  expect(screen.queryByRole("button", { name: "Повторить" })).not.toBeInTheDocument()
})
```

- [ ] **Step 4: Убедиться, что тесты падают**

Run: `cd webapp && npm run test -- --run`
Expected: FAIL — компоненты не существуют

- [ ] **Step 5: Написать оболочку и компоненты**

Требования:

- `App.tsx`: `QueryClientProvider`, вызов `telegram.ready()` в `useEffect`, установка CSS-переменных темы на `document.documentElement`, шапка (старт · дата · чип модели), четыре вкладки с ролями `tablist`/`tab` и `aria-selected`, стек шторок.
- Кнопка «назад» Telegram: при непустом стеке вешается обработчик, снимающий верхнюю шторку; при пустом — снимается (`telegram.onBack(null)`), чтобы Telegram закрыл приложение сам.
- Без Telegram (`initData()` пустая) — экран с текстом «Откройте приложение из Telegram» вместо вкладок.
- `Sheet.tsx`: заголовок, кнопка с доступным именем «Закрыть», содержимое, затемнение фона.
- `ErrorBox.tsx`: показывает `userMessage`; кнопка «Повторить» скрыта при статусе 401 и 403 — повторять там нечего.
- `styles.css`: раскладка, цвета через переменные Telegram с запасными значениями. Верстку и размеры взять из макета (`miniapp/prototype.html:1-489` — там весь CSS).

Экраны в этой задаче — заглушки вида `<p>Прогноз</p>`; их наполняют задачи 8–13.

- [ ] **Step 6: Прогон**

Run: `cd webapp && npm run test -- --run && npm run build`
Expected: всё зелёное

- [ ] **Step 7: Коммит**

```bash
git add webapp/src
git commit -m "feat(webapp): оболочка — шапка, вкладки, шторки, тема"
```

---

### Task 7: Палитра и два прибора

**Files:**
- Create: `webapp/src/charts/palette.ts`, `webapp/src/charts/HourStrip.tsx`, `webapp/src/charts/AirColumn.tsx`, `webapp/src/charts/charts.test.tsx`, `tests/test_palette_sync.py`

**Interfaces:**
- Produces: `GRADE`, `TERRAIN`, `BAND`, `TEMP`, `WIND`, `GUST` — цвета в формате `#rrggbb`; `colorOfCategory(category: string): string`.
- Produces: `<HourStrip hours={HourFact[]} window={[number, number] | null} />`, `<AirColumn facts={Facts} />`.

- [ ] **Step 1: Написать питоновский тест сверки палитры**

`tests/test_palette_sync.py`:

```python
"""Цвета приложения совпадают с цветами PNG из чата.

Палитра живёт в charts.py и копируется в TypeScript — иначе никак, языки
разные. Незаметное расхождение приводит к тому, что один и тот же день в чате
и в приложении раскрашен по-разному, и пилот не знает, какой картинке верить.
"""
import pathlib
import re

import charts

ROOT = pathlib.Path(__file__).resolve().parent.parent
PALETTE = ROOT / "webapp" / "src" / "charts" / "palette.ts"


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(rgb)


def _declared() -> dict[str, str]:
    """Все объявления вида `X: "#rrggbb"` и `export const X = "#rrggbb"`."""
    text = PALETTE.read_text(encoding="utf-8")
    return {m.group(1): m.group(2).lower()
            for m in re.finditer(r'(?:export const\s+)?(\w+)\s*[:=]\s*"(#[0-9a-fA-F]{6})"', text)}


def test_scalar_colors_match_charts():
    got = _declared()
    for name, rgb in [("TERRAIN", charts.TERRAIN), ("BAND", charts.BAND),
                      ("TEMP", charts.TEMP), ("WIND", charts.WIND), ("GUST", charts.GUST)]:
        assert got.get(name) == _hex(rgb), f"{name}: {got.get(name)} против {_hex(rgb)}"


def test_every_grade_colour_matches_charts():
    got = _declared()
    for category, rgb in charts.GRADE_RGB.items():
        assert got.get(category) == _hex(rgb), f"{category}: {got.get(category)} против {_hex(rgb)}"


def test_no_grade_is_missing_from_the_palette():
    """Новая категория в charts.py без цвета в приложении — молчаливо серый день."""
    got = _declared()
    assert set(charts.GRADE_RGB) <= set(got)
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `.venv/bin/python -m pytest tests/test_palette_sync.py -q`
Expected: FAIL — файла `palette.ts` нет

- [ ] **Step 3: Написать палитру**

`webapp/src/charts/palette.ts` — значения перевести из `charts.py` вручную и сверить прогоном теста. Формат объявлений должен совпадать с тем, что читает регулярное выражение теста: `export const TERRAIN = "#968e80"` и объект оценок вида `{ "хорошо": "#..." }` с ключами из `charts.GRADE_RGB`.

Дописать `colorOfCategory(category)` — возвращает цвет категории; для неизвестной категории бросает исключение, а не отдаёт серый по умолчанию: молчаливый серый скрывает рассинхронизацию, ради которой и написан тест.

- [ ] **Step 4: Убедиться, что тест сверки зелёный**

Run: `.venv/bin/python -m pytest tests/test_palette_sync.py -q`
Expected: PASS (3 теста)

- [ ] **Step 5: Написать тесты приборов**

`webapp/src/charts/charts.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react"
import { expect, test } from "vitest"
import { HourStrip } from "./HourStrip"
import { AirColumn } from "./AirColumn"
import facts from "../../test/fixtures/facts_1d.json"
import type { Facts } from "../api/types"

const F = facts as unknown as Facts

test("в полосе часов столбик на каждый светлый час", () => {
  const { container } = render(<HourStrip hours={F.hourly_daytime} window={F.assessment.fly_window} />)
  expect(container.querySelectorAll("[data-hour]")).toHaveLength(F.hourly_daytime.length)
})

test("часы вне лётного окна помечены", () => {
  const { container } = render(<HourStrip hours={F.hourly_daytime} window={[11, 16]} />)
  const inside = container.querySelectorAll('[data-in-window="true"]')
  expect(inside.length).toBeGreaterThan(0)
  expect(inside.length).toBeLessThan(F.hourly_daytime.length)
})

test("столб воздуха подписывает старт и потолок", () => {
  render(<AirColumn facts={F} />)
  expect(screen.getByText(/старт/i)).toBeInTheDocument()
  expect(screen.getByText(/потолок/i)).toBeInTheDocument()
})

test("без данных о потолке столб не выдумывает высоту", () => {
  const noCeiling = { ...F, thermal_ceiling_m_agl: null, thermal_ceiling_m_msl: null }
  render(<AirColumn facts={noCeiling} />)
  expect(screen.getByText(/потолок неизвестен/i)).toBeInTheDocument()
})
```

- [ ] **Step 6: Убедиться, что тесты падают, затем написать компоненты**

Run: `cd webapp && npm run test -- --run charts` → FAIL.

Требования:
- `HourStrip` — SVG: столбик на каждый элемент `hourly_daytime`, высота пропорциональна баллу часа, цвет из палитры по категории часа, атрибуты `data-hour` и `data-in-window`. Раскладку взять из макета (`renderDay`, `miniapp/prototype.html:739-942`).
- `AirColumn` — SVG: снизу вверх рельеф, старт (`site.elevation_m`), рабочий коридор, потолок (`thermal_ceiling_m_msl`), база облаков (`lcl_m_agl` плюс высота старта). При `thermal_ceiling_m_msl === null` подписать «потолок неизвестен» и не рисовать линию — модель может не отдавать `boundary_layer_height`.
- Отдельной строкой в подписи столба: потолок всегда считается по GFS (решение из макета, `miniapp/README.md:39-41`).

Run снова: PASS (4 теста).

- [ ] **Step 7: Коммит**

```bash
git add webapp/src/charts tests/test_palette_sync.py
git commit -m "feat(webapp): палитра из charts.py и два прибора дня"
```

---

### Task 8: Экран прогноза и метеограмма

**Files:**
- Create: `webapp/src/screens/Forecast.tsx`, `webapp/src/screens/Forecast.test.tsx`, `webapp/src/charts/Meteogram.tsx`, `webapp/src/sheets/MeteogramSheet.tsx`
- Modify: `webapp/src/App.tsx`

- [ ] **Step 1: Написать тесты экрана**

`webapp/src/screens/Forecast.test.tsx`: рендер экрана с замоканным `fetch`, отдающим `facts_1d.json`. Проверить:

```tsx
test("показывает вердикт дня и лётное окно", async () => { /* ждать текста assessment.label_ru */ })
test("пока грузится — показывает индикатор, а не пустоту", () => { /* Spinner в документе */ })
test("на 502 показывает ошибку и кнопку повтора", async () => { /* ErrorBox */ })
test("кнопка «Ветер по высотам» открывает шторку", async () => { /* заголовок шторки виден */ })
test("кнопка «Разбор от ИИ» открывает шторку", async () => { /* заголовок шторки виден */ })
```

Тела тестов писать по образцу `queries.test.tsx`: обёртка с `QueryClientProvider`, `vi.stubGlobal("fetch", ...)` с разбором пути запроса.

- [ ] **Step 2: Убедиться, что тесты падают, затем написать экран**

Раскладка — из макета `renderDay` (`miniapp/prototype.html:739-942`): шапка с вердиктом, полоса часов, столб воздуха, строка ограничения, оговорки (`caveats`), кнопки шторок. Метеограмма — `buildMeteogram` (строки 1705-1765), рисуется компонентом `Meteogram` на SVG: температура, ветер, порывы; цвета `TEMP`, `WIND`, `GUST` из палитры.

- [ ] **Step 3: Прогон и коммит**

```bash
cd webapp && npm run test -- --run && npm run build
git add webapp/src && git commit -m "feat(webapp): экран прогноза и метеограмма"
```

---

### Task 9: Шторки прогноза — ветер по высотам и разбор дня

**Files:**
- Create: `webapp/src/sheets/WindGridSheet.tsx`, `webapp/src/sheets/DayAnalysisSheet.tsx`, `webapp/src/sheets/sheets.test.tsx`

- [ ] **Step 1: Написать тесты**

Проверить на `wind_grid.json`:

```tsx
test("в сетке строка на каждый уровень и колонка на каждый час", async () => {})
test("уровень старта выделен", async () => { /* data-launch="true" */ })
test("разбор показывает текст от Gemini", async () => {})
test("разбор при 429 предлагает повторить, а не молчит", async () => {})
```

- [ ] **Step 2: Написать шторки**

`WindGridSheet` — таблица «высота × час»: строки из `levels` (сверху вниз по убыванию `alt_m_msl`), колонки из `hours`, в ячейке стрелка направления и скорость; уровень с `is_launch` помечен атрибутом `data-launch="true"` и подписью. Раскладка — `openWindGrid` (`miniapp/prototype.html:1487-1532`).

`DayAnalysisSheet` — вызывает `useAnalysis()` при открытии, показывает `Spinner`, затем текст. Текст приходит строкой без разметки; переносы строк сохранять (`white-space: pre-wrap`). Раскладка — `openDayAI` (строки 1533-1555).

- [ ] **Step 3: Прогон и коммит**

```bash
cd webapp && npm run test -- --run && npm run build
git add webapp/src && git commit -m "feat(webapp): шторки ветра по высотам и разбора дня"
```

---

### Task 10: Экран обзора и скан

**Files:**
- Create: `webapp/src/screens/Overview.tsx`, `webapp/src/screens/Overview.test.tsx`
- Modify: `webapp/src/App.tsx`

- [ ] **Step 1: Написать тесты**

На `forecast_3d.json` (ответ `GET /api/forecast` с диапазоном — это `engine.facts_overview`, а НЕ строки обзора) и `scan.json`:

```tsx
test("строка на каждый день диапазона", async () => {})
test("переключение диапазона меняет запрос", async () => { /* url содержит range=week */ })
test("в строке видна причина ограничения, а не описание погоды", async () => {})
test("нажатие на день открывает прогноз этого дня", async () => {})
test("режим «Все старты» показывает старты и их дни", async () => {})
test("старты без лётных дней перечислены отдельно", async () => { /* поле empty */ })
```

- [ ] **Step 2: Написать экран**

Раскладка — `renderOver` (`miniapp/prototype.html:943-1014`) и `renderScan` (строки 1015-1066). Диапазоны: `3d`, `week`, `2weeks`; отдельный режим «Все старты» дёргает `/api/scan`. Нажатие на день переключает на вкладку прогноза с выбранной датой.

- [ ] **Step 3: Прогон и коммит**

```bash
cd webapp && npm run test -- --run && npm run build
git add webapp/src && git commit -m "feat(webapp): экран обзора и скан по всем стартам"
```

---

### Task 11: Карта и тайлы через свой домен

**Files:**
- Create: `webapp/src/map/MapView.tsx`, `webapp/src/map/pins.ts`, `webapp/src/map/map.test.tsx`
- Modify: `Caddyfile`, `tests/test_deploy_config.py`

**Interfaces:**
- Produces: `<MapView points={LatLon[]} sites={Site[]} onTap={(p: LatLon) => void} onDragPoint={(i: number, p: LatLon) => void} />`, тип `LatLon = { lat: number; lon: number }`.

- [ ] **Step 1: Написать тест конфигурации Caddy**

Дописать в `tests/test_deploy_config.py`:

```python
def test_tiles_are_proxied_through_our_own_domain():
    """Клиент ходит за тайлами только к своему домену: прямые запросы к
    tile.openstreetmap.org показали бы чужому сервису адрес каждого пилота и
    район, куда он смотрит. Ради этого прокси и заводился."""
    text = _read("Caddyfile")
    assert "handle /tiles/*" in text
    assert "tile.openstreetmap.org" in text


def test_tile_proxy_names_the_application_in_user_agent():
    """Правила использования тайлов OpenStreetMap требуют, чтобы клиент себя
    называл. Безымянный поток запросов там блокируют."""
    text = _read("Caddyfile")
    assert "header_up User-Agent" in text
```

- [ ] **Step 2: Убедиться, что тесты падают, затем править Caddyfile**

Добавить блок **выше** `handle /api/*` не требуется — пути не пересекаются, но порядок с `handle` для статики важен: `/tiles/*` должен стоять до общего `handle`. Проверить настоящим бинарником:

```bash
docker run --rm -e PUBLIC_DOMAIN=example.com -v "$PWD/Caddyfile":/etc/caddy/Caddyfile:ro \
  caddy:2-alpine caddy adapt --config /etc/caddy/Caddyfile
```
Expected: код возврата 0, в выводе виден upstream `tile.openstreetmap.org`.

- [ ] **Step 3: Написать тесты карты**

Leaflet требует размеров контейнера, которых в jsdom нет, поэтому тесты проверяют не отрисовку, а поведение обёртки:

```tsx
test("тап по карте отдаёт координаты наверх", async () => {})
test("на карте столько маркеров, сколько точек", async () => {})
test("тайлы берутся у своего домена", () => { /* url шаблона начинается с /tiles/ */ })
```

- [ ] **Step 4: Написать компонент**

`MapView` — обёртка над Leaflet: карта создаётся в `useEffect`, слой тайлов `"/tiles/{z}/{x}/{y}.png"`, маркеры пересобираются при изменении `points`, обработчики `click` и `dragend` вызывают колбэки. Атрибуция OpenStreetMap обязательна — этого требуют условия использования данных.

- [ ] **Step 5: Прогон и коммит**

```bash
cd webapp && npm run test -- --run && npm run build && cd .. && .venv/bin/python -m pytest tests/test_deploy_config.py -q
git add webapp/src/map Caddyfile tests/test_deploy_config.py
git commit -m "feat(webapp): карта Leaflet и тайлы через свой домен"
```

---

### Task 12: Экран маршрута

**Files:**
- Create: `webapp/src/screens/Route.tsx`, `webapp/src/screens/Route.test.tsx`, `webapp/src/charts/RouteProfile.tsx`, `webapp/src/sheets/PointCardSheet.tsx`, `webapp/src/sheets/RouteAnalysisSheet.tsx`
- Modify: `webapp/src/App.tsx`

- [ ] **Step 1: Написать тесты**

На `route.json`:

```tsx
test("показывает вердикт маршрута и километраж", async () => {})
test("разрез рисует рельеф из terrain, а не из точек", async () => { /* число сегментов = terrain.km.length */ })
test("маршрут без terrain не роняет экран", async () => { /* terrain: null */ })
test("нажатие на точку открывает её карточку", async () => {})
test("перебор времени вылета шлёт новый запрос с departure", async () => {})
test("разбор маршрута показывает текст", async () => {})
```

- [ ] **Step 2: Написать экран**

Раскладка — `renderRoute` (`miniapp/prototype.html:1067-1194`), разрез — `buildSection` (строки 1195-1265), карточка точки — `openPointCard` (строки 1577-1631), разбор — `openRouteAI` (строки 1556-1576).

Важное про разрез: рельеф приходит отдельной сеткой со своим километражом (`terrain.km` и `terrain.elevations`), и рисовать его нужно по этим километрам, а не по индексам — шаг у разных плеч разный, и по индексам рельеф съедет относительно погоды. Причина записана в `forecast.py` рядом с формированием ответа.

- [ ] **Step 3: Прогон и коммит**

```bash
cd webapp && npm run test -- --run && npm run build
git add webapp/src && git commit -m "feat(webapp): экран маршрута, разрез и карточка точки"
```

---

### Task 13: Маршруты пилота и формы ввода

**Files:**
- Create: `webapp/src/sheets/SavedRoutesSheet.tsx`, `webapp/src/sheets/NewRouteSheet.tsx`, `webapp/src/sheets/SitePickerSheet.tsx`, `webapp/src/sheets/ModelPickerSheet.tsx`, `webapp/src/sheets/AddSiteSheet.tsx`, `webapp/src/screens/Settings.tsx`, `webapp/src/screens/Settings.test.tsx`, `webapp/src/sheets/forms.test.tsx`
- Modify: `webapp/src/App.tsx`

- [ ] **Step 1: Написать тесты форм**

```tsx
test("новый маршрут принимает точки, поставленные на карте", async () => {})
test("новый маршрут принимает список координат", async () => { /* /api/route/parse, поле text */ })
test("новый маршрут принимает файл GPX", async () => { /* FormData с полем file */ })
test("сохранение маршрута с пустым именем не уходит на сервер", async () => {})
test("добавление старта подтягивает высоту точки", async () => { /* /api/elevation */ })
test("добавление старта с именем длиннее допустимого показывает ошибку сервера", async () => {})
test("удаление старта спрашивает подтверждение", async () => {})
test("смена постоянной модели уходит в PATCH /api/prefs", async () => {})
test("разовая модель не пишется в настройки", async () => { /* PATCH не вызывается */ })
test("скорость по маршруту сохраняется", async () => {})
```

- [ ] **Step 2: Написать шторки и экран настроек**

Раскладки: `openSaved` (строки 1766-1780), `openNewRoute` (1781-1805), `openSiteSheet` (1632-1651), `openModelSheet` (1652-1694), `buildAddSite` (1837-1861), `openSiteEditor` (1806-1836), `renderSet` (1363-1468).

Правила, которые нельзя обойти на клиенте (сервер их проверяет, приложение должно объяснять заранее): имя старта и маршрута без символа `|` и не длиннее `store.NAME_MAX_BYTES` байт; координаты в пределах широты ±90 и долготы ±180; точек маршрута не меньше `route.MIN_POINTS` и не больше `route.MAX_POINTS`; файл не больше `route.MAX_GPX_BYTES`. Значения не дублировать в коде фронтенда произвольными числами — брать из ответа сервера при ошибке и показывать его текст.

Разовая модель против постоянной: чип в шапке меняет модель только для текущего экрана и в `PATCH /api/prefs` не уходит; постоянная меняется на экране настроек.

- [ ] **Step 3: Прогон и коммит**

```bash
cd webapp && npm run test -- --run && npm run build
git add webapp/src && git commit -m "feat(webapp): маршруты пилота, старты и настройки"
```

---

### Task 14: Сборка в образ и раскатка

**Files:**
- Modify: `Dockerfile`, `api.py`, `docker-compose.yml`, `Caddyfile`, `README.md`, `tests/test_deploy_config.py`, `tests/test_api_static.py`
- Delete: `static/index.html`

- [ ] **Step 1: Написать тесты раскладки**

Дописать в `tests/test_deploy_config.py`:

```python
def test_image_builds_the_webapp():
    """Собранное приложение попадает в образ отдельным этапом на Node. Без
    этого контейнер поднимется и будет отдавать 404 на корне — молча."""
    text = _read("Dockerfile")
    assert "node:22" in text
    assert "npm ci" in text
    assert "webapp/dist" in text


def test_compose_no_longer_mounts_static_into_caddy():
    """Статику отдаёт pgbot: смонтированный в caddy каталог был вторым путём к
    тому же месту и расходился бы с образом при первой же пересборке."""
    assert "/srv/www" not in _read("docker-compose.yml")


def test_caddy_sends_everything_but_tiles_to_pgbot():
    text = _read("Caddyfile")
    assert "file_server" not in text
    assert text.count("reverse_proxy pgbot:") >= 1
```

В `tests/test_api_static.py` заменить проверки заглушки на проверку каталога `webapp/dist`.

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_deploy_config.py tests/test_api_static.py -q`
Expected: FAIL

- [ ] **Step 3: Правки**

`Dockerfile` — первым этапом:

```dockerfile
FROM node:22-slim AS webapp
WORKDIR /build
COPY webapp/package.json webapp/package-lock.json ./
RUN npm ci
COPY webapp/ ./
RUN npm run build
```

В основном этапе после `COPY . .` добавить `COPY --from=webapp /build/dist ./webapp/dist`, а `chown -R app /app` оставить ниже, чтобы права распространились и на собранное.

`api.py` — `STATIC_DIR` указывает на `webapp/dist`.

`docker-compose.yml` — из томов `caddy` убрать `./static:/srv/www:ro`.

`Caddyfile` — `file_server` и `root` убрать; общий `handle` проксирует в `pgbot`. Блок `/tiles/*` остаётся.

Удалить `static/index.html` и пустой каталог `static/`.

`README.md` — раздел про Caddy: статику отдаёт pgbot, заглушки больше нет, появилась цель `make webapp-build`.

- [ ] **Step 4: Проверить конфигурацию настоящим Caddy и compose**

```bash
docker run --rm -e PUBLIC_DOMAIN=example.com -v "$PWD/Caddyfile":/etc/caddy/Caddyfile:ro \
  caddy:2-alpine caddy adapt --config /etc/caddy/Caddyfile
```
Expected: код возврата 0

- [ ] **Step 5: Прогон и коммит**

```bash
make test
git add -A && git commit -m "feat(deploy): приложение собирается в образ, статику отдаёт pgbot"
```

---

### Task 15: Сквозные сценарии Playwright

**Files:**
- Create: `webapp/playwright.config.ts`, `webapp/e2e/app.spec.ts`, `webapp/e2e/fixtures.ts`
- Modify: `webapp/package.json`, `Makefile`, `README.md`

- [ ] **Step 1: Настроить Playwright**

`webapp/playwright.config.ts`: браузер `chromium`, размер окна 452×900 (ширина, на которой снимался макет), `webServer` поднимает `vite preview` на собранном приложении, базовый адрес — он же. Запросы к `/api` проксируются на локальный `app.py`.

`webapp/e2e/fixtures.ts`: перед каждым сценарием в страницу подставляется поддельный объект `window.Telegram.WebApp` с настоящей подписью из переменной окружения `DEV_INIT_DATA` (её выпускает `scripts/dev_init_data.py`).

- [ ] **Step 2: Написать сценарии**

`webapp/e2e/app.spec.ts`:

```ts
test("приложение открывается и показывает вкладки", async ({ page }) => {})
test("прогноз загружается и показывает вердикт", async ({ page }) => {})
test("шторка ветра по высотам открывается и закрывается", async ({ page }) => {})
test("настройки открываются и показывают список моделей", async ({ page }) => {})
test("без подписи приложение просит открыть из Telegram", async ({ page }) => {})
```

- [ ] **Step 3: Добавить цель make**

```makefile
e2e:                ## run end-to-end tests (needs a running app.py and BOT_TOKEN)
	npm --prefix webapp run e2e
```

В `.PHONY` добавить `e2e`. В `webapp/package.json` — скрипт `"e2e": "playwright test"`.

Дописать в `README.md` раздел про запуск сквозных тестов: сначала `python scripts/dev_init_data.py --user-id <ваш id> --token "$BOT_TOKEN"`, полученную строку в `DEV_INIT_DATA`, затем `make e2e`.

- [ ] **Step 4: Прогон**

Run: `make e2e`
Expected: все сценарии зелёные

- [ ] **Step 5: Коммит**

```bash
git add webapp/playwright.config.ts webapp/e2e webapp/package.json Makefile README.md
git commit -m "test(webapp): сквозные сценарии Playwright"
```

---

## Порядок и зависимости

Задачи идут строго по номерам: каждая опирается на интерфейсы предыдущих. Задачи 8–13 (экраны) между собой независимы по коду, но все опираются на 1–7, а 12–13 ещё и на карту из задачи 11.

После каждой задачи приложение собирается и обе тестовые сюиты зелёные. Раскатка возможна начиная с задачи 14; до неё образ продолжает отдавать заглушку фазы 3.

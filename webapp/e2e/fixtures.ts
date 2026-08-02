// Обвязка сквозных сценариев: поддельный Telegram вокруг НАСТОЯЩЕЙ подписи и
// (для сценариев раскладки) подстановка ответов API.
//
// Подпись здесь не подделывается — она настоящая, просто выпущена локально
// (scripts/dev_init_data.py) тем же токеном, каким её проверяет сервер
// (webauth.verify — HMAC от "WebAppData", в Telegram он не ходит). Обхода
// проверки в приложении нет и не будет, поэтому единственная точка подмены —
// то же самое место, куда смотрит telegram.ts: window.Telegram.WebApp.
import { readFileSync } from "node:fs"
import { test as base, expect } from "@playwright/test"
import type { Page, Route } from "@playwright/test"

// Как открыто приложение:
//   "signed" — подставлен window.Telegram.WebApp с подписью из DEV_INIT_DATA;
//   "none"   — объекта Telegram нет вовсе, как в обычном браузере.
export type TelegramMode = "signed" | "none"

type Options = { telegram: TelegramMode }

function requireInitData(): string {
  const raw = process.env.DEV_INIT_DATA
  if (!raw) {
    // Пустая строка сюда доехать не должна: приложение считает пустую
    // initData признаком «открыто не из Telegram» и показывает заглушку —
    // сценарии молча проверяли бы её вместо самого приложения.
    throw new Error(
      "DEV_INIT_DATA не задана. Выпустите подпись тем же токеном, что у "
      + "запущенного app.py:\n"
      + '  export DEV_INIT_DATA="$(python scripts/dev_init_data.py '
      + '--user-id <ваш telegram id> --token "$BOT_TOKEN")"',
    )
  }
  return raw
}

// Настоящий SDK Telegram (webapp/index.html подключает его с telegram.org)
// в браузере сценария не нужен и мешает: он присваивает window.Telegram уже
// после addInitScript и молча затирает подставленный объект — приложение
// читало пустую initData и показывало заглушку «Не Telegram» вместо себя
// (воспроизведено на первом прогоне этих сценариев). Отдать что-то полезное
// вне клиента Telegram он всё равно не может: initData там пустая по
// определению, а это ровно то состояние, которое проверяет отдельный
// сценарий. Заодно прогон перестаёт зависеть от доступности telegram.org.
async function blockTelegramSdk(page: Page): Promise<void> {
  await page.route("**/telegram-web-app.js", (route) => route.abort())
}

// Ставится через addInitScript — то есть ДО скриптов страницы: приложение
// читает telegram.initData() на первом же рендере (App.tsx), и объект,
// созданный после загрузки, оно бы уже не увидело.
async function installTelegram(page: Page, initData: string): Promise<void> {
  await page.addInitScript((signature: string) => {
    // Набор полей — ровно тот, к которому обращается webapp/src/telegram.ts
    // (initData/colorScheme/themeParams/ready/expand/BackButton/
    // HapticFeedback). Ничего сверх этого не подделывается: лишнее поле
    // означало бы, что сценарий проверяет поведение, которого в приложении
    // нет. themeParams пустой намеренно — theme.ts обязан достроить цельную
    // палитру схемы сам, и сценарии идут по тому же пути, что и настоящий
    // клиент без присланной темы.
    window.Telegram = {
      WebApp: {
        initData: signature,
        colorScheme: "light",
        themeParams: {},
        ready: () => {},
        expand: () => {},
        BackButton: { show: () => {}, hide: () => {}, onClick: () => {}, offClick: () => {} },
        HapticFeedback: { impactOccurred: () => {}, notificationOccurred: () => {} },
      },
    }
  }, initData)
}

export const test = base.extend<Options>({
  telegram: ["signed", { option: true }],
  page: async ({ page, telegram }, use) => {
    await blockTelegramSdk(page)
    if (telegram === "signed") {
      await installTelegram(page, requireInitData())
    }
    await use(page)
    // Сценарий уходит, только когда страница договорила с сервером.
    //
    // Сервер разрешает пилоту один тяжёлый запрос одновременно и отвечает на
    // второй 429 (api.py:one_at_a_time), а приложение такой отказ не
    // повторяет намеренно (retry: false, api/queries.ts). Все сценарии
    // подписаны одним пилотом, и без этого ожидания следующий начинался
    // раньше, чем сервер отпускал слот предыдущего: экран «Обзора»
    // смонтирован всегда и уходит за своим прогнозом на 3 дня вторым, уже
    // после того, как сценарий увидел вердикт дня и закончился. Проверено —
    // сценарий про шторку ветра падал на «Уже считаю — дождись ответа»
    // вместо кнопки. Ожидание привязано к затихшей сети, а не к паузе:
    // договорила страница — идём дальше.
    //
    // Истечение потолка НЕ глушится. Проглоченное, оно неотличимо от успеха:
    // разборка молча сдаётся, слот на сервере остаётся занятым, и краснеет
    // следующий сценарий — чужим 429 «Уже считаю», то есть отладка
    // начинается с продукта вместо разборки. Проверено мутацией «потолок
    // 1 мс»: с проглоченным отказом сценарий зелёный, без него — красный с
    // текстом ниже.
    try {
      await page.waitForLoadState("networkidle", { timeout: 60_000 })
    } catch (cause) {
      throw new Error(
        "страница не договорила с сервером за 60 с: слот пилота на сервере "
        + "(api.py:one_at_a_time) остаётся занятым, и следующий сценарий "
        + "получит 429 вместо своих данных",
        { cause },
      )
    }
  },
})

export { expect }

// ──────────────────────────────────────────── ответы API для сценариев раскладки
//
// Раскладку меряют на ФИКСИРОВАННЫХ данных, а не на живом прогнозе, и это не
// экономия времени, а условие проверки: длина текста в чипе времени вылета
// определяет, вылезет он за рамку или нет, а живой ответ на разные дни даёт
// разный набор вариантов вылета — сценарий то ловил бы дефект, то нет.
// Фикстуры не выдуманы: их печатает scripts/dump_api_fixtures.py из тех же
// данных, на которых стоят тесты домена, поэтому форма ответа здесь не может
// молча разойтись с настоящим API.
function fixture<T>(name: string): T {
  return JSON.parse(readFileSync(new URL(`../test/fixtures/${name}`, import.meta.url), "utf8")) as T
}

type RouteFixture = { points: { lat: number; lon: number; km: number }[] }

// Прозрачный PNG 1×1 — вместо настоящих плиток карты. Сценариям важно, КУДА
// Leaflet их разложил (по ним видно, какую область карта считает своей), а не
// что на них нарисовано; поход же за настоящими плитками сделал бы прогон
// зависимым от чужого сервера и от прокси /tiles, к раскладке отношения не
// имеющих.
const PIXEL_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
)

async function json(route: Route, body: unknown): Promise<void> {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) })
}

export type ApiStub = {
  // Отпускает придержанный ответ POST /api/route. Нужен сценарию про карту:
  // маршрут обязан досчитаться, пока вкладка «Маршрут» скрыта, — иначе карта
  // создастся в контейнере с уже известным размером, и проверять будет нечего.
  releaseRoute: () => void
}

export async function stubApi(page: Page, opts: { holdRoute?: boolean } = {}): Promise<ApiStub> {
  const routeResult = fixture<RouteFixture>("route.json")
  // Сохранённый маршрут — те же точки, что вернёт расчёт: иначе шторка
  // «Сохранённые» отдавала бы одну геометрию, а карта показывала другую, и
  // сценарий описывал бы положение, которого в приложении не бывает.
  const savedRoutes = [{
    name: "Гудаури — юг",
    points: routeResult.points.map((p) => [p.lat, p.lon, null]),
    saved_at: "2026-08-01",
  }]

  let releaseRoute = (): void => {}
  const held = new Promise<void>((resolve) => { releaseRoute = resolve })

  await page.route("**/tiles/**", (route) => route.fulfill({ contentType: "image/png", body: PIXEL_PNG }))

  await page.route("**/api/**", async (route) => {
    const request = route.request()
    const { pathname, searchParams } = new URL(request.url())
    const key = `${request.method()} ${pathname}`

    if (key === "GET /api/prefs") return json(route, fixture("prefs.json"))
    if (key === "GET /api/sites") return json(route, fixture("sites.json"))
    if (key === "GET /api/routes") return json(route, savedRoutes)
    if (key === "GET /api/forecast") {
      // Форма ответа зависит от range (forecast.py:347-349, перегрузки
      // useForecast в api/queries.ts): Facts при "1d", ForecastOverview при
      // остальных. Экран «Обзор» смонтирован всегда, поэтому запрос на "3d"
      // уходит вместе с запросом «Прогноза» — отдать ему Facts значит уронить
      // весь экран на разборе days_daytime.
      const overview = searchParams.get("range") !== "1d"
      return json(route, fixture(overview ? "forecast_3d.json" : "facts_1d.json"))
    }
    if (key === "POST /api/route") {
      if (opts.holdRoute) await held
      return json(route, routeResult)
    }
    // Всё остальное — явный отказ, а не молчание: неотвеченный запрос завис
    // бы спиннером, и сценарий упал бы по потолку времени, ничего не объяснив.
    return route.fulfill({
      status: 501,
      contentType: "application/json",
      body: JSON.stringify({ detail: `сценарий не подставляет ответ на ${key}` }),
    })
  })

  return { releaseRoute }
}

// Экран «Настройки» и шторки, которые он открывает: выбор метеомодели,
// маршрутная скорость, поправка на ветер, список стартов с добавлением и
// удалением.
//
// Тесты идут через НАСТОЯЩИЙ путь пилота (нажать строку → открылась шторка →
// нажать в шторке), а не рендерят шторку в изоляции: ровно так задача 10
// поймала Critical «нажали второй старт, открылся первый» — привязка «что
// нажали» к «что поехало на сервер» живёт между компонентами, а не внутри
// одного.
//
// Модельные тесты рендерят всё приложение целиком: разовая и постоянная
// модель различаются не тем, что происходит в шторке, а тем, доезжает ли
// выбор до PATCH /api/prefs и до параметра model= в запросе прогноза.
//
// <StrictMode> — снаружи SheetsProvider и снаружи App: шторка, смонтированная
// вне строгого режима, не воспроизводит гонку подписки useMutation (разбор
// C2 задачи 12: обёртка держала StrictMode внутри провайдера, и все 12
// тестов были зелёными при живом дефекте).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import { StrictMode } from "react"
import type { ReactNode } from "react"
import { App, SheetsProvider } from "../App"
import { Settings } from "./Settings"
import type { Prefs, Site } from "../api/types"
import facts from "../../test/fixtures/facts_1d.json"
import overview from "../../test/fixtures/forecast_3d.json"
import prefsFixture from "../../test/fixtures/prefs.json"
import sitesFixture from "../../test/fixtures/sites.json"

const SITE = (sitesFixture as Site[])[0]!

// Три старта, порядок не алфавитный: на одном старте невозможно отличить
// «открыли карточку того, что нажали» от «всегда первый» (Critical задачи 10).
const THREE_SITES: Site[] = [
  { ...SITE, name: "Гудаури", lat: 42.47, lon: 44.48 },
  { ...SITE, name: "Лалискури", lat: 42.51, lon: 42.32, aspect: "ЮВ", aspect_deg: 135, elevation_m: 900 },
  { ...SITE, name: "Казбеги", lat: 42.66, lon: 44.64, aspect: "З", aspect_deg: 270, elevation_m: 1750 },
]

type Call = { url: string; method: string; body: BodyInit | null | undefined }

const calls: Call[] = []
let prefsState: Prefs

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } })
}

// Ответ может быть и промисом: тесту про «шторку открыли до ответа сервера»
// нужен запрос, который разрешается по команде, а не сразу.
function stubFetch(reply: (url: string, init?: RequestInit) => Response | Promise<Response>): void {
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), method: init?.method ?? "GET", body: init?.body })
    return Promise.resolve(reply(String(url), init))
  })
}

// Настройки — состояние, а не константа: PATCH обязан менять то, что потом
// вернёт GET, иначе тест не отличит «сохранилось» от «нарисовалось на месте».
function defaultReply(url: string, init?: RequestInit): Response {
  const path = url.split("?")[0]
  const method = init?.method ?? "GET"
  if (path === "/api/prefs" && method === "PATCH") {
    prefsState = { ...prefsState, ...(JSON.parse(String(init?.body)) as Partial<Prefs>) }
    return json(prefsState)
  }
  if (path === "/api/prefs") return json(prefsState)
  if (path === "/api/sites") return json(THREE_SITES)
  if (path === "/api/routes") return json([])
  if (path === "/api/forecast") return json(url.includes("range=1d") ? facts : overview)
  if (path === "/api/scan") return json({ sites: [], empty: [], failed: [] })
  return json({})
}

function callsTo(path: string, method?: string): Call[] {
  return calls.filter((c) => c.url.split("?")[0] === path && (method === undefined || c.method === method))
}

function body(call: Call): Record<string, unknown> {
  return JSON.parse(String(call.body)) as Record<string, unknown>
}

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return (
    <StrictMode>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </StrictMode>
  )
}

// Экран настроек в собственном дереве: шторки ему нужны настоящие (он их
// открывает), а оболочка приложения — нет.
function renderSettings(props: Partial<Parameters<typeof Settings>[0]> = {}) {
  return render(
    <SheetsProvider>
      <Settings
        currentSite="Гудаури"
        onceModel={null}
        onPickOnce={vi.fn()}
        onPickPermanent={vi.fn()}
        onOpenSiteForecast={vi.fn()}
        {...props}
      />
    </SheetsProvider>,
    { wrapper },
  )
}

beforeEach(() => {
  calls.length = 0
  prefsState = prefsFixture as Prefs
  const back = { show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() }
  window.Telegram = { WebApp: {
    initData: "auth_date=1&hash=abc", colorScheme: "light", themeParams: {},
    ready: vi.fn(), expand: vi.fn(), BackButton: back,
    HapticFeedback: { impactOccurred: vi.fn(), notificationOccurred: vi.fn() },
  } }
  stubFetch(defaultReply)
})

// ------------------------------------------------------------ старты

test("добавление старта подтягивает высоту точки", async () => {
  stubFetch((url, init) => {
    if (url === "/api/elevation") return json({ elevation_m: 1874 })
    if (url === "/api/sites" && init?.method === "POST") {
      return json({ ...SITE, name: "Лалискури", lat: 42.51, lon: 42.32, elevation_m: 1874 }, 201)
    }
    return defaultReply(url, init)
  })
  renderSettings()

  await userEvent.click(await screen.findByRole("button", { name: /Добавить старт/ }))
  const sheet = screen.getByRole("dialog")

  await userEvent.type(within(sheet).getByLabelText(/Название/), "Лалискури")
  await userEvent.type(within(sheet).getByLabelText(/Широта/), "42.51")
  await userEvent.type(within(sheet).getByLabelText(/Долгота/), "42.32")
  await userEvent.click(within(sheet).getByRole("button", { name: "Добавить старт" }))

  await waitFor(() => { expect(callsTo("/api/sites", "POST")).toHaveLength(1) })

  // Высоту приложение спрашивает у сервера (api.py:elevation →
  // forecast.fetch_elevation), а не выдумывает нулём: SiteIn.elevation_m
  // обязателен, и старт с нулевой высотой врал бы во всех расчётах.
  const elevation = callsTo("/api/elevation", "POST")
  expect(elevation).toHaveLength(1)
  expect(body(elevation[0]!)).toEqual({ lat: 42.51, lon: 42.32 })

  const created = body(callsTo("/api/sites", "POST")[0]!)
  expect(created.name).toBe("Лалискури")
  expect(created.lat).toBe(42.51)
  expect(created.lon).toBe(42.32)
  expect(created.elevation_m).toBe(1874)
})

test("добавление старта с именем длиннее допустимого показывает ошибку сервера", async () => {
  // Дословный текст store.name_error — единственное место, где предел имени
  // назван словами. Клиент его не повторяет и не проверяет длину сам.
  const serverText = "Слишком длинное имя — не влезет в кнопки Telegram. До ~20 символов, короче?"
  stubFetch((url, init) => {
    if (url === "/api/elevation") return json({ elevation_m: 1874 })
    if (url === "/api/sites" && init?.method === "POST") return json({ detail: serverText }, 400)
    return defaultReply(url, init)
  })
  renderSettings()

  await userEvent.click(await screen.findByRole("button", { name: /Добавить старт/ }))
  const sheet = screen.getByRole("dialog")

  await userEvent.type(within(sheet).getByLabelText(/Название/), "Северный склон над деревней Коби у поворота")
  await userEvent.type(within(sheet).getByLabelText(/Широта/), "42.51")
  await userEvent.type(within(sheet).getByLabelText(/Долгота/), "42.32")
  await userEvent.click(within(sheet).getByRole("button", { name: "Добавить старт" }))

  expect(await screen.findByText(serverText)).toBeInTheDocument()
  // Запрос ДОШЁЛ до сервера: приложение не отсекает длинное имя своей копией
  // предела (store.NAME_MAX_BYTES живёт только на сервере).
  expect(callsTo("/api/sites", "POST")).toHaveLength(1)
})

// Тот же довод, что и у пустого имени маршрута, плюс цена: отправка без
// имени сначала дёрнула бы ТЯЖЁЛЫЙ запрос высоты (api.py:elevation висит на
// one_at_a_time), и только потом сервер отказал бы по store.name_error.
test("старт без названия не уходит на сервер", async () => {
  renderSettings()

  await userEvent.click(await screen.findByRole("button", { name: /Добавить старт/ }))
  const sheet = screen.getByRole("dialog")
  await userEvent.type(within(sheet).getByLabelText(/Широта/), "42.51")
  await userEvent.type(within(sheet).getByLabelText(/Долгота/), "42.32")
  await userEvent.click(within(sheet).getByRole("button", { name: "Добавить старт" }))

  expect(callsTo("/api/elevation")).toHaveLength(0)
  expect(callsTo("/api/sites", "POST")).toHaveLength(0)
  expect(within(sheet).getByRole("alert")).toHaveTextContent(/название/i)
})

test("удаление старта спрашивает подтверждение", async () => {
  stubFetch((url, init) => {
    if (url.startsWith("/api/sites/") && init?.method === "DELETE") return new Response(null, { status: 204 })
    return defaultReply(url, init)
  })
  renderSettings()

  // Третий старт списка: подмена «всегда первый» на первом не видна.
  await userEvent.click(await screen.findByRole("button", { name: /Казбеги/ }))
  const sheet = screen.getByRole("dialog")
  await userEvent.click(within(sheet).getByRole("button", { name: /Удалить старт/ }))

  // Первое нажатие ничего не удаляет — библиотека стартов общая, промах
  // пальцем стоил бы старта у всех пилотов сразу.
  expect(callsTo("/api/sites/Казбеги".replace("Казбеги", encodeURIComponent("Казбеги")), "DELETE")).toHaveLength(0)
  expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(0)

  await userEvent.click(within(sheet).getByRole("button", { name: /Да, удалить/ }))

  await waitFor(() => { expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1) })
  const deleted = calls.filter((c) => c.method === "DELETE")[0]!
  expect(decodeURIComponent(deleted.url)).toBe("/api/sites/Казбеги")
})

// ------------------------------------------------------------ метеомодель

test("смена постоянной модели уходит в PATCH /api/prefs", async () => {
  render(<StrictMode><App /></StrictMode>)

  // Чип в шапке подписан текущей моделью (prefs.model_key = ecmwf).
  await userEvent.click(await screen.findByRole("button", { name: "ECMWF" }))
  const permanent = screen.getByRole("group", { name: /Постоянная/ })
  // Не первая модель в списке (auto) и не текущая (ECMWF).
  await userEvent.click(within(permanent).getByRole("button", { name: /ICON/ }))

  await waitFor(() => { expect(callsTo("/api/prefs", "PATCH")).toHaveLength(1) })
  expect(body(callsTo("/api/prefs", "PATCH")[0]!)).toEqual({ model_key: "icon" })

  // Постоянная модель — это и есть новая модель приложения: чип показывает
  // её без пометки «разово».
  expect(await screen.findByRole("button", { name: "ICON" })).toBeInTheDocument()
})

test("разовая модель не пишется в настройки", async () => {
  render(<StrictMode><App /></StrictMode>)

  await userEvent.click(await screen.findByRole("button", { name: "ECMWF" }))
  const once = screen.getByRole("group", { name: /Разово/ })
  await userEvent.click(within(once).getByRole("button", { name: /GFS/ }))

  // Разовый выбор живёт только в этом сеансе — в настройках пилота он не
  // остаётся (api.py:_model_for: разовая модель приходит параметром запроса,
  // постоянная лежит в store.prefs).
  expect(callsTo("/api/prefs", "PATCH")).toHaveLength(0)

  // И при этом он ДЕЙСТВУЕТ: прогноз пересчитывается по выбранной модели.
  await waitFor(() => {
    const models = callsTo("/api/forecast")
      .map((c) => new URL(c.url, "http://x").searchParams)
      .filter((p) => p.get("range") === "1d")
      .map((p) => p.get("model"))
    expect(models).toContain("gfs")
  })
  expect(screen.getByRole("button", { name: /GFS · разово/ })).toBeInTheDocument()
})

// Ревью задачи 13 (N2): шторка кладётся в стек ГОТОВЫМ элементом, и её пропы
// застывали на момент нажатия. Чип модели нажимается и пока настройки в пути
// (в нём крутится индикатор), и шторка, открытая в этот момент, оставалась с
// двумя пустыми списками навсегда — даже после прихода /api/prefs. Тест
// повторяет именно этот порядок: сначала открыть, потом ответить.
test("шторка модели, открытая до ответа настроек, показывает пришедшие модели", async () => {
  let deliverPrefs = (): void => { throw new Error("настройки не запрашивались") }
  const pending = new Promise<Response>((resolve) => {
    deliverPrefs = () => { resolve(json(prefsState)) }
  })
  stubFetch((url, init) => {
    const path = url.split("?")[0]
    const method = init?.method ?? "GET"
    return path === "/api/prefs" && method === "GET" ? pending : defaultReply(url, init)
  })

  render(<StrictMode><App /></StrictMode>)

  // Пока настроек нет, чип подписан индикатором загрузки — и всё равно
  // нажимается (в макете он кнопка всегда, prototype.html:423).
  await userEvent.click(await screen.findByRole("button", { name: "Загрузка" }))
  expect(screen.getByRole("dialog", { name: "Метеомодель" })).toBeInTheDocument()

  deliverPrefs()

  const permanent = await screen.findByRole("group", { name: /Постоянная/ })
  expect(within(permanent).getByRole("button", { name: /ICON/ })).toBeInTheDocument()
  const once = screen.getByRole("group", { name: /Разово/ })
  expect(within(once).getByRole("button", { name: /GFS/ })).toBeInTheDocument()
})

// ------------------------------------------------------------ маршрут

test("скорость по маршруту сохраняется", async () => {
  renderSettings()

  expect(await screen.findByText("25 км/ч")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Увеличить маршрутную скорость" }))

  await waitFor(() => { expect(callsTo("/api/prefs", "PATCH")).toHaveLength(1) })
  expect(body(callsTo("/api/prefs", "PATCH")[0]!)).toEqual({ avg_route_speed_kmh: 26 })
  expect(await screen.findByText("26 км/ч")).toBeInTheDocument()
})

// Ревью задачи 13 (N9): черновик скорости снимался только при отказе, поэтому
// после успеха он навсегда перекрывал настройки, пришедшие с сервера. Здесь
// сервер отвечает на PATCH ДРУГИМ числом, чем прислал клиент, — так выглядит
// и правка с другого устройства, и любое серверное решение о значении:
// на экране обязана оказаться правда из store, а не желание пилота.
test("после ответа сервера на экране его значение, а не черновик", async () => {
  stubFetch((url, init) => {
    const path = url.split("?")[0]
    if (path === "/api/prefs" && init?.method === "PATCH") {
      prefsState = { ...prefsState, avg_route_speed_kmh: 30 }
      return json(prefsState)
    }
    return defaultReply(url, init)
  })
  renderSettings()

  expect(await screen.findByText("25 км/ч")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Увеличить маршрутную скорость" }))

  expect(await screen.findByText("30 км/ч")).toBeInTheDocument()
})

// Ревью задачи 13 (N9), вторая половина: два нажатия подряд шлют два PATCH на
// один и тот же ключ, и порядок их обработки сервером ничем не задан — «+»,
// затем «−» может оставить в store 26, когда пилот остановился на 25. Пока
// первый запрос в пути, степпер заперт.
test("второй шаг скорости не уходит, пока первый в полёте", async () => {
  stubFetch((url, init) => {
    const path = url.split("?")[0]
    if (path === "/api/prefs" && init?.method === "PATCH") return new Promise<Response>(() => {})
    return defaultReply(url, init)
  })
  renderSettings()

  const plus = await screen.findByRole("button", { name: "Увеличить маршрутную скорость" })
  await userEvent.click(plus)
  await waitFor(() => { expect(plus).toBeDisabled() })
  await userEvent.click(screen.getByRole("button", { name: "Уменьшить маршрутную скорость" }))

  expect(callsTo("/api/prefs", "PATCH")).toHaveLength(1)
  expect(body(callsTo("/api/prefs", "PATCH")[0]!)).toEqual({ avg_route_speed_kmh: 26 })
})

// Тумблер поправки на ветер иначе не покрыт ничем: он меняет расчёт времени
// прилёта на всём маршруте (route.py: GS = V·cos(WCA) + попутная), а
// «нажимается, но не сохраняется» выглядит на экране точно так же, как
// рабочий.
test("поправка на ветер сохраняется", async () => {
  renderSettings()

  const toggle = await screen.findByRole("switch", { name: /Учитывать ветер/ })
  expect(toggle).toHaveAttribute("aria-checked", "true") // фикстура: включена
  await userEvent.click(toggle)

  await waitFor(() => { expect(callsTo("/api/prefs", "PATCH")).toHaveLength(1) })
  expect(body(callsTo("/api/prefs", "PATCH")[0]!)).toEqual({ wind_correction_enabled: false })
  await waitFor(() => {
    expect(screen.getByRole("switch", { name: /Учитывать ветер/ })).toHaveAttribute("aria-checked", "false")
  })
})

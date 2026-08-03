// Тела тестов — по образцу screens/Forecast.test.tsx: обёртка с
// QueryClientProvider (шторки здесь не нужны — экран не открывает ни одной,
// в отличие от Forecast, поэтому SheetsProvider не подключаем),
// vi.stubGlobal("fetch", ...) с разбором пути запроса. На экране обзора
// запросов два разных ("/api/forecast" — диапазон 3d/week/2weeks,
// "/api/scan" — режим «Все старты»), поэтому подделка ветвится по пути, а
// не отдаёт одну и ту же фикстуру на любой запрос.
//
// forecast_3d.json — настоящий ответ GET /api/forecast?range=3d|week|2weeks
// (engine.facts_overview, форма ForecastOverview). Это НЕ форма строк
// /api/scan (OverviewRow, живёт в scan.json/scan_mixed.json) — их легко
// перепутать (см. комментарий у OverviewRow в api/types.ts), поэтому здесь
// два явно разных фикстурных файла на два явно разных эндпоинта.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import type { ReactNode } from "react"
import { Overview } from "./Overview"
import { fmtDate } from "../format"
import overview from "../../test/fixtures/forecast_3d.json"
import scan from "../../test/fixtures/scan.json"
import scanMixed from "../../test/fixtures/scan_mixed.json"
import sites from "../../test/fixtures/sites.json"

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

function jsonResponse(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }))
}

// Пути ТЯЖЁЛЫХ запросов из записанных вызовов. Слот пилота на сервере занимают
// только они (api.py:one_at_a_time); /api/sites экран спрашивает и скрытым —
// он дешёвый, идёт по тому же ключу, что уже запросила оболочка, и нужен,
// чтобы отличить пустую библиотеку от несделанного выбора.
function heavy(fetchMock: { mock: { calls: unknown[][] } }): string[] {
  return fetchMock.mock.calls
    .map((c) => String(c[0]).split("?")[0])
    .filter((p) => p === "/api/forecast" || p === "/api/scan")
}

// Подделка, ветвящаяся по пути запроса — /api/forecast всегда отдаёт
// forecast_3d.json (диапазон в самом ответе бэкенд не меняет, см. комментарий
// в Overview.tsx о том, что "date" диапазонному /api/forecast безразличен),
// /api/scan отдаёт переданный scanBody, /api/sites — список стартов: режим
// «Все старты» читает его сам, чтобы не спрашивать сервер про пустую
// библиотеку (Overview.tsx: ScanView).
function stubByPath(scanBody: unknown = scan) {
  vi.stubGlobal("fetch", (url: string) => {
    const path = url.split("?")[0]
    if (path === "/api/scan") return jsonResponse(scanBody)
    if (path === "/api/sites") return jsonResponse(sites)
    return jsonResponse(overview)
  })
}

// Период больше не предвыбран (бриф explicit-site-and-day): экран открывается
// без единого нажатого сегмента и до выбора в сеть не ходит. Тестам, которым
// нужен список дней, приходится выбрать период самим — ровно как пилоту.
async function pickRange(label = "3 дня"): Promise<void> {
  await userEvent.click(screen.getByRole("button", { name: label }))
}

beforeEach(() => {
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: { initData: "auth_date=1&hash=abc" } }
})

test("строка на каждый день диапазона", async () => {
  stubByPath()
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await pickRange()
  const list = await screen.findByRole("group", { name: "Дни диапазона" })
  expect(within(list).getAllByRole("button")).toHaveLength(overview.days_daytime.length)
  for (const day of overview.days_daytime) {
    expect(within(list).getByText(fmtDate(day.date))).toBeInTheDocument()
  }
})

test("переключение диапазона меняет запрос", async () => {
  const fetchMock = vi.fn((url: string) => {
    const path = url.split("?")[0]
    return jsonResponse(path === "/api/scan" ? scan : overview)
  })
  vi.stubGlobal("fetch", fetchMock)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await pickRange()
  await screen.findByRole("group", { name: "Дни диапазона" })

  await userEvent.click(screen.getByRole("button", { name: "Неделя" }))

  await waitFor(() => {
    const calls = fetchMock.mock.calls.map(([u]) => String(u))
    expect(calls.some((u) => u.includes("range=week"))).toBe(true)
  })
})

test("в строке видна причина ограничения, а не описание погоды", async () => {
  stubByPath()
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await pickRange()
  const list = await screen.findByRole("group", { name: "Дни диапазона" })

  const day = overview.days_daytime[0]!
  expect(day.assessment.limiting_factor_ru).not.toBeNull()
  expect(within(list).getAllByText(new RegExp(day.assessment.limiting_factor_ru!))).not.toHaveLength(0)
  // "ясно" (day.weather) не показывается в строке дня — вытеснено причиной
  // ограничения. В лучший день (лид-панель) погода показывается — там своя,
  // отдельная от списка строка, поэтому проверка сужена именно до списка.
  expect(within(list).queryByText(new RegExp(day.weather))).not.toBeInTheDocument()
})

test("нажатие на день открывает прогноз этого дня", async () => {
  stubByPath()
  const onOpenDay = vi.fn()
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={onOpenDay} />, { wrapper })
  await pickRange()
  const list = await screen.findByRole("group", { name: "Дни диапазона" })

  const target = overview.days_daytime[2]!
  await userEvent.click(within(list).getByRole("button", { name: new RegExp(fmtDate(target.date)) }))

  // onOpenDay несёт и старт (текущий, тот же, что передан в проп site), и
  // дату — не только дату (см. ниже критичный тест про «Все старты» с двумя
  // стартами: там колбэк обязан нести старт КОНКРЕТНОЙ строки, а не проп).
  expect(onOpenDay).toHaveBeenCalledWith("Гудаури", target.date)
})

// Ревью (Critical, воспроизведено на App.test.tsx): день, нажатый внутри
// группы конкретного старта в скане, обязан открывать прогноз ЭТОГО старта,
// а не старта, переданного в проп `site` (тот отражает старт диапазонных
// сегментов 3d/week/2weeks, а не старт под курсором в «Все старты»). До
// исправления Overview.tsx звал onOpenDay(row.date) без имени старта вовсе —
// вызывающий код (App.tsx) не мог узнать, чей день нажали, и подставлял
// прежний текущий старт.
test("нажатие на день скана несёт старт ЭТОЙ строки, а не переданный в проп site", async () => {
  const secondSiteDate = "2026-08-05"
  const scanTwoSites = {
    sites: [
      scan.sites[0]!,
      { name: "Казбеги", aspect_deg: scan.sites[0]!.aspect_deg, days: [{ ...scan.sites[0]!.days[0]!, date: secondSiteDate }] },
    ],
    empty: [],
    failed: [],
  }
  stubByPath(scanTwoSites)
  const onOpenDay = vi.fn()
  // site="Гудаури" — тот же приём, что и в остальных тестах файла, но здесь
  // важно, что он ДРУГОЙ, чем старт второй группы (Казбеги): если бы
  // компонент молча подставлял проп site вместо s.name, тест поймал бы это
  // явно, а не совпадением значений.
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={onOpenDay} />, { wrapper })
  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))

  const kazbegiGroup = await screen.findByRole("group", { name: "Казбеги" })
  await userEvent.click(within(kazbegiGroup).getByRole("button"))

  expect(onOpenDay).toHaveBeenCalledWith("Казбеги", secondSiteDate)
})

test("режим «Все старты» показывает старты и их дни", async () => {
  stubByPath()
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))

  const site = scan.sites[0]!
  expect(await screen.findByText(site.name)).toBeInTheDocument()
  const group = screen.getByRole("group", { name: site.name })
  expect(within(group).getAllByRole("button")).toHaveLength(site.days.length)
})

// Финальное ревью ветки, C1б: Scan.sites[].aspect_deg — ГРАДУСЫ
// (forecast.py:91 кладёт site["aspect_deg"]), и печать значения как есть
// давала шапку группы «180 · 7 лётных». В чате тот же скан печатает
// «🪂 Гудаури (Ю)» (bot.py:244). Фикстура снята с настоящего forecast.scan_week
// (scripts/dump_api_fixtures.py), поэтому в ней стоит именно число.
test("в шапке группы стоит румб, а не градусы", async () => {
  stubByPath()
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))

  const site = scan.sites[0]!
  expect(site.aspect_deg).toBe(180)
  expect(await screen.findByText(`Ю · ${site.days.length} лётных`)).toBeInTheDocument()
})

test("старты без лётных дней перечислены отдельно", async () => {
  stubByPath(scanMixed)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))

  expect(await screen.findByText(new RegExp(scanMixed.empty[0]!))).toBeInTheDocument()
  expect(screen.getByText(new RegExp(scanMixed.failed[0]!))).toBeInTheDocument()
})

// ─────────────────────────────── явный выбор периода (бриф explicit-site-and-day)
//
// Экран открывался на «3 дня» и сразу считал прогноз старта, о котором пилот
// не просил, а в одном ряду с периодами лежали «Все старты» — не период, а
// другой вопрос: ЧТО смотрим. Домен это подтверждает: GET /api/scan
// (forecast.scan_week) диапазона не принимает вовсе и считает только неделю.

test("на обзоре изначально не нажат ни один период", async () => {
  stubByPath()
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })

  const periods = screen.getByRole("group", { name: "Диапазон обзора" })
  const buttons = within(periods).getAllByRole("button")
  expect(buttons).not.toHaveLength(0)
  for (const button of buttons) {
    expect(button).toHaveAttribute("aria-pressed", "false")
  }
  // И «Все старты» не нажат тоже — иначе «ничего не предвыбрано» держалось бы
  // только на половине экрана.
  expect(screen.getByRole("button", { name: "Все старты" })).toHaveAttribute("aria-pressed", "false")
})

test("«Все старты» не лежит среди периодов", () => {
  stubByPath()
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })

  const periods = screen.getByRole("group", { name: "Диапазон обзора" })
  expect(within(periods).getAllByRole("button").map((b) => b.textContent)).toEqual(["3 дня", "Неделя", "2 недели"])
  // Сам переключатель на экране есть, просто отдельно — иначе проверка выше
  // прошла бы и на экране, где «Все старты» потеряли вовсе.
  expect(screen.getByRole("button", { name: "Все старты" })).toBeInTheDocument()
})

test("«Все старты» считает скан и не требует периода", async () => {
  const fetchMock = vi.fn((url: string) => {
    const path = String(url).split("?")[0]
    if (path === "/api/scan") return jsonResponse(scan)
    if (path === "/api/sites") return jsonResponse(sites)
    return jsonResponse(overview)
  })
  vi.stubGlobal("fetch", fetchMock)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })

  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))

  const site = scan.sites[0]!
  const group = await screen.findByRole("group", { name: site.name })
  expect(within(group).getAllByRole("button")).toHaveLength(site.days.length)
  // Периода не спросили и спросить негде: селектор уступил место строке про
  // единственный срок, который у скана есть.
  expect(screen.queryByRole("group", { name: "Диапазон обзора" })).toBeNull()
  expect(screen.getByText("по всем стартам — на неделю вперёд")).toBeInTheDocument()
  // Диапазонный прогноз при этом не считался: скан — это другой запрос.
  expect(fetchMock.mock.calls.filter(([u]) => String(u).startsWith("/api/forecast"))).toHaveLength(0)
})

test("без выбранного периода обзор не шлёт запрос", async () => {
  const fetchMock = vi.fn((_url: string) => jsonResponse(overview))
  vi.stubGlobal("fetch", fetchMock)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await new Promise((resolve) => { setTimeout(resolve, 20) })

  expect(heavy(fetchMock)).toHaveLength(0)
  expect(screen.getByText("Выберите период")).toBeInTheDocument()

  // Тот же экран с выбранным периодом запрос шлёт — без этой половины тест был
  // бы зелёным и на экране, не работающем вовсе.
  await pickRange()
  await waitFor(() => {
    expect(fetchMock.mock.calls.filter(([u]) => String(u).startsWith("/api/forecast"))).toHaveLength(1)
  })
})

// Тесты сверх шести из брифа.

test("пока грузится — показывает индикатор, а не пустоту", async () => {
  vi.stubGlobal("fetch", (_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("отменено", "AbortError")))
  }))
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await pickRange()
  expect(screen.getByRole("status", { name: "Загрузка" })).toBeInTheDocument()
})

test("на 502 показывает ошибку и кнопку повтора", async () => {
  vi.stubGlobal("fetch", () => jsonResponse({ detail: "" }, 502))
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await pickRange()
  expect(await screen.findByText(/open-meteo сейчас недоступна/)).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument()
})

test("скан на ошибку тоже показывает кнопку повтора", async () => {
  vi.stubGlobal("fetch", (url: string) => {
    const path = url.split("?")[0]
    if (path === "/api/scan") return jsonResponse({ detail: "" }, 502)
    // Список стартов — настоящим списком: режим «Все старты» читает его сам и
    // без непустой библиотеки скан не запросит вовсе (Overview.tsx: ScanView).
    if (path === "/api/sites") return jsonResponse(sites)
    return jsonResponse(overview)
  })
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))
  expect(await screen.findByText(/open-meteo сейчас недоступна/)).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument()
})

// Старт не выбран (в шапке приложения) — понятный текст вместо вечной
// загрузки, тот же приём, что и в Forecast.tsx (useForecast не запускает
// запрос, пока site === null). Проверяется на ВЫБРАННОМ периоде: иначе экран
// сказал бы то же самое про недостающий период, и текст про старт остался бы
// непроверенным.
test("без выбранного старта — понятный текст, а не вечная загрузка", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(overview))
  render(<Overview site={null} model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await pickRange()
  expect(screen.getByText("Выберите старт")).toBeInTheDocument()
})

// Финальное ревью ветки, I2. Правило «лётный день» живёт в criteria.FLYABLE
// и приезжает готовым ответом (assessment.flyable, engine.assessment_facts).
// Копия правила в экране («не лётно» только у no_fly и danger) расходилась с
// доменом на категории marginal: старт со всеми маргинальными днями был
// подписан «лётно» в каждой строке «Недели» и одновременно лежал в «Без
// лётных дней» на вкладке «Все старты».
//
// Подделывается ровно то, что отличает копию от домена: категория остаётся
// «хорошей», а flyable — false. Проверка на самой фикстуре (excellent +
// flyable: true) прошла бы и со старым правилом.
test("«лётно» под баллом — по ответу сервера, а не по собственному разбору категории", async () => {
  const marginalFirstDay = {
    ...overview,
    days_daytime: overview.days_daytime.map((day, i) => (
      i === 0 ? { ...day, assessment: { ...day.assessment, flyable: false } } : day
    )),
  }
  vi.stubGlobal("fetch", () => jsonResponse(marginalFirstDay))
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await pickRange()
  const list = await screen.findByRole("group", { name: "Дни диапазона" })

  const rows = within(list).getAllByRole("button")
  expect(within(rows[0]!).getByText("не лётно")).toBeInTheDocument()
  expect(within(rows[1]!).getByText("лётно")).toBeInTheDocument()
})

// Финальное ревью ветки, I6. Две половины экрана описывали один и тот же день
// по разным правилам: в «Все старты» запасным текстом стояла row.label —
// название категории, которое строка и так несёт баллом и его цветом, — а
// погоды не было вовсе, хотя чат на этом же месте её печатает (bot.py:252).
// Запасной текст виден только у дня, которому нечего ограничивать
// (criteria: «если всё на максимуме, лимит-фактора нет»), а в фикстуре
// лимит-фактор есть у каждого дня — поэтому он снимается точечно.
test("в строке «Все старты» стоит погода, а не второй раз категория", async () => {
  const noLimit = {
    ...scan,
    sites: scan.sites.map((s) => ({
      ...s,
      days: s.days.map((d, i) => (i === 0 ? { ...d, limiting: null } : d)),
    })),
  }
  stubByPath(noLimit)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))

  const row = noLimit.sites[0]!.days[0]!
  const group = await screen.findByRole("group", { name: noLimit.sites[0]!.name })
  const first = within(group).getAllByRole("button")[0]!
  expect(first).toHaveTextContent(row.weather)
  // Название категории в строке не повторяется: её место занимает то, чего в
  // строке не было, — погода.
  expect(first).not.toHaveTextContent(row.label)
})

// Вторая половина I6: осадки. Порог — criteria.RAIN_DAY_MM (webapp/src/domain.ts
// под сверкой tests/test_webapp_sync.py), тот же, по которому дождь печатает
// чат. В фикстуре осадков нет (ясная неделя), поэтому день с дождём
// подставляется точечно — иначе проверять было бы нечего.
test("в строке «Все старты» виден дождь", async () => {
  const rainy = {
    ...scan,
    sites: scan.sites.map((s) => ({
      ...s,
      days: s.days.map((d, i) => (i === 0 ? { ...d, precip: 2.4 } : { ...d, precip: 0.1 })),
    })),
  }
  stubByPath(rainy)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))

  const group = await screen.findByRole("group", { name: rainy.sites[0]!.name })
  const rows = within(group).getAllByRole("button")
  expect(rows[0]!).toHaveTextContent("2,4 мм")
  // 0,1 мм — ниже порога: это роса, а не дождь, и чат о ней тоже молчит.
  expect(rows[1]!).not.toHaveTextContent("мм")
})

// Финальное ревью ветки, Minor 6. На свежей установке вкладка «Все старты»
// показывала СОВЕРШЕННО пустой экран — только переключатель сегментов, — при
// том что соседние сегменты в том же состоянии объясняют, что делать. Заодно
// в сеть уходил самый дорогой запрос приложения про пустую библиотеку.
//
// «Пусто» здесь — ответ /api/sites, а не пустой проп site: с явным выбором
// «старт не выбран» и «стартов нет» разошлись, а скану выбранный старт не
// нужен вовсе (forecast.scan_week ходит по ВСЕЙ библиотеке). Поэтому старт в
// пропе есть, а библиотека пуста — состояние, которого раньше не бывало.
test("без стартов «Все старты» объясняет это и не спрашивает сервер", async () => {
  const fetchMock = vi.fn((url: string) => (
    String(url).split("?")[0] === "/api/sites" ? jsonResponse([]) : jsonResponse(overview)
  ))
  vi.stubGlobal("fetch", fetchMock)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))

  expect(await screen.findByText("Нет стартов")).toBeInTheDocument()
  expect(fetchMock.mock.calls.filter(([u]) => String(u).startsWith("/api/scan"))).toHaveLength(0)
})

// Вторая половина того же экрана на той же пустой библиотеке. Она предлагала
// «Выберите старт. Старт выбирается кнопкой в шапке» — там, где выбирать
// нечего, — пока соседняя половина честно говорила «Нет стартов»: один экран
// давал два разных ответа на один вопрос через одно нажатие (ревью ветки
// explicit-site-and-day, M1).
test("без стартов диапазонная половина обзора тоже говорит «Нет стартов»", async () => {
  vi.stubGlobal("fetch", (url: string) => (
    String(url).split("?")[0] === "/api/sites" ? jsonResponse([]) : jsonResponse(overview)
  ))
  render(<Overview site={null} model="ecmwf" onOpenDay={() => {}} />, { wrapper })

  expect(await screen.findByText("Нет стартов")).toBeInTheDocument()
  expect(screen.queryByText("Выберите старт и период")).toBeNull()
  expect(screen.queryByText(/Старт выбирается кнопкой в шапке/)).toBeNull()
})

// Финальное ревью ветки, I3. Экран смонтирован всегда (все четыре живут в
// дереве разом, App.tsx), и скрытым он занимал единственный слот пилота на
// сервере раньше того экрана, на который пилот смотрит.
test("скрытый экран в сеть не ходит, а показанный — ходит", async () => {
  const fetchMock = vi.fn((url: string) => {
    const path = String(url).split("?")[0]
    return jsonResponse(path === "/api/scan" ? scan : overview)
  })
  vi.stubGlobal("fetch", fetchMock)
  const { rerender } = render(
    <Overview site="Гудаури" model="ecmwf" active={false} onOpenDay={() => {}} />, { wrapper },
  )
  await pickRange()
  await new Promise((resolve) => { setTimeout(resolve, 20) })
  // Считаются ТЯЖЁЛЫЕ запросы: слот пилота на сервере занимают они
  // (api.py:one_at_a_time). Список стартов экран спрашивает и скрытым — он
  // дешёвый, идёт по тому же ключу, что уже запросила оболочка, и нужен, чтобы
  // отличить пустую библиотеку от несделанного выбора.
  expect(heavy(fetchMock)).toHaveLength(0)

  rerender(<Overview site="Гудаури" model="ecmwf" active onOpenDay={() => {}} />)
  await screen.findByRole("group", { name: "Дни диапазона" })
  expect(heavy(fetchMock)).toEqual(["/api/forecast"])
})

// Тот же сторож, но на пути «Все старты» — он ведёт к САМОМУ дорогому запросу
// приложения (forecast.scan_week идёт за погодой по всей библиотеке), а
// проверялся только диапазонный путь: снятие `active` у useScan оставляло весь
// пакет зелёным (ревью ветки explicit-site-and-day, I2). Список стартов
// приходит и на скрытой вкладке — он дешёвый и нужен самой шапке; считается
// только скан.
test("скрытый экран не запускает скан по всем стартам", async () => {
  const fetchMock = vi.fn((url: string) => {
    const path = String(url).split("?")[0]
    return jsonResponse(path === "/api/scan" ? scan : path === "/api/sites" ? sites : overview)
  })
  vi.stubGlobal("fetch", fetchMock)
  const { rerender } = render(
    <Overview site="Гудаури" model="ecmwf" active={false} onOpenDay={() => {}} />, { wrapper },
  )
  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))
  await new Promise((resolve) => { setTimeout(resolve, 20) })
  const scans = (): string[] => fetchMock.mock.calls
    .map(([u]) => String(u).split("?")[0]).filter((p) => p === "/api/scan")
  expect(scans()).toHaveLength(0)

  rerender(<Overview site="Гудаури" model="ecmwf" active onOpenDay={() => {}} />)
  await waitFor(() => { expect(scans()).toHaveLength(1) })
})

// scan_mixed.json несёт непустые sites[].days ВМЕСТЕ с непустыми empty/failed
// (см. комментарий в scripts/dump_api_fixtures.py про never[]) — старт с
// лётными днями и старты без них показаны одновременно, каждый в своём месте.
test("скан со стартами и без лётных дней одновременно не теряет ни одного старта", async () => {
  stubByPath(scanMixed)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))

  const site = scanMixed.sites[0]!
  const group = await screen.findByRole("group", { name: site.name })
  expect(within(group).getAllByRole("button")).toHaveLength(site.days.length)
  expect(screen.getByText(new RegExp(scanMixed.empty[0]!))).toBeInTheDocument()
  expect(screen.getByText(new RegExp(scanMixed.failed[0]!))).toBeInTheDocument()
})

// Пропавшая сеть — сценарий пилота, а не выдумка теста: он смотрит прогноз,
// теряет связь и переключается на «Обзор». Отказавший fetch отклоняется
// TypeError-ом, а не ApiError (client.ts строит ApiError только по ответу
// сервера), и TanStack отдаёт его экрану как есть — то есть в ErrorBox
// доезжает объект без userMessage. Пилот видел «Не получилось», сразу
// «Повторить», а между ними пусто (финальное ревью ветки, круг 2, I4).
// Проверяется на экране, а не только на ErrorBox: типы хуков обещают ApiError,
// и именно это обещание расходилось с тем, что до экрана доезжает.
test("пропавшая сеть объясняется словами, а не пустой рамкой", async () => {
  vi.stubGlobal("fetch", () => Promise.reject(new TypeError("Failed to fetch")))
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await pickRange()

  expect(await screen.findByText(/Нет связи/)).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument()
})

// ──────────────────────────────── повтор запроса по упавшему старту
//
// Старт попадает в Scan.failed, когда его недельный запрос упал
// (forecast.py:92-96). Экран перечислял такие старты одной строкой через
// запятую и отправлял пилота открывать каждый вручную на другом экране — то
// есть называл отказ и тут же уходил от него. Теперь у каждого упавшего старта
// своя кнопка, и тап повторяет ЕГО запрос.
//
// Повтора всего скана при этом нет: forecast.scan_week берёт недельные данные
// каждого старта по ключу кэша (name, "week", None, model) — forecast.py:86, —
// по тому же ключу, что и GET /api/forecast?site=X&range=week. Одиночный
// запрос по упавшему старту и есть повтор того самого запроса, который скан не
// смог сделать, а не какой-то другой; спрашивать после него ещё и /api/scan
// целиком значит занять единственный тяжёлый слот пилота (api.py:one_at_a_time)
// обходом всей библиотеки ради уже полученного ответа.

// Скан, в котором лётных дней не нашлось ни у кого, а перечисленные старты
// упали. sites/empty пустые намеренно: тесты ниже проверяют именно блок failed,
// и лишние группы в разметке только мешали бы адресовать нужную.
function scanWithFailed(failed: string[]): { sites: never[]; empty: never[]; failed: string[] } {
  return { sites: [], empty: [], failed }
}

// Пути тяжёлых запросов из записанных вызовов — по одному пути.
function callsTo(fetchMock: { mock: { calls: unknown[][] } }, path: string): string[] {
  return fetchMock.mock.calls.map((c) => String(c[0])).filter((u) => u.split("?")[0] === path)
}

// Подделка со своим ответом на /api/forecast: повтор упавшего старта ходит
// именно туда, и тестам ниже нужно менять ЭТОТ ответ (нелётные дни, отказ), не
// трогая ответ скана.
function stubScanAndForecast(scanBody: unknown, forecastBody: unknown, forecastStatus = 200) {
  const fetchMock = vi.fn((url: string) => {
    const path = String(url).split("?")[0]
    if (path === "/api/scan") return jsonResponse(scanBody)
    if (path === "/api/sites") return jsonResponse(sites)
    return jsonResponse(forecastBody, forecastStatus)
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

async function openAllSites(): Promise<void> {
  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))
}

// Имя упавшего старта отличается и от старта в пропе `site`, и от старта в
// самой фикстуре ответа (forecast_3d.json — «Гудаури»): группа перезапрошенного
// старта обязана называться тем стартом, который пилот перезапросил, а не тем,
// что подвернулся рядом.
const FAILED_SITE = "Казбеги"
const OTHER_FAILED_SITE = "Местиа"

test("каждый упавший старт — своя кнопка повтора", async () => {
  stubScanAndForecast(scanWithFailed([FAILED_SITE, OTHER_FAILED_SITE]), overview)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await openAllSites()

  expect(await screen.findByText("Не удалось получить")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: new RegExp(`${FAILED_SITE}.*Повторить`) })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: new RegExp(`${OTHER_FAILED_SITE}.*Повторить`) })).toBeInTheDocument()
})

test("тап по упавшему старту повторяет запрос ИМЕННО этого старта", async () => {
  const fetchMock = stubScanAndForecast(scanWithFailed([FAILED_SITE, OTHER_FAILED_SITE]), overview)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await openAllSites()

  await userEvent.click(await screen.findByRole("button", { name: new RegExp(FAILED_SITE) }))

  await waitFor(() => { expect(callsTo(fetchMock, "/api/forecast")).toHaveLength(1) })
  const asked = new URL(callsTo(fetchMock, "/api/forecast")[0]!, "http://localhost")
  expect(asked.searchParams.get("site")).toBe(FAILED_SITE)
  // Недельный запрос — тот самый, по чьему ключу кэша скан и не смог получить
  // данные (forecast.py:86). Другой диапазон грел бы другую запись.
  expect(asked.searchParams.get("range")).toBe("week")
  // Соседний упавший старт не спрашивали: у каждого свой повтор.
  expect(asked.searchParams.get("site")).not.toBe(OTHER_FAILED_SITE)
})

test("повтор упавшего старта не перезапрашивает скан целиком", async () => {
  const fetchMock = stubScanAndForecast(scanWithFailed([FAILED_SITE]), overview)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await openAllSites()
  await screen.findByRole("button", { name: new RegExp(FAILED_SITE) })
  const scansBefore = callsTo(fetchMock, "/api/scan").length

  await userEvent.click(screen.getByRole("button", { name: new RegExp(FAILED_SITE) }))
  await screen.findByRole("group", { name: FAILED_SITE })

  expect(callsTo(fetchMock, "/api/scan")).toHaveLength(scansBefore)
})

test("успешный повтор показывает лётные дни этого старта", async () => {
  stubScanAndForecast(scanWithFailed([FAILED_SITE]), overview)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await openAllSites()
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(FAILED_SITE) }))

  const group = await screen.findByRole("group", { name: FAILED_SITE })
  expect(within(group).getAllByRole("button")).toHaveLength(overview.days_daytime.length)
  expect(within(group).getByText(fmtDate(overview.days_daytime[0]!.date))).toBeInTheDocument()
  // Кнопки повтора на месте старта больше нет — её заменил ответ.
  expect(screen.queryByRole("button", { name: new RegExp(`${FAILED_SITE}.*Повторить`) })).toBeNull()
})

// Та же проверка, что уже стоит на группах скана: день, нажатый внутри группы
// конкретного старта, открывает прогноз ЭТОГО старта. Здесь она особенно
// нужна: под рукой сразу два чужих имени — старт в пропе `site` и старт внутри
// самого ответа (фикстура снята с «Гудаури»).
test("день перезапрошенного старта открывает прогноз ЭТОГО старта", async () => {
  stubScanAndForecast(scanWithFailed([FAILED_SITE]), overview)
  const onOpenDay = vi.fn()
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={onOpenDay} />, { wrapper })
  await openAllSites()
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(FAILED_SITE) }))

  const group = await screen.findByRole("group", { name: FAILED_SITE })
  const target = overview.days_daytime[2]!
  await userEvent.click(within(group).getByRole("button", { name: new RegExp(fmtDate(target.date)) }))

  expect(onOpenDay).toHaveBeenCalledWith(FAILED_SITE, target.date)
})

// Скан кладёт в группу старта только лётные дни (forecast.py:97), а
// /api/forecast отдаёт ВСЕ дни диапазона — иначе перезапрошенный старт стоял бы
// в том же списке по другому правилу, чем его соседи. Правило берётся готовым
// ответом сервера (assessment.flyable → criteria.flyable), своей копии порога у
// приложения нет намеренно (финальное ревью ветки, I2).
test("в группе перезапрошенного старта только лётные дни", async () => {
  const firstNotFlyable = {
    ...overview,
    days_daytime: overview.days_daytime.map((day, i) => (
      i === 0 ? { ...day, assessment: { ...day.assessment, flyable: false } } : day
    )),
  }
  stubScanAndForecast(scanWithFailed([FAILED_SITE]), firstNotFlyable)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await openAllSites()
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(FAILED_SITE) }))

  const group = await screen.findByRole("group", { name: FAILED_SITE })
  expect(within(group).getAllByRole("button")).toHaveLength(overview.days_daytime.length - 1)
  expect(within(group).queryByText(fmtDate(overview.days_daytime[0]!.date))).toBeNull()
})

// Тот же вердикт, что домен положил бы в Scan.empty, если бы запрос не упал.
// Пустая группа вместо слов читалась бы как «повтор не сработал».
test("повтор без единого лётного дня объясняется словами", async () => {
  const nothingFlyable = {
    ...overview,
    days_daytime: overview.days_daytime.map((day) => (
      { ...day, assessment: { ...day.assessment, flyable: false } }
    )),
  }
  stubScanAndForecast(scanWithFailed([FAILED_SITE]), nothingFlyable)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await openAllSites()
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(FAILED_SITE) }))

  expect(await screen.findByText(/ни одного лётного дня/)).toBeInTheDocument()
  expect(screen.queryByRole("group", { name: FAILED_SITE })).toBeNull()
})

// Упавших стартов бывает несколько (снимок пилота: четыре в одной строке), и
// рамка отказа сама по себе не говорит, чей повтор не прошёл.
test("отказавший повтор называет старт и снова даёт повторить", async () => {
  stubScanAndForecast(scanWithFailed([FAILED_SITE]), { detail: "" }, 502)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await openAllSites()
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(FAILED_SITE) }))

  expect(await screen.findByText(/open-meteo сейчас недоступна/)).toBeInTheDocument()
  expect(screen.getByText(FAILED_SITE)).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument()
})

// «Все старты» — переключатель, и выключение размонтирует ScanView вместе со
// строками упавших стартов. Пока строка помнила только собственное «повтор
// нажали», это стирало уже полученный ответ: пилот возвращался на вкладку и
// снова видел «Повторить» на месте дней. Сам ответ при этом никуда не девался —
// он лежит в кэше по ключу ["forecast", name, "week", null, model], — поэтому
// строка спрашивает не «нажимали ли здесь повтор», а «есть ли уже ответ».
test("полученный повтором ответ переживает выключение и включение «Все старты»", async () => {
  const fetchMock = stubScanAndForecast(scanWithFailed([FAILED_SITE]), overview)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await openAllSites()
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(FAILED_SITE) }))
  await screen.findByRole("group", { name: FAILED_SITE })

  await openAllSites()
  await openAllSites()

  expect(await screen.findByRole("group", { name: FAILED_SITE })).toBeInTheDocument()
  // Ответ взят из кэша, а не выпрошен заново: повторный тяжёлый запрос за теми
  // же данными занял бы единственный слот пилота (api.py:one_at_a_time).
  expect(callsTo(fetchMock, "/api/forecast")).toHaveLength(1)
})

// Та же память, но на отказе: вернувшись на вкладку, пилот должен видеть, чем
// кончился его повтор, а не предложение начать сначала.
test("отказавший повтор переживает выключение и включение «Все старты»", async () => {
  stubScanAndForecast(scanWithFailed([FAILED_SITE]), { detail: "" }, 502)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await openAllSites()
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(FAILED_SITE) }))
  await screen.findByText(/open-meteo сейчас недоступна/)

  await openAllSites()
  await openAllSites()

  expect(await screen.findByText(/open-meteo сейчас недоступна/)).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument()
})

test("повтор одного упавшего старта не трогает соседний", async () => {
  stubScanAndForecast(scanWithFailed([FAILED_SITE, OTHER_FAILED_SITE]), overview)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await openAllSites()
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(FAILED_SITE) }))
  await screen.findByRole("group", { name: FAILED_SITE })

  expect(screen.getByRole("button", { name: new RegExp(`${OTHER_FAILED_SITE}.*Повторить`) })).toBeInTheDocument()
  expect(screen.queryByRole("group", { name: OTHER_FAILED_SITE })).toBeNull()
})

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

  expect(fetchMock).not.toHaveBeenCalled()
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
  expect(fetchMock).not.toHaveBeenCalled()

  rerender(<Overview site="Гудаури" model="ecmwf" active onOpenDay={() => {}} />)
  await screen.findByRole("group", { name: "Дни диапазона" })
  expect(fetchMock.mock.calls.map(([u]) => String(u).split("?")[0])).toEqual(["/api/forecast"])
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

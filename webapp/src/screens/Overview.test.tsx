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
// /api/scan отдаёт переданный scanBody.
function stubByPath(scanBody: unknown = scan) {
  vi.stubGlobal("fetch", (url: string) => {
    const path = url.split("?")[0]
    return jsonResponse(path === "/api/scan" ? scanBody : overview)
  })
}

beforeEach(() => {
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: { initData: "auth_date=1&hash=abc" } }
})

test("строка на каждый день диапазона", async () => {
  stubByPath()
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
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
  await screen.findByRole("group", { name: "Дни диапазона" })
  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))

  const kazbegiGroup = await screen.findByRole("group", { name: "Казбеги" })
  await userEvent.click(within(kazbegiGroup).getByRole("button"))

  expect(onOpenDay).toHaveBeenCalledWith("Казбеги", secondSiteDate)
})

test("режим «Все старты» показывает старты и их дни", async () => {
  stubByPath()
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await screen.findByRole("group", { name: "Дни диапазона" })

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
  await screen.findByRole("group", { name: "Дни диапазона" })

  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))

  const site = scan.sites[0]!
  expect(site.aspect_deg).toBe(180)
  expect(await screen.findByText(`Ю · ${site.days.length} лётных`)).toBeInTheDocument()
})

test("старты без лётных дней перечислены отдельно", async () => {
  stubByPath(scanMixed)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await screen.findByRole("group", { name: "Дни диапазона" })

  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))

  expect(await screen.findByText(new RegExp(scanMixed.empty[0]!))).toBeInTheDocument()
  expect(screen.getByText(new RegExp(scanMixed.failed[0]!))).toBeInTheDocument()
})

// Тесты сверх шести из брифа.

test("пока грузится — показывает индикатор, а не пустоту", () => {
  vi.stubGlobal("fetch", (_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("отменено", "AbortError")))
  }))
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  expect(screen.getByRole("status", { name: "Загрузка" })).toBeInTheDocument()
})

test("на 502 показывает ошибку и кнопку повтора", async () => {
  vi.stubGlobal("fetch", () => jsonResponse({ detail: "" }, 502))
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  expect(await screen.findByText(/open-meteo сейчас недоступна/)).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument()
})

test("скан на ошибку тоже показывает кнопку повтора", async () => {
  vi.stubGlobal("fetch", (url: string) => {
    const path = url.split("?")[0]
    return path === "/api/scan" ? jsonResponse({ detail: "" }, 502) : jsonResponse(overview)
  })
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await screen.findByRole("group", { name: "Дни диапазона" })
  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))
  expect(await screen.findByText(/open-meteo сейчас недоступна/)).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument()
})

// Нет сохранённых стартов (свежая установка) — понятный текст вместо
// вечной загрузки, тот же приём, что и в Forecast.tsx/App.tsx (useForecast
// не запускает запрос, пока site === null).
test("без стартов — понятный текст, а не вечная загрузка", () => {
  vi.stubGlobal("fetch", () => jsonResponse(overview))
  render(<Overview site={null} model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  expect(screen.getByText("Нет стартов")).toBeInTheDocument()
})

// scan_mixed.json несёт непустые sites[].days ВМЕСТЕ с непустыми empty/failed
// (см. комментарий в scripts/dump_api_fixtures.py про never[]) — старт с
// лётными днями и старты без них показаны одновременно, каждый в своём месте.
test("скан со стартами и без лётных дней одновременно не теряет ни одного старта", async () => {
  stubByPath(scanMixed)
  render(<Overview site="Гудаури" model="ecmwf" onOpenDay={() => {}} />, { wrapper })
  await screen.findByRole("group", { name: "Дни диапазона" })
  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))

  const site = scanMixed.sites[0]!
  const group = await screen.findByRole("group", { name: site.name })
  expect(within(group).getAllByRole("button")).toHaveLength(site.days.length)
  expect(screen.getByText(new RegExp(scanMixed.empty[0]!))).toBeInTheDocument()
  expect(screen.getByText(new RegExp(scanMixed.failed[0]!))).toBeInTheDocument()
})

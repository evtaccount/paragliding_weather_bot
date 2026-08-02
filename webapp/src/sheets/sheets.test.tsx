// Тела шторок «Ветер по высотам» (WindGridSheet) и «Разбор от ИИ»
// (DayAnalysisSheet) — по образцу screens/Forecast.test.tsx: обёртка с
// QueryClientProvider, vi.stubGlobal("fetch", ...), подделка
// window.Telegram. SheetsProvider здесь не нужен — ни один из двух
// компонентов не открывает вложенных шторок и не читает useSheetsContext
// (в отличие от Forecast).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import { beforeEach, expect, test, vi } from "vitest"
import { StrictMode } from "react"
import type { ReactNode } from "react"
import { WindGridSheet } from "./WindGridSheet"
import { DayAnalysisSheet } from "./DayAnalysisSheet"
import type { WindGrid } from "../api/types"
import windGridFixture from "../../test/fixtures/wind_grid.json"

const GRID = windGridFixture as unknown as WindGrid

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

function jsonResponse(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }))
}

beforeEach(() => {
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: { initData: "auth_date=1&hash=abc" } }
})

// ------------------------------------------------------------ WindGridSheet

test("в сетке строка на каждый уровень и колонка на каждый час", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(GRID))
  render(<WindGridSheet site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })

  const rows = await screen.findAllByRole("row")
  // Строка заголовка (часы) + одна строка на каждый уровень.
  expect(rows).toHaveLength(GRID.levels.length + 1)

  const headerCells = within(rows[0]!).getAllByRole("columnheader")
  // Угловая пустая ячейка + один столбец на каждый час.
  expect(headerCells).toHaveLength(GRID.hours.length + 1)
})

test("уровень старта выделен", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(GRID))
  render(<WindGridSheet site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })

  const launchLevel = GRID.levels.find((lv) => lv.is_launch)
  if (!launchLevel) throw new Error("фикстура wind_grid.json должна содержать уровень старта")

  // Заякорено началом строки: без этого "10 м" совпадает ещё и с текстом
  // "2210 м MSL" того же уровня (2210 оканчивается на "10", дальше идёт
  // "м" — случайное совпадение цифр в фикстуре, а не в компоненте).
  const label = await screen.findByText(new RegExp(`^${launchLevel.label}`))
  const row = label.closest("tr")
  expect(row).toHaveAttribute("data-launch", "true")

  // Остальные строки не помечены как старт — атрибут отличает ровно одну строку.
  const otherRows = (await screen.findAllByRole("row")).filter((r) => r !== row && r.tagName === "TR")
  for (const r of otherRows) {
    if (r.querySelector("th[scope=col]")) continue // строка заголовка
    expect(r).toHaveAttribute("data-launch", "false")
  }
})

test("сетка сверху вниз идёт по убыванию высоты", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(GRID))
  render(<WindGridSheet site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })

  const rows = await screen.findAllByRole("row")
  const bodyRows = rows.slice(1) // без строки заголовка
  const altitudes = bodyRows.map((row) => {
    // Высота — в отдельном <div> внутри заголовка строки, не в его полном
    // textContent: у него подпись уровня ("10 м") склеена с высотой без
    // пробела, и для уровня старта (2210 м) "2210" сам оканчивается на
    // "10" — общий textContent даёт ложные цифры.
    const rowheader = within(row).getByRole("rowheader")
    const altText = rowheader.querySelector("div")?.textContent ?? ""
    const match = /(\d+)\s*м MSL/.exec(altText)
    if (!match) throw new Error(`не нашёл высоту в подписи строки: "${altText}"`)
    return Number(match[1])
  })
  const sortedDesc = [...altitudes].sort((a, b) => b - a)
  expect(altitudes).toEqual(sortedDesc)
})

test("пока сетка грузится — показывает индикатор", () => {
  vi.stubGlobal("fetch", () => new Promise<Response>(() => {}))
  render(<WindGridSheet site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  expect(screen.getByRole("status", { name: "Загрузка" })).toBeInTheDocument()
})

test("ошибка загрузки сетки — показывает ошибку и кнопку повтора", async () => {
  vi.stubGlobal("fetch", () => jsonResponse({ detail: "" }, 502))
  render(<WindGridSheet site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  expect(await screen.findByText(/open-meteo сейчас недоступна/)).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument()
})

test("пустая сетка не роняет шторку", async () => {
  vi.stubGlobal("fetch", () => jsonResponse({ ...GRID, levels: [] }))
  render(<WindGridSheet site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  const rows = await screen.findAllByRole("row")
  // Осталась только строка заголовка — ни одного уровня, но без падения.
  expect(rows).toHaveLength(1)
})

// Ревью (minor): шапка строится из data.hours, ячейки строки — из
// level.hourly того же уровня; совпадение длин и порядка раньше ничем не
// проверялось (позиционное сопоставление). У домена это гарантированный
// инвариант (engine.py строит оба списка по одному набору индексов), но
// если он когда-нибудь нарушится — таблица не должна молча съезжать.
test("уровень с неполным набором часов не сдвигает соседние колонки", async () => {
  const shortLevel = { ...GRID.levels[0]!, hourly: GRID.levels[0]!.hourly.filter((h) => h.hour !== 10) }
  vi.stubGlobal("fetch", () => jsonResponse({ ...GRID, levels: [shortLevel, ...GRID.levels.slice(1)] }))
  render(<WindGridSheet site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })

  const rows = await screen.findAllByRole("row")
  const shortRow = rows.find((r) => r.textContent?.startsWith(shortLevel.label))
  if (!shortRow) throw new Error("не нашёл строку урезанного уровня")
  const cells = within(shortRow).getAllByRole("cell")
  // Ровно столько ячеек, сколько часов в шапке — недостающий час рисует
  // прочерк на своём месте, а не съедает одну ячейку у соседних часов.
  expect(cells).toHaveLength(GRID.hours.length)
  expect(within(shortRow).getByText("—")).toBeInTheDocument()
})

// ------------------------------------------------------------ DayAnalysisSheet

test("разбор показывает текст от Gemini", async () => {
  vi.stubGlobal("fetch", () => jsonResponse({ text: "Лететь стоит, но окно короче, чем кажется по баллу." }))
  render(<DayAnalysisSheet site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  expect(await screen.findByText("Лететь стоит, но окно короче, чем кажется по баллу.")).toBeInTheDocument()
})

test("пока разбор считается — показывает индикатор", () => {
  vi.stubGlobal("fetch", () => new Promise<Response>(() => {}))
  render(<DayAnalysisSheet site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  expect(screen.getByRole("status", { name: "Загрузка" })).toBeInTheDocument()
})

test("разбор при 429 предлагает повторить, а не молчит", async () => {
  vi.stubGlobal("fetch", () => jsonResponse({ detail: "Уже считаю — дождись ответа." }, 429))
  render(<DayAnalysisSheet site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  expect(await screen.findByText("Уже считаю — дождись ответа.")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument()
})

test("длинный текст разбора сохраняет переносы строк", async () => {
  const text = "Первый абзац про окно.\nВторой абзац про термичку.\nТретий абзац с советом."
  vi.stubGlobal("fetch", () => jsonResponse({ text }))
  render(<DayAnalysisSheet site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  const paragraph = await screen.findByRole("paragraph")
  expect(paragraph.textContent).toBe(text)
  expect(paragraph).toHaveStyle({ whiteSpace: "pre-wrap" })
})

// Ревью: main.tsx оборачивает всё приложение в <StrictMode> безусловно
// (действует при каждом npm run dev, не только в тестах) — ни один из
// тестов выше этого не ловил, потому что ни один не рендерит дерево внутри
// <StrictMode>. Под ним React синхронно подписывает-отписывает-подписывает
// заново внутренний слушатель useSyncExternalStore (react-query's
// useMutation: mutationObserver.ts:96-100 — onUnsubscribe снимает
// observer с ТЕКУЩЕЙ мутации, если слушателей не осталось). Только второй
// вызов mutate() возвращает observer на мутацию — сторож против двойного
// вызова как раз его блокирует, и тогда результат первой (реально
// выполняющейся) мутации становится недоставляемым: экран висит на
// Spinner навсегда, без единой ошибки в консоли.
test("под строгим режимом разработки шторка всё равно показывает разбор", async () => {
  vi.stubGlobal("fetch", () => jsonResponse({ text: "Текст под строгим режимом разработки." }))
  render(
    <StrictMode>
      <DayAnalysisSheet site="Гудаури" date="2026-07-25" model="ecmwf" />
    </StrictMode>,
    { wrapper },
  )
  expect(await screen.findByText("Текст под строгим режимом разработки.")).toBeInTheDocument()
})

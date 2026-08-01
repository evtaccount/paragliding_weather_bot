// Тела тестов — по образцу api/queries.test.tsx: обёртка с
// QueryClientProvider, vi.stubGlobal("fetch", ...) с разбором пути запроса
// (здесь путь один — /api/forecast, поэтому фикстура отдаётся на любой
// запрос без ветвления по URL), подделка window.Telegram. Обёртка сверх
// того оборачивает в SheetsProvider (App.tsx) — без него useSheetsContext
// внутри Forecast бросил бы исключение вне провайдера.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import type { ReactNode } from "react"
import { Forecast } from "./Forecast"
import { SheetsProvider } from "../App"
import type { Facts } from "../api/types"
import facts from "../../test/fixtures/facts_1d.json"
import factsWindy from "../../test/fixtures/facts_1d_windy.json"
import factsNoCeiling from "../../test/fixtures/facts_1d_no_ceiling.json"
import factsNoWindow from "../../test/fixtures/facts_1d_no_window.json"
import windGrid from "../../test/fixtures/wind_grid.json"

const F = facts as unknown as Facts
const WINDY = factsWindy as unknown as Facts
const NO_CEILING = factsNoCeiling as unknown as Facts
const NO_WINDOW = factsNoWindow as unknown as Facts

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <SheetsProvider>{children}</SheetsProvider>
    </QueryClientProvider>
  )
}

function jsonResponse(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }))
}

beforeEach(() => {
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: { initData: "auth_date=1&hash=abc" } }
})

test("показывает вердикт дня и лётное окно", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(F))
  render(<Forecast site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  expect(await screen.findByText(F.assessment.label_ru)).toBeInTheDocument()
  expect(screen.getByText("07:00 – 17:00")).toBeInTheDocument()
})

test("пока грузится — показывает индикатор, а не пустоту", () => {
  // fetch слушает AbortSignal и отклоняет промис на abort — не только
  // корректности ради, а чтобы не зависнуть: React Query сам отменяет
  // запрос при размонтировании (тест заканчивается, RTL размонтирует
  // компонент), это освобождает очередь тяжёлых запросов (api/queue.ts)
  // без явного cancelQueries. На случай, если в будущем этот автоматический
  // разбор перестанет срабатывать (другая версия библиотеки, другой сценарий
  // размонтирования) — общий сброс очереди перед КАЖДЫМ тестом уже стоит в
  // test/setup.ts (resetQueueForTests), это вторая, независимая страховка.
  vi.stubGlobal("fetch", (_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("отменено", "AbortError")))
  }))
  render(<Forecast site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  expect(screen.getByRole("status", { name: "Загрузка" })).toBeInTheDocument()
})

test("на 502 показывает ошибку и кнопку повтора", async () => {
  vi.stubGlobal("fetch", () => jsonResponse({ detail: "" }, 502))
  render(<Forecast site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  expect(await screen.findByText(/open-meteo сейчас недоступна/)).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument()
})

test("кнопка «Ветер по высотам» открывает шторку", async () => {
  // Открытая шторка сама запрашивает /api/forecast/wind-grid (задача 9,
  // WindGridSheet) — единый ответ F на любой путь (как в остальных тестах
  // этого файла) отдал бы Facts вместо WindGrid и уронил бы шторку на
  // `data.levels` (у Facts такого поля нет). Тот же приём, что и в
  // App.test.tsx:53-57 — ветвление по пути, а не по паре реального URL.
  vi.stubGlobal("fetch", (url: string) => {
    const path = url.split("?")[0]
    return jsonResponse(path === "/api/forecast/wind-grid" ? windGrid : F)
  })
  render(<Forecast site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  await screen.findByText(F.assessment.label_ru)
  await userEvent.click(screen.getByRole("button", { name: /Ветер по высотам/ }))
  expect(await screen.findByRole("dialog", { name: "Ветер по высотам" })).toBeInTheDocument()
})

test("кнопка «Разбор от ИИ» открывает шторку", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(F))
  render(<Forecast site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  await screen.findByText(F.assessment.label_ru)
  await userEvent.click(screen.getByRole("button", { name: /Разбор от ИИ/ }))
  expect(await screen.findByRole("dialog", { name: "Разбор от ИИ" })).toBeInTheDocument()
})

// Сверх пяти тестов брифа: кнопка метеограммы — сама метеограмма (новый
// компонент этой задачи), а не временная заглушка задачи 9, поэтому её
// стоит проверить так же тщательно, как вердикт.
test("кнопка «Метеограмма» открывает шторку с графиком", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(F))
  render(<Forecast site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  await screen.findByText(F.assessment.label_ru)
  await userEvent.click(screen.getByRole("button", { name: /Метеограмма/ }))
  const dialog = await screen.findByRole("dialog", { name: "Метеограмма" })
  expect(within(dialog).getByRole("img", { name: /Метеограмма/ })).toBeInTheDocument()
})

// Сверх пяти тестов брифа: три особые фикстуры не должны ронять экран.
test("без потолка — не выдумывает высоту", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(NO_CEILING))
  render(<Forecast site="Плато" date="2026-07-25" model="ecmwf" />, { wrapper })
  expect(await screen.findByText(NO_CEILING.assessment.label_ru)).toBeInTheDocument()
  expect(screen.getByText(/потолок неизвестен/i)).toBeInTheDocument()
})

test("без окна термички — не падает и объясняет, что окна нет", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(NO_WINDOW))
  render(<Forecast site="Гудаури-Север" date="2026-12-15" model="ecmwf" />, { wrapper })
  expect(await screen.findByText(NO_WINDOW.assessment.label_ru)).toBeInTheDocument()
  expect(screen.getByText(/окно не определено/)).toBeInTheDocument()
  expect(screen.getByText(/термическое окно не открывается/)).toBeInTheDocument()
})

// Ревью: наличие всех блоков уже проверено выше, но ни один тест не ловит,
// если их переставить местами — так и случилось (строка ограничения стояла
// перед столбом воздуха, кнопки — перед оговорками). Проверяем порядок в
// самом документе (compareDocumentPosition), а не порядок вызовов
// screen.getByXxx в тесте, который сам по себе ничего не гарантирует.
test("порядок на экране: вердикт → полоса часов → столб воздуха → строка ограничения → оговорки → кнопки", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(F))
  render(<Forecast site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  await screen.findByText(F.assessment.label_ru)

  const verdict = screen.getByText(F.assessment.label_ru)
  const hourStrip = screen.getByRole("img", { name: /Полоса часов дня/ })
  const airColumn = screen.getByRole("img", { name: /Столб воздуха/ })
  const limiting = screen.getByText("Ограничивает")
  const caveats = screen.getByText("Оговорки")
  const actions = screen.getByRole("button", { name: /Ветер по высотам/ })

  const order = [verdict, hourStrip, airColumn, limiting, caveats, actions]
  for (let i = 0; i < order.length - 1; i++) {
    const before = order[i]!
    const after = order[i + 1]!
    expect(before.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  }
})

test("с предупреждениями — показывает оговорки о вето", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(WINDY))
  render(<Forecast site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  expect(await screen.findByText(WINDY.assessment.label_ru)).toBeInTheDocument()
  expect(screen.getByText(/вето внутри окна/)).toBeInTheDocument()
})

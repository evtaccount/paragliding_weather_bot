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

test("пока грузится — показывает индикатор, а не пустоту", async () => {
  // Свой QueryClient (а не общий wrapper) и fetch, реагирующий на
  // AbortSignal, — не только чтобы проверить спиннер, а чтобы после теста
  // явно освободить очередь тяжёлых запросов (api/queue.ts: `busy` —
  // модульный синглтон на весь файл). Промис, который никогда не
  // рассчитывается и не слушает signal, навсегда оставил бы `busy = true`
  // и уронил бы все следующие тесты этого файла тем же зависшим "Загрузка"
  // — ровно то падение, которое объясняет комментарий у одноимённого теста
  // в api/queries.test.tsx.
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function localWrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
        <SheetsProvider>{children}</SheetsProvider>
      </QueryClientProvider>
    )
  }
  vi.stubGlobal("fetch", (_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("отменено", "AbortError")))
  }))
  render(<Forecast site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper: localWrapper })
  expect(screen.getByRole("status", { name: "Загрузка" })).toBeInTheDocument()
  await qc.cancelQueries({ queryKey: ["forecast", "Гудаури", "1d", "2026-07-25", "ecmwf"] })
})

test("на 502 показывает ошибку и кнопку повтора", async () => {
  vi.stubGlobal("fetch", () => jsonResponse({ detail: "" }, 502))
  render(<Forecast site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  expect(await screen.findByText(/open-meteo сейчас недоступна/)).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument()
})

test("кнопка «Ветер по высотам» открывает шторку", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(F))
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

test("с предупреждениями — показывает оговорки о вето", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(WINDY))
  render(<Forecast site="Гудаури" date="2026-07-25" model="ecmwf" />, { wrapper })
  expect(await screen.findByText(WINDY.assessment.label_ru)).toBeInTheDocument()
  expect(screen.getByText(/вето внутри окна/)).toBeInTheDocument()
})

import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import { StrictMode } from "react"
import { App } from "./App"
import { fmtDate } from "./format"
import facts from "../test/fixtures/facts_1d.json"
import overview from "../test/fixtures/forecast_3d.json"
import sites from "../test/fixtures/sites.json"
import prefs from "../test/fixtures/prefs.json"

beforeEach(() => {
  const back = { show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() }
  // Подсказка типов здесь не нужна, в отличие от telegram.test.ts (там
  // объект идёт через отдельную функцию fakeWebApp(), и её возвращаемый
  // тип выводится независимо от Window.Telegram, из-за чего colorScheme
  // сужается до string и падает настоящая ошибка типов): здесь литерал
  // объекта стоит прямо в присваивании, TypeScript типизирует его
  // контекстно по Window.Telegram, "dark" сужается до "light"|"dark" сам,
  // и ошибки нет. Директива-подсказка тут оказалась бы "неиспользуемой"
  // (TS2578) и уронила бы tsc --noEmit — расходится с дословным текстом
  // брифа, см. task-6-report.md.
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

// Известная недоделка задачи 6 (progress.md, Task 6 m2): пустой список
// стартов (свежая установка, задача 13 ещё не даёт способа его завести) —
// раньше показывал спиннер, который никогда не пропадал (siteLabel
// возвращал undefined и на "ещё грузится", и на "пуст" одинаково). Задача 8
// первой заводит в шапку настоящие данные и приводит это в порядок.
test("шапка показывает понятный текст, а не вечную загрузку, когда список стартов пуст", async () => {
  vi.stubGlobal("fetch", (url: string) => {
    const path = url.split("?")[0]
    const body = path === "/api/sites" ? "[]" : "{}"
    return Promise.resolve(new Response(body, { status: 200, headers: { "content-type": "application/json" } }))
  })
  render(<App />)
  // Область поиска — именно шапка (role="banner" у <header>), а не весь
  // документ: вкладка «Прогноз» при том же пустом списке стартов показывает
  // собственный текст "Нет стартов" (Forecast.tsx) — без сужения тест был
  // бы зелёным и на старой ошибке (спиннер в шапке навсегда), просто найдя
  // чужую надпись.
  const header = screen.getByRole("banner")
  await waitFor(() => {
    expect(within(header).getByText("Нет стартов")).toBeInTheDocument()
  })
})

// Ревью task-9: main.tsx оборачивает всё приложение в <StrictMode>
// безусловно (действует при каждом npm run dev). Открытие шторки «Разбор
// от ИИ» через настоящий клик в настоящем дереве — DayAnalysisSheet
// монтируется не первым коммитом всего дерева, а ПОЗЖЕ, из setState стека
// шторок (App.tsx: sheets.push) глубоко внутри — и этого достаточно,
// чтобы React синхронно отписал и переподписал внутренний слушатель
// useSyncExternalStore, на котором построен useMutation
// (@tanstack/query-core, mutationObserver.ts: onUnsubscribe снимает
// observer с ТЕКУЩЕЙ мутации, когда слушателей не осталось; заново он
// возвращается только повторным вызовом mutate()). Прямой рендер шторки в
// изоляции внутри <StrictMode> (без настоящего дерева и настоящего клика)
// эту гонку не ловит — проверено при разборе ревью: воспроизводится только
// через настоящий путь монтирования, поэтому тест здесь, рядом с
// остальными тестами полного дерева App, а не в sheets.test.tsx.
test("под строгим режимом разработки открытие «Разбор от ИИ» доходит до текста, а не виснет", async () => {
  vi.stubGlobal("fetch", (url: string) => {
    const path = url.split("?")[0]
    const body =
      path === "/api/sites" ? sites
      : path === "/api/prefs" ? prefs
      // Вкладка «Обзор» (задача 10) смонтирована всегда, как и «Прогноз» —
      // её собственный запрос (range=3d по умолчанию) идёт на тот же путь
      // /api/forecast, но с другой формой ответа (ForecastOverview, а не
      // Facts): без ветвления по range этот тест ловил экран обзора на
      // чужой фикстуре и падал на .days_daytime, которого у Facts нет.
      : path === "/api/forecast" && url.includes("range=1d") ? facts
      : path === "/api/forecast" ? { days_daytime: [] }
      : path === "/api/analysis" ? { text: "Разбор под строгим режимом разработки." }
      : {}
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }))
  })
  render(<StrictMode><App /></StrictMode>)
  await screen.findByText(facts.assessment.label_ru)
  await userEvent.click(screen.getByRole("button", { name: /Разбор от ИИ/ }))
  expect(await screen.findByText("Разбор под строгим режимом разработки.")).toBeInTheDocument()
})

// Задача 10: тап по дню в «Обзоре» должен по-настоящему переключать вкладку
// «Прогноз» на выбранный день, а не только на вкладку с прежней (сегодняшней)
// датой — до этой задачи App.tsx передавал в Forecast константный todayIso().
// Проверяется здесь, на настоящем дереве App, а не в Overview.test.tsx: там
// проверяется только вызов колбэка onOpenDay, а не то, что App реально
// меняет дату запроса «Прогноза» в ответ на него.
test("тап по дню в «Обзоре» переключает вкладку «Прогноз» на дату этого дня", async () => {
  const fetchMock = vi.fn((url: string) => {
    const path = url.split("?")[0]
    const body =
      path === "/api/sites" ? sites
      : path === "/api/prefs" ? prefs
      : path === "/api/forecast" && url.includes("range=1d") ? facts
      : path === "/api/forecast" ? overview
      : {}
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }))
  })
  vi.stubGlobal("fetch", fetchMock)

  render(<App />)
  await userEvent.click(screen.getByRole("tab", { name: "Обзор" }))
  const target = overview.days_daytime[2]!
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(fmtDate(target.date)) }))

  expect(screen.getByRole("tab", { name: "Прогноз" })).toHaveAttribute("aria-selected", "true")
  await waitFor(() => {
    const calls = fetchMock.mock.calls.map(([u]) => String(u))
    expect(calls.some((u) => u.includes("range=1d") && u.includes(`date=${target.date}`))).toBe(true)
  })
})

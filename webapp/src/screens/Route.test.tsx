// Тела тестов — по образцу screens/Forecast.test.tsx: обёртка с
// QueryClientProvider + SheetsProvider (App.tsx) — экран открывает шторки
// (карточка точки, разбор маршрута), поэтому SheetsProvider нужен, как и в
// Forecast.test.tsx (в отличие от Overview.test.tsx, который шторок не
// открывает). vi.stubGlobal("fetch", ...) с разбором пути запроса — POST
// /api/route (useRoute) и POST /api/route/analysis (useRouteAnalysis) разные
// эндпоинты с разными формами ответа, путать их фикстурой одного эндпоинта
// на другом уронило бы экран так же, как и на других экранах приложения (см.
// комментарий в Overview.test.tsx/Forecast.test.tsx про ту же ловушку).
//
// route.json — настоящий ответ POST /api/route (RouteResult).
// route_no_terrain.json — тот же маршрут, но Elevation API не ответил
// (terrain: null) — экран обязан это пережить (см. task-12-brief.md).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import { StrictMode } from "react"
import type { ReactNode } from "react"
import { Route } from "./Route"
import { RouteProfile } from "../charts/RouteProfile"
import { SheetsProvider } from "../App"
import { roleLabel } from "../sheets/PointCardSheet"
import { fmtNum } from "../format"
import type { RoutePointRow } from "../api/queries"
import type { RouteResult } from "../api/types"
import routeFixture from "../../test/fixtures/route.json"
import routeNoTerrainFixture from "../../test/fixtures/route_no_terrain.json"

const ROUTE = routeFixture as unknown as RouteResult
const ROUTE_NO_TERRAIN = routeNoTerrainFixture as unknown as RouteResult

// Формат [lat, lon, name] — как принимает проп `points` экрана (тот же
// формат, в котором маршруты хранит store и отдаёт /api/route/parse).
// Собирается ИЗ ТОЧЕК ответа (по одной, через .map) — не присваивается
// массивом целиком куда-то, где ждут другую форму: обходит ловушку типов,
// описанную в task-12-brief.md (RoutePoint.subs/groups в союзе трёх форм
// точек конфликтуют с индексной сигнатурой Record<string, number>, если
// присвоить route.points скопом), хотя здесь она и не встретилась бы — эти
// три поля (lat/lon/name) во всех формах точки одинаковы.
const POINTS: RoutePointRow[] = ROUTE.points.map((p): RoutePointRow => [p.lat, p.lon, p.name])

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
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

test("показывает вердикт маршрута и километраж", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />, { wrapper })

  expect(await screen.findByText(ROUTE.verdict.label)).toBeInTheDocument()
  expect(screen.getByText(/40\s*км/)).toBeInTheDocument()
  expect(screen.getByText("70,5")).toBeInTheDocument()
})

// Главный риск разреза (см. комментарий в RouteProfile.tsx и в forecast.py
// рядом с формированием "terrain"): рельеф приходит ОТДЕЛЬНОЙ сеткой со
// своим километражом, и шаг у разных плеч разный — рисовать по ПОРЯДКОВОМУ
// НОМЕРУ сэмпла (считая шаг одинаковым) значит молча сдвинуть рельеф
// относительно погоды. Юнит-тест самого RouteProfile (без сети) на заведомо
// неравномерной сетке [0, 1, 10] км: по километражу два первых вершины
// должны лечь ЗАМЕТНО ближе друг к другу, чем вторая и третья (шаг 1 км
// против 9 км) — по индексу (наивная и неверная реализация) оба шага были
// бы РАВНЫ, по одному "шагу массива" каждый.
test("разрез рисует рельеф из terrain, а не из точек", () => {
  const terrain = { km: [0, 1, 10], elevations: [1000, 1050, 1100] }
  const { container } = render(<RouteProfile points={[]} terrain={terrain} bottleneckKm={null} />)

  const outline = container.querySelector("polyline.route-terrain")
  expect(outline).not.toBeNull()
  const xs = outline!.getAttribute("points")!.trim().split(/\s+/).map((pair) => Number(pair.split(",")[0]))
  // Число вершин разреза = terrain.km.length, а не points.length (0 здесь).
  expect(xs).toHaveLength(terrain.km.length)

  const [x0, x1, x2] = xs as [number, number, number]
  expect(x1 - x0).toBeGreaterThan(0)
  expect(x2 - x1).toBeGreaterThan((x1 - x0) * 4)
})

test("маршрут без terrain не роняет экран", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE_NO_TERRAIN))
  render(
    <Route points={POINTS} name={ROUTE_NO_TERRAIN.route.name} date={ROUTE_NO_TERRAIN.route.date} model="ecmwf" />,
    { wrapper },
  )

  expect(await screen.findByText(ROUTE_NO_TERRAIN.verdict.label)).toBeInTheDocument()
  expect(screen.getByText(/разрез не построен/)).toBeInTheDocument()
  expect(screen.getByText(ROUTE_NO_TERRAIN.notes[0]!)).toBeInTheDocument()
})

test("нажатие на точку открывает её карточку", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />, { wrapper })
  await screen.findByText(ROUTE.verdict.label)

  const target = ROUTE.points[0]!
  await userEvent.click(screen.getByRole("button", { name: new RegExp(`^${fmtNum(target.km)} км`) }))

  expect(
    await screen.findByRole("dialog", { name: new RegExp(`${target.eta}.*${roleLabel(target.role)}`) }),
  ).toBeInTheDocument()
})

test("перебор времени вылета шлёт новый запрос с departure", async () => {
  // Параметры перечислены явно, хотя тело их не читает: без них выведенный
  // тип вызова — пустой кортеж, и разбор mock.calls ниже не компилируется.
  const fetchMock = vi.fn((_url: string, _init?: RequestInit) => jsonResponse(ROUTE))
  vi.stubGlobal("fetch", fetchMock)
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />, { wrapper })
  await screen.findByText(ROUTE.verdict.label)

  const target = ROUTE.departure_scan.find((e) => e.departure !== ROUTE.route.departure)!
  await userEvent.click(screen.getByRole("button", { name: new RegExp(`^${target.departure} →`) }))

  await waitFor(() => {
    const bodies = fetchMock.mock.calls
      .map(([, init]) => init as RequestInit | undefined)
      .filter((init): init is RequestInit => init?.method === "POST")
      .map((init) => JSON.parse(String(init.body)) as { departure?: string | null })
    expect(bodies.some((b) => b.departure === target.departure)).toBe(true)
  })
})

test("разбор маршрута показывает текст", async () => {
  vi.stubGlobal("fetch", (url: string) => {
    const path = url.split("?")[0]
    return jsonResponse(path === "/api/route/analysis" ? { text: "Маршрут проходится, но без запаса." } : ROUTE)
  })
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />, { wrapper })
  await screen.findByText(ROUTE.verdict.label)

  await userEvent.click(screen.getByRole("button", { name: /Разбор от ИИ/ }))
  expect(await screen.findByText("Маршрут проходится, но без запаса.")).toBeInTheDocument()
})

// Тесты сверх шести из брифа.

test("пока считается — показывает индикатор, а не пустоту", () => {
  vi.stubGlobal("fetch", (_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("отменено", "AbortError")))
  }))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />, { wrapper })
  expect(screen.getByRole("status", { name: "Загрузка" })).toBeInTheDocument()
})

test("на 502 показывает ошибку и кнопку повтора", async () => {
  vi.stubGlobal("fetch", () => jsonResponse({ detail: "" }, 502))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />, { wrapper })
  expect(await screen.findByText(/open-meteo сейчас недоступна/)).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument()
})

// route.py:MIN_POINTS = 2 — меньше точек сервер бы просто отклонил; экран
// не должен уходить в сеть впустую на заведомо неполном маршруте.
test("меньше двух точек — понятный текст, а не запрос", () => {
  const fetchMock = vi.fn(() => jsonResponse(ROUTE))
  vi.stubGlobal("fetch", fetchMock)
  render(<Route points={[POINTS[0]!]} name={null} date="2026-08-01" model="ecmwf" />, { wrapper })

  expect(screen.getByText("Нет маршрута")).toBeInTheDocument()
  expect(fetchMock).not.toHaveBeenCalled()
})

// Маршрут из двух точек (минимум по route.py:MIN_POINTS) — граничный случай,
// который короткий маршрут из route.json (5 точек) не проверяет сам по себе.
test("маршрут из двух точек не роняет экран", async () => {
  const twoPointRoute: RouteResult = {
    ...ROUTE,
    points: [ROUTE.points[0]!, ROUTE.points[ROUTE.points.length - 1]!],
  }
  const twoPoints: RoutePointRow[] = [POINTS[0]!, POINTS[POINTS.length - 1]!]
  vi.stubGlobal("fetch", () => jsonResponse(twoPointRoute))
  render(<Route points={twoPoints} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />, { wrapper })

  expect(await screen.findByText(ROUTE.verdict.label)).toBeInTheDocument()
  expect(screen.getAllByRole("button", { name: /км ·/ })).toHaveLength(2)
})

// Ревью task-9/task-11: main.tsx оборачивает всё приложение в <StrictMode>
// безусловно (каждый npm run dev). Route.tsx и RouteAnalysisSheet.tsx зовут
// mutate() в эффекте без стража против повторного вызова (см. комментарий в
// обоих файлах) — тот же класс дефекта, что уже был Critical на
// DayAnalysisSheet.tsx (task-9): страж ломал шторку под <StrictMode>, потому
// что второй вызов mutate() — единственный, что возвращает наблюдателя
// TanStack Query на мутацию после того, как React синхронно отписал его при
// пересборке эффекта. Открытие «Разбор от ИИ» проверено через настоящий клик
// в настоящем дереве (а не изолированным рендером шторки) — task-9 явно
// показал, что дефект воспроизводится только так.
test("под строгим режимом разработки маршрут доходит до вердикта, а не виснет", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  render(
    <StrictMode>
      <Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />
    </StrictMode>,
    { wrapper },
  )
  expect(await screen.findByText(ROUTE.verdict.label)).toBeInTheDocument()
})

test("под строгим режимом разработки открытие «Разбор от ИИ» доходит до текста, а не виснет", async () => {
  vi.stubGlobal("fetch", (url: string) => {
    const path = url.split("?")[0]
    return jsonResponse(path === "/api/route/analysis" ? { text: "Разбор под строгим режимом разработки." } : ROUTE)
  })
  render(
    <StrictMode>
      <Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />
    </StrictMode>,
    { wrapper },
  )
  await screen.findByText(ROUTE.verdict.label)
  await userEvent.click(screen.getByRole("button", { name: /Разбор от ИИ/ }))
  expect(await screen.findByText("Разбор под строгим режимом разработки.")).toBeInTheDocument()
})

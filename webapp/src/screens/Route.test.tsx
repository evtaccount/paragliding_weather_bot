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
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import { StrictMode, useState } from "react"
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

// QueryClient создаётся ЛЕНИВО через useState, а не выражением в теле
// обёртки: под <StrictMode> (strictWrapper ниже) React вызывает тело
// компонента дважды, а при любом ре-рендере обёртки — ещё раз, и каждый
// такой вызов подсовывал бы провайдеру НОВЫЙ клиент, обнуляя состояние уже
// запущенных мутаций.
function makeClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
}

function wrapper({ children }: { children: ReactNode }) {
  const [qc] = useState(makeClient)
  return (
    <QueryClientProvider client={qc}>
      <SheetsProvider>{children}</SheetsProvider>
    </QueryClientProvider>
  )
}

// Обёртка для тестов «под строгим режимом разработки»: <StrictMode> обязан
// быть СНАРУЖИ SheetsProvider, а не приходить в него как children. Шторку
// SheetsProvider рендерит собственным сиблингом детей (App.tsx:74-78) — с
// <StrictMode> внутри children шторка монтируется ВНЕ строгого режима, её
// эффект выполняется один раз, и тест зеленеет даже с дефектом, ради
// которого написан (ревью task-12, Critical-2: оба строгих теста были
// инертны). В настоящем дереве порядок именно такой — main.tsx оборачивает
// в <StrictMode> весь <App/> целиком, вместе со стеком шторок; так же
// сделано в App.test.tsx:108.
function strictWrapper({ children }: { children: ReactNode }) {
  const [qc] = useState(makeClient)
  return (
    <StrictMode>
      <QueryClientProvider client={qc}>
        <SheetsProvider>{children}</SheetsProvider>
      </QueryClientProvider>
    </StrictMode>
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
  // Проходимость (route.py:FEASIBILITY_RU) — часть вердикта, а не
  // необязательное украшение: карточка в Telegram печатает её строкой под
  // баллом всегда (route.py:_verdict_lines).
  expect(screen.getByText("маршрут проходится")).toBeInTheDocument()
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

// Ревью task-12 (Important-1): балл и категория НЕ различают время вылета, при
// котором маршрут не успеть до закрытия окна. В route.json вылет 15:30 даёт
// feasibility "too_slow" при тех же 70,5 и «отличная лётная», что и
// completable — без строки проходимости экран рисовал для них побайтово
// одинаковый вердикт, и пилот читал «отличная лётная · 70,5» для времени, в
// которое он не успевает. В карточке Telegram этого не бывает:
// route.py:_verdict_lines печатает FEASIBILITY_RU всегда.
test("вердикт и чипы вылета показывают проходимость, а не только балл", async () => {
  const tooSlow: RouteResult = { ...ROUTE, verdict: { ...ROUTE.verdict, feasibility: "too_slow" } }
  vi.stubGlobal("fetch", () => jsonResponse(tooSlow))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />, { wrapper })

  expect(await screen.findByText("не успеваешь до закрытия окна")).toBeInTheDocument()
  // Балл и категория при этом ровно те же, что у проходимого маршрута —
  // отличает варианты только строка проходимости.
  expect(screen.getByText("70,5")).toBeInTheDocument()
  expect(screen.getByText(ROUTE.verdict.label)).toBeInTheDocument()
  // Тот же разрыв в чипах перебора: 15:30 и 11:30 показывают одинаковые
  // «70,5», а проходимость у них разная (departure_scan[].feasibility).
  expect(screen.getByRole("button", { name: "15:30 → 70,5 · не успеваешь до закрытия окна" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "11:30 → 70,5 · маршрут проходится" })).toBeInTheDocument()
})

// Ревью task-12 (Important-4): тест «нажатие на точку открывает её карточку»
// сверяет только заголовок шторки, а его собирает сам Route.tsx — тело
// карточки не проверялось ничем (замена всего PointCardSheet на <div/>
// оставляла все тесты зелёными). Здесь проверяются именно числа этой точки:
// подпись высоты берётся из её thermal_ceiling_m, а «Земля» — единственная
// строка карточки, где домен отдаёт м/с и их надо перевести в км/ч
// (route.py:MS_TO_KMH): 2,0/4,0 м/с → 7/14 км/ч.
test("карточка точки показывает погоду именно этой точки", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />, { wrapper })
  await screen.findByText(ROUTE.verdict.label)

  const target = ROUTE.points[0]!
  await userEvent.click(screen.getByRole("button", { name: new RegExp(`^${fmtNum(target.km)} км`) }))
  const card = await screen.findByRole("dialog")

  expect(within(card).getByText("Ветер 2200 м")).toBeInTheDocument()
  expect(within(card).getByText("14 км/ч ЮЮЗ")).toBeInTheDocument()
  expect(within(card).getByText("Земля")).toBeInTheDocument()
  expect(within(card).getByText("7/14 км/ч")).toBeInTheDocument()
  expect(within(card).getByText("2464 м")).toBeInTheDocument()
  // Подпись и значение — разные узлы (<em>Ограничивает:</em> плюс текст),
  // поэтому две проверки, а не одна на всю строку.
  expect(within(card).getByText("Ограничивает:")).toBeInTheDocument()
  expect(within(card).getByText(/спред/)).toBeInTheDocument()
})

// Ревью task-12 (Important-4): колонки «вдоль» и «ветер» не проверял никто —
// замена обеих на константы оставляла все тесты зелёными. Формат тот же, что
// у таблицы в Telegram (route.py:_rows): знак составляющей вдоль курса несёт
// стрелка, само число берётся по модулю, ветер — румб плюс скорость.
test("таблица точек показывает составляющую вдоль курса и ветер на рабочей высоте", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />, { wrapper })
  await screen.findByText(ROUTE.verdict.label)

  const target = ROUTE.points[1]!
  const row = screen.getByRole("button", { name: new RegExp(`^${fmtNum(target.km)} км`) })
  expect(within(row).getByText("←14")).toBeInTheDocument()
  expect(within(row).getByText("ЮЮЗ 14")).toBeInTheDocument()
})

// Ревью task-12 (Important-3): renderRoute начинается с карты
// (prototype.html:1071-1082), а на экране её не было — весь Leaflet задачи 11
// оставался мёртвым кодом. Маркеров ровно столько, сколько точек в ответе:
// карта показывает посчитанный профиль, а не только поворотные точки.
test("на экране маршрута есть карта с точками маршрута", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  const { container } = render(
    <Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />,
    { wrapper },
  )
  await screen.findByText(ROUTE.verdict.label)

  expect(container.querySelector(".leaflet-container")).not.toBeNull()
  expect(container.querySelectorAll(".leaflet-marker-icon")).toHaveLength(ROUTE.points.length)
})

// Строка запаса окна и обратного маршрута — prototype.html:1166. Запас
// считается как в карточке Telegram (route.py:990-993): первая и последняя
// точка с посчитанным запасом, знак — типографский минус/плюс.
test("показывает запас окна и балл обратного маршрута", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />, { wrapper })
  await screen.findByText(ROUTE.verdict.label)

  expect(screen.getByText(/Запас окна: старт \+450 мин · финиш \+231 мин/)).toBeInTheDocument()
  expect(screen.getByText(/Обратный маршрут — 84,0/)).toBeInTheDocument()
})

// Имя маршрута необязательно (api.py:RouteIn — `name: str | None = None`), и
// App.tsx сегодня передаёт именно null: строка вердикта не должна начинаться
// с висячего разделителя « · вылет …».
test("безымянный маршрут не показывает висячий разделитель", async () => {
  const noName: RouteResult = { ...ROUTE, route: { ...ROUTE.route, name: null } }
  vi.stubGlobal("fetch", () => jsonResponse(noName))
  render(<Route points={POINTS} name={null} date={ROUTE.route.date} model="ecmwf" />, { wrapper })
  await screen.findByText(ROUTE.verdict.label)

  expect(screen.getByText(/^вылет 11:30/)).toBeInTheDocument()
})

// Ревью task-12 (Important-4): коридор и база облаков не проверялись ничем —
// `bandPolygon = null` и `cloudBaseLine = null` (разрез без обоих слоёв)
// оставляли все тесты зелёными.
test("разрез рисует рабочий коридор и базу облаков", () => {
  const { container } = render(
    <RouteProfile points={ROUTE.points} terrain={ROUTE.terrain} bottleneckKm={null} />,
  )

  const band = container.querySelector("polygon.route-band")
  expect(band).not.toBeNull()
  // Коридор замкнут: верх по потолку термички каждой точки плюс низ по
  // рельефу тех же точек в обратном порядке.
  expect(band!.getAttribute("points")!.trim().split(/\s+/)).toHaveLength(ROUTE.points.length * 2)

  const base = container.querySelector("polyline.route-cloud-base")
  expect(base).not.toBeNull()
  expect(base!.getAttribute("points")!.trim().split(/\s+/)).toHaveLength(ROUTE.points.length)
})

// Ревью task-12 (Important-2): километр точки округлён доменом до 0,1
// (forecast.py:_point_dict), а километр узкого места приходит сырым float
// (criteria.py:802) — на route.json это 10.007557221018047 против 10,0, и
// строгое равенство не выделяло подпись никогда.
test("подпись узкого места выделена, хотя километр приходит неокруглённым", () => {
  const bottleneck = ROUTE.verdict.bottleneck!
  const { container } = render(
    <RouteProfile points={ROUTE.points} terrain={ROUTE.terrain} bottleneckKm={bottleneck.km} />,
  )

  const bold = container.querySelectorAll('text[font-weight="700"]')
  expect(bold).toHaveLength(1)
  expect(bold[0]!.textContent).toBe(String(Math.round(bottleneck.km)))
})

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
    <Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />,
    { wrapper: strictWrapper },
  )
  expect(await screen.findByText(ROUTE.verdict.label)).toBeInTheDocument()
})

test("под строгим режимом разработки открытие «Разбор от ИИ» доходит до текста, а не виснет", async () => {
  vi.stubGlobal("fetch", (url: string) => {
    const path = url.split("?")[0]
    return jsonResponse(path === "/api/route/analysis" ? { text: "Разбор под строгим режимом разработки." } : ROUTE)
  })
  render(
    <Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" />,
    { wrapper: strictWrapper },
  )
  await screen.findByText(ROUTE.verdict.label)
  await userEvent.click(screen.getByRole("button", { name: /Разбор от ИИ/ }))
  expect(await screen.findByText("Разбор под строгим режимом разработки.")).toBeInTheDocument()
})

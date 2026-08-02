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
import { act, render, screen, waitFor, within } from "@testing-library/react"
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
import prefsFixture from "../../test/fixtures/prefs.json"

const ROUTE = routeFixture as unknown as RouteResult
const ROUTE_NO_TERRAIN = routeNoTerrainFixture as unknown as RouteResult
// Настоящий ответ GET /api/prefs (см. scripts/dump_api_fixtures.py): экран
// подписан на него ради маршрутной скорости и поправки на ветер — сервер
// считает маршрут по ним, а в теле запроса их нет.
const PREFS = prefsFixture

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

// Обёртка с ЗАДАННЫМ клиентом: нужна там, где тест сам кладёт свежий ответ в
// кэш — так же, как это делает PATCH настроек (useUpdatePrefs.onSuccess).
// Обычный `wrapper` создаёт клиент внутри себя, и дотянуться до него неоткуда.
function clientWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <SheetsProvider>{children}</SheetsProvider>
      </QueryClientProvider>
    )
  }
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

// Тело ПОСЛЕДНЕГО запроса расчёта маршрута (POST /api/route). Экран шлёт их
// несколько за сеанс (монтирование, смена времени вылета, смена маршрута), и
// проверять надо именно последний: «есть хоть один запрос без departure»
// верно всегда — первый запрос уходит без времени по определению.
type RouteRequestBody = { name?: string | null; date?: string; departure?: string | null }

type FetchMock = { mock: { calls: [string, (RequestInit | undefined)?][] } }

// Только расчёты маршрута: экран ходит ещё и за настройками пилота
// (usePrefs — лёгкий запрос к тому же кэшу, что и у оболочки), а считать
// «сколько всего было запросов» значит считать не то.
function routePosts(fetchMock: FetchMock): [string, (RequestInit | undefined)?][] {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url).split("?")[0] === "/api/route" && init?.method === "POST")
}

function lastRouteBody(fetchMock: FetchMock): RouteRequestBody {
  const posts = routePosts(fetchMock)
  const last = posts[posts.length - 1]
  if (!last) throw new Error("расчёт маршрута ни разу не запрашивался")
  return JSON.parse(String(last[1]!.body)) as RouteRequestBody
}

beforeEach(() => {
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: { initData: "auth_date=1&hash=abc" } }
})

test("показывает вердикт маршрута и километраж", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })

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
    <Route points={POINTS} name={ROUTE_NO_TERRAIN.route.name} date={ROUTE_NO_TERRAIN.route.date} model="ecmwf" onPickRoute={() => {}} />,
    { wrapper },
  )

  expect(await screen.findByText(ROUTE_NO_TERRAIN.verdict.label)).toBeInTheDocument()
  expect(screen.getByText(/разрез не построен/)).toBeInTheDocument()
  expect(screen.getByText(ROUTE_NO_TERRAIN.notes[0]!)).toBeInTheDocument()
})

// Нажимается НЕ первая строка (третья точка, 20 км): заголовок шторки,
// собранный из points[0] вместо нажатой точки, обязан ронять этот тест — с
// первой строкой такая подмена неотличима (ре-ревью task-12, N2). Тот же
// класс дефекта был Critical задачи 10: тап по дню открывал прогноз первого
// старта.
test("нажатие на точку открывает её карточку", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })
  await screen.findByText(ROUTE.verdict.label)

  const target = ROUTE.points[2]!
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
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })
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

// Ревью задачи 13 (N1): экран «Маршрут» не размонтируется никогда (вкладки
// скрыты через hidden, App.tsx), поэтому выбранное чипом время вылета
// переживало смену маршрута — и следующий маршрут считался по времени,
// подобранному для предыдущего. До задачи 13 дефект был недостижим: маршрут
// нельзя было сменить. Проверяется на ПОСЛЕДНЕМ теле запроса, а не на «есть
// хоть один запрос без departure»: первый запрос (при монтировании) и так
// уходит без времени, и проверка «какой-нибудь» зеленела бы при живом дефекте.
test("новый маршрут считается по своему окну, а не по времени прежнего", async () => {
  const fetchMock = vi.fn((_url: string, _init?: RequestInit) => jsonResponse(ROUTE))
  vi.stubGlobal("fetch", fetchMock)
  const { rerender } = render(
    <Route points={POINTS} name="Маршрут А" date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />,
    { wrapper },
  )
  await screen.findByText(ROUTE.verdict.label)

  // Пилот подобрал время вылета маршруту А.
  const target = ROUTE.departure_scan.find((e) => e.departure !== ROUTE.route.departure)!
  await userEvent.click(screen.getByRole("button", { name: new RegExp(`^${target.departure} →`) }))
  await waitFor(() => {
    expect(lastRouteBody(fetchMock).departure).toBe(target.departure)
  })

  // И открыл другой маршрут — другая ССЫЛКА на точки, как из шторки
  // «Сохранённые».
  const otherPoints: RoutePointRow[] = POINTS.slice(0, 3).map(([lat, lon, n]): RoutePointRow => [lat + 0.1, lon, n])
  rerender(
    <Route points={otherPoints} name="Маршрут Б" date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />,
  )

  await waitFor(() => {
    const body = lastRouteBody(fetchMock)
    expect(body.name).toBe("Маршрут Б")
    // Время вылета маршрута Б выбирает сервер (route.py:get_route — начало
    // термического окна первой точки), а не чип, нажатый у маршрута А.
    expect(body.departure).toBeNull()
  })
})

// Ре-ревью задачи 13 (N13): число точек в шапке панели маршрута осталось без
// склонения, хотя на кнопке шторки и в «Сохранённых» то же число уже
// склоняется (fmtPoints). На маршруте ~200 км сервер отдаёт 21 сэмпл — панель
// писала «21 точек» рядом с кнопкой, где написано «21 точка». Фикстура тут
// подменяется точечно: в route.json сэмплов 5, а «5 точек» одинаково у обеих
// реализаций и дефект не показывает.
test("число сэмплов в шапке маршрута склоняется", async () => {
  const many = { ...ROUTE, route: { ...ROUTE.route, sample_count: 21 } }
  vi.stubGlobal("fetch", () => jsonResponse(many))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })
  await screen.findByText(ROUTE.verdict.label)

  expect(screen.getByText(/^21 точка · шаг/)).toBeInTheDocument()
})

// Ревью задачи 13 (N4): в макете (prototype.html:1182-1186) широкой сделана
// «Новый маршрут» (mk(..., true)), а «Разбор от ИИ» и «Сохранённые» делят
// первый ряд. Раскладка .acts — grid 1fr 1fr плюс act--wide (grid-column:
// 1 / -1), то есть перестановка широкой кнопки зеркалит весь блок. Сверять
// это глазами станет задача 15 (Playwright), но класс проверить можно уже
// сейчас — иначе расхождение с единственным источником вёрстки живёт молча.
test("широкой в блоке действий стоит «Новый маршрут», как в макете", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })
  await screen.findByText(ROUTE.verdict.label)

  expect(screen.getByRole("button", { name: /Новый маршрут/ })).toHaveClass("act--wide")
  for (const name of [/Разбор от ИИ/, /Сохранённые/]) {
    expect(screen.getByRole("button", { name })).not.toHaveClass("act--wide")
  }
})

test("разбор маршрута показывает текст", async () => {
  vi.stubGlobal("fetch", (url: string) => {
    const path = url.split("?")[0]
    return jsonResponse(path === "/api/route/analysis" ? { text: "Маршрут проходится, но без запаса." } : ROUTE)
  })
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })
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
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })

  expect(await screen.findByText("не успеваешь до закрытия окна")).toBeInTheDocument()
  // Балл и категория при этом ровно те же, что у проходимого маршрута —
  // отличает варианты только строка проходимости.
  expect(screen.getByText("70,5")).toBeInTheDocument()
  expect(screen.getByText(ROUTE.verdict.label)).toBeInTheDocument()
  // Тот же разрыв в чипах перебора: 15:30 и 11:30 показывают одинаковые
  // «70,5», а проходимость у них разная (departure_scan[].feasibility).
  // Проверяется ВИДИМЫЙ текст, а не только доступное имя (ре-ревью, N3): в
  // Telegram на телефоне title не всплывает, aria-label читает только
  // скринридер, и по доступному имени тест был бы зелёным при полностью
  // одинаковых на вид чипах.
  expect(screen.getByText("15:30 → 70,5 · не успеваешь до закрытия окна")).toBeInTheDocument()
  expect(screen.queryByText("15:30 → 70,5")).toBeNull()
  expect(screen.getByText("11:30 → 70,5")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "15:30 → 70,5 · не успеваешь до закрытия окна" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "11:30 → 70,5 · маршрут проходится" })).toBeInTheDocument()
})

// Ревью task-12 (Important-4): тест «нажатие на точку открывает её карточку»
// сверяет только заголовок шторки, а его собирает сам Route.tsx — тело
// карточки не проверялось ничем (замена всего PointCardSheet на <div/>
// оставляла все тесты зелёными).
//
// Ре-ревью (N2): открываются ДВЕ разные точки подряд, и первая — не первая
// строка таблицы. Точка 20 км идёт по маршруту (enroute): у неё свой балл 69
// и свой лимитирующий фактор, а строки «Земля» нет вовсе — наземный ветер
// показывается только там, где пилот стоит на земле (route.py:
// render_point_card). Точка 0 км — старт: балл 84, «Земля» есть, и это
// единственное место карточки, где домен отдаёт м/с и их надо перевести в
// км/ч (route.py:MS_TO_KMH): 2,0/4,0 м/с → 7/14 км/ч. Карточка, всегда
// показывающая первую точку, роняет первую половину теста; карточка,
// потерявшая перевод единиц или строку роли, — вторую.
test("карточка точки показывает погоду именно этой точки", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })
  await screen.findByText(ROUTE.verdict.label)

  const enroute = ROUTE.points[2]!
  await userEvent.click(screen.getByRole("button", { name: new RegExp(`^${fmtNum(enroute.km)} км`) }))
  const enrouteCard = await screen.findByRole("dialog")

  expect(within(enrouteCard).getByText("69,0")).toBeInTheDocument()
  expect(within(enrouteCard).getByText(/ветер вдоль курса/)).toBeInTheDocument()
  expect(within(enrouteCard).queryByText("Земля")).toBeNull()
  expect(within(enrouteCard).getByText("Ветер 2200 м")).toBeInTheDocument()
  expect(within(enrouteCard).getByText("14 км/ч ЮЮЗ")).toBeInTheDocument()
  expect(within(enrouteCard).getByText("2464 м")).toBeInTheDocument()

  await userEvent.click(within(enrouteCard).getByRole("button", { name: "Закрыть" }))
  const takeoff = ROUTE.points[0]!
  await userEvent.click(screen.getByRole("button", { name: new RegExp(`^${fmtNum(takeoff.km)} км`) }))
  const takeoffCard = await screen.findByRole("dialog")

  expect(within(takeoffCard).getByText("84,0")).toBeInTheDocument()
  expect(within(takeoffCard).getByText("Земля")).toBeInTheDocument()
  expect(within(takeoffCard).getByText("7/14 км/ч")).toBeInTheDocument()
  // Подпись и значение — разные узлы (<em>Ограничивает:</em> плюс текст),
  // поэтому две проверки, а не одна на всю строку.
  expect(within(takeoffCard).getByText("Ограничивает:")).toBeInTheDocument()
  expect(within(takeoffCard).getByText(/спред/)).toBeInTheDocument()
})

// Ревью task-12 (Important-4): колонки «вдоль» и «ветер» не проверял никто —
// замена обеих на константы оставляла все тесты зелёными. Формат тот же, что
// у таблицы в Telegram (route.py:_rows): знак составляющей вдоль курса несёт
// стрелка, само число берётся по модулю, ветер — румб плюс скорость.
test("таблица точек показывает составляющую вдоль курса и ветер на рабочей высоте", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })
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
// Трасса (ре-ревью, N7) — единственное, что показывает их ПОРЯДОК: без линии
// пять одинаковых пинов не читаются как маршрут (в макете её рисует drawMap,
// prototype.html:1339-1342).
test("на экране маршрута есть карта с точками маршрута и трассой", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  const { container } = render(
    <Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />,
    { wrapper },
  )
  await screen.findByText(ROUTE.verdict.label)

  expect(container.querySelector(".leaflet-container")).not.toBeNull()
  expect(container.querySelectorAll(".leaflet-marker-icon")).toHaveLength(ROUTE.points.length)
  expect(container.querySelector("path.pgbot-track")).not.toBeNull()
})

// Ре-ревью task-12 (N7): в макете пин — кнопка, открывающая карточку точки
// (prototype.html:1345-1356), а перенесённые маркеры не слушали нажатие
// вовсе. Нажимается пин НЕ первой точки — по той же причине, что и в тесте
// строки таблицы (N2). Доступное имя пина — подпись из макета «Точка N км,
// балл X»: Leaflet делает маркер кнопкой (role="button"), и без подписи у
// неё нет имени ни для пилота, ни для теста.
test("нажатие на пин карты открывает карточку той же точки", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })
  await screen.findByText(ROUTE.verdict.label)

  const target = ROUTE.points[2]!
  await userEvent.click(
    screen.getByRole("button", { name: `Точка ${fmtNum(target.km)} км, балл ${fmtNum(target.score!)}` }),
  )

  expect(
    await screen.findByRole("dialog", { name: new RegExp(`${target.eta}.*${roleLabel(target.role)}`) }),
  ).toBeInTheDocument()
})

// Ре-ревью task-12 (N5): легенда под разрезом не была закреплена ничем —
// мутация «легенда убрана» оставляла весь прогон зелёным. Без подписей три
// слоя (заливка рельефа, полупрозрачный коридор, пунктир базы) пилоту не
// различить — prototype.html:1113-1119.
test("под разрезом есть легенда трёх слоёв", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })
  await screen.findByText(ROUTE.verdict.label)

  expect(screen.getByText("рельеф")).toBeInTheDocument()
  expect(screen.getByText("рабочий коридор")).toBeInTheDocument()
  expect(screen.getByText("база облаков")).toBeInTheDocument()
})

// Строка запаса окна и обратного маршрута — prototype.html:1166. Запас
// считается как в карточке Telegram (route.py:990-993): первая и последняя
// точка с посчитанным запасом, знак — типографский минус/плюс.
test("показывает запас окна и балл обратного маршрута", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })
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
  render(<Route points={POINTS} name={null} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })
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
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })
  expect(screen.getByRole("status", { name: "Загрузка" })).toBeInTheDocument()
})

test("на 502 показывает ошибку и кнопку повтора", async () => {
  vi.stubGlobal("fetch", () => jsonResponse({ detail: "" }, 502))
  render(<Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })
  expect(await screen.findByText(/open-meteo сейчас недоступна/)).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument()
})

// route.py:MIN_POINTS = 2 — меньше точек сервер бы просто отклонил; экран
// не должен уходить в сеть впустую на заведомо неполном маршруте.
test("меньше двух точек — понятный текст, а не запрос", () => {
  const fetchMock = vi.fn((_url: string, _init?: RequestInit) => jsonResponse(ROUTE))
  vi.stubGlobal("fetch", fetchMock)
  render(<Route points={[POINTS[0]!]} name={null} date="2026-08-01" model="ecmwf" onPickRoute={() => {}} />, { wrapper })

  expect(screen.getByText("Нет маршрута")).toBeInTheDocument()
  expect(routePosts(fetchMock)).toHaveLength(0)
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
  render(<Route points={twoPoints} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />, { wrapper })

  expect(await screen.findByText(ROUTE.verdict.label)).toBeInTheDocument()
  expect(screen.getAllByRole("button", { name: /км ·/ })).toHaveLength(2)
})

// Ревью task-9/task-11: main.tsx оборачивает всё приложение в <StrictMode>
// безусловно (каждый npm run dev), поэтому оба теста ниже идут через
// strictWrapper — дерево той же формы, что в проде, а не голый рендер.
//
// ВАЖНО, что именно ловит каждый из них (ре-ревью task-12, N4 — прежний
// комментарий обещал за оба больше, чем проверял):
//
// Первый тест НЕ является регрессионным на страж против повторного вызова
// mutate(). Проверено мутацией: страж (`useRef(false)` + ранний выход),
// поставленный в эффект Route.tsx, оставляет этот тест ЗЕЛЁНЫМ, а красным
// делает «перебор времени вылета шлёт новый запрос с departure» — на экране
// страж ломает не доставку первого результата, а законный повторный запрос
// при смене departure. Этот тест закрепляет другое: что экран под двойным
// монтированием доходит до вердикта, а не остаётся на индикаторе (двойной
// вызов mutate() проходит через очередь heavy() и не отменяет сам себя).
//
// Второй тест (шторка) — тот самый регрессионный: возвращение стража в
// эффект RouteAnalysisSheet.tsx роняет его по таймауту, проверено и в
// красной фазе круга правок 1, и мутацией. Дефект того же класса был
// Critical на DayAnalysisSheet.tsx (task-9): второй вызов mutate() —
// единственный, что возвращает наблюдателя TanStack Query на мутацию после
// того, как React отписал его при пересборке эффекта; страж блокировал
// именно его. Воспроизводится только настоящим кликом в настоящем дереве, а
// не изолированным рендером шторки (task-9 это показал явно).
test("под строгим режимом разработки маршрут доходит до вердикта, а не виснет", async () => {
  vi.stubGlobal("fetch", () => jsonResponse(ROUTE))
  render(
    <Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />,
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
    <Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />,
    { wrapper: strictWrapper },
  )
  await screen.findByText(ROUTE.verdict.label)
  await userEvent.click(screen.getByRole("button", { name: /Разбор от ИИ/ }))
  expect(await screen.findByText("Разбор под строгим режимом разработки.")).toBeInTheDocument()
})

// Финальное ревью ветки, I5. Та же ось, что N1 задачи 13, только вторая:
// выбранное время вылета было привязано к маршруту, но не к дате. Пилот
// подобрал «18:00» сегодняшнему дню, ушёл в «Обзор» и тапнул другой день —
// новый день молча считался с departure прежнего, хотя термическое окно у
// него другое и «18:00» может не быть в departure_scan вовсе: ни один чип не
// подсвечен, а маршрут посчитан по времени, которого в списке нет. Вернуть
// «пусть выбирает сервер» пилоту при этом нечем.
test("другой день считается по своему окну, а не по времени, подобранному вчера", async () => {
  const fetchMock = vi.fn((_url: string, _init?: RequestInit) => jsonResponse(ROUTE))
  vi.stubGlobal("fetch", fetchMock)
  const { rerender } = render(
    <Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf" onPickRoute={() => {}} />,
    { wrapper },
  )
  await screen.findByText(ROUTE.verdict.label)

  const target = ROUTE.departure_scan.find((e) => e.departure !== ROUTE.route.departure)!
  await userEvent.click(screen.getByRole("button", { name: new RegExp(`^${target.departure} →`) }))
  await waitFor(() => {
    expect(lastRouteBody(fetchMock).departure).toBe(target.departure)
  })

  // Тот же маршрут (та же ССЫЛКА на точки), другой день — как после тапа по
  // дню в «Обзоре».
  rerender(
    <Route points={POINTS} name={ROUTE.route.name} date="2026-07-31" model="ecmwf" onPickRoute={() => {}} />,
  )

  await waitFor(() => {
    const body = lastRouteBody(fetchMock)
    expect(body.date).toBe("2026-07-31")
    expect(body.departure).toBeNull()
  })
})

// Финальное ревью ветки, I3: скрытая вкладка не тратит единственный слот
// пилота. У «Маршрута» это не запрос-подписка, а мутация в эффекте, поэтому
// проверяется отдельно от «Прогноза» и «Обзора».
test("скрытый экран маршрута не считает маршрут, а показанный — считает", async () => {
  const fetchMock = vi.fn((_url: string, _init?: RequestInit) => jsonResponse(ROUTE))
  vi.stubGlobal("fetch", fetchMock)
  const { rerender } = render(
    <Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf"
           active={false} onPickRoute={() => {}} />,
    { wrapper },
  )
  // Пауза внутри act: за эти 20 мс приходит ответ /api/prefs (экран подписан
  // на настройки, см. Route.tsx), и React обновляет состояние — снаружи act
  // это законный повод для предупреждения в stderr.
  await act(async () => { await new Promise((resolve) => { setTimeout(resolve, 20) }) })
  // Считается ТЯЖЁЛЫЙ запрос: слот пилота на сервере занимает расчёт маршрута
  // (api.py:one_at_a_time), а не подписка на настройки.
  expect(routePosts(fetchMock)).toHaveLength(0)

  rerender(
    <Route points={POINTS} name={ROUTE.route.name} date={ROUTE.route.date} model="ecmwf"
           active onPickRoute={() => {}} />,
  )
  expect(await screen.findByText(ROUTE.verdict.label)).toBeInTheDocument()
})

// Обратная сторона той же правки: возвращение на вкладку не должно считать
// заново то, что уже посчитано. Без памяти о последнем отправленном вводе
// каждое переключение вкладок туда-обратно стоило бы пилоту ещё одного
// тяжёлого запроса — то самое, ради устранения чего эффект и гасится.
test("возвращение на вкладку не пересчитывает тот же маршрут", async () => {
  const fetchMock = vi.fn((_url: string, _init?: RequestInit) => jsonResponse(ROUTE))
  vi.stubGlobal("fetch", fetchMock)
  const props = { points: POINTS, name: ROUTE.route.name, date: ROUTE.route.date, model: "ecmwf", onPickRoute: () => {} }
  const { rerender } = render(<Route {...props} active />, { wrapper })
  await screen.findByText(ROUTE.verdict.label)
  expect(routePosts(fetchMock)).toHaveLength(1)

  rerender(<Route {...props} active={false} />)
  rerender(<Route {...props} active />)
  // Пауза внутри act: за эти 20 мс приходит ответ /api/prefs (экран подписан
  // на настройки, см. Route.tsx), и React обновляет состояние — снаружи act
  // это законный повод для предупреждения в stderr.
  await act(async () => { await new Promise((resolve) => { setTimeout(resolve, 20) }) })

  expect(routePosts(fetchMock)).toHaveLength(1)
})

// Финальное ревью ветки, круг 2 (I3). Маршрутная скорость и поправка на ветер
// в тело POST /api/route не едут — сервер берёт их из настроек пилота сам
// (forecast.py:_evaluate), — и показанный маршрут оставался посчитанным по
// прежним: пилот считал маршрут, шёл в «Настройки», трижды жал «+» (25 → 28
// км/ч), возвращался и видел ТЕ ЖЕ времена прилёта и тот же запас окна, а
// запросов после возвращения не было ни одного.
//
// Свежие настройки кладутся в кэш ровно так, как это делает сам PATCH
// (useUpdatePrefs.onSuccess: client.setQueryData(["prefs"], ответ сервера)) —
// это и есть то событие, которое экран обязан заметить. Проверяется ЧИСЛО
// расчётов, а не тело запроса: настроек в теле нет и быть не должно.
test("правка настроек пересчитывает показанный маршрут", async () => {
  const fetchMock = vi.fn((url: string, _init?: RequestInit) =>
    jsonResponse(String(url).split("?")[0] === "/api/prefs" ? PREFS : ROUTE))
  vi.stubGlobal("fetch", fetchMock)
  const client = makeClient()
  // Настройки уже в кэше — так и бывает в настоящем дереве: пока /api/prefs не
  // ответил, вкладка «Маршрут» неактивна и эффект не работает вовсе (App.tsx:
  // modelSettled). Без этой строки тест ловил бы не пересчёт по правке, а
  // приход настроек на пустом кэше — два расчёта на одном монтировании.
  client.setQueryData(["prefs"], PREFS)
  const props = { points: POINTS, name: ROUTE.route.name, date: ROUTE.route.date, model: "ecmwf", onPickRoute: () => {} }
  render(<Route {...props} />, { wrapper: clientWrapper(client) })
  await screen.findByText(ROUTE.verdict.label)
  await waitFor(() => { expect(routePosts(fetchMock)).toHaveLength(1) })

  act(() => { client.setQueryData(["prefs"], { ...PREFS, avg_route_speed_kmh: 28 }) })
  await waitFor(() => { expect(routePosts(fetchMock)).toHaveLength(2) })

  // Тумблер поправки на ветер — вторая настройка того же расчёта
  // (forecast.py:_evaluate выбирает по ней route.march или ровную скорость).
  act(() => {
    client.setQueryData(["prefs"], { ...PREFS, avg_route_speed_kmh: 28, wind_correction_enabled: false })
  })
  await waitFor(() => { expect(routePosts(fetchMock)).toHaveLength(3) })
})

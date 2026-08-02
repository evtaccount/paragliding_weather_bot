// Шторки ввода задачи 13: «Новый маршрут» (три способа задать точки),
// «Сохранённые маршруты», выбиралка старта.
//
// <StrictMode> стоит В ОБЁРТКЕ, снаружи всего дерева: main.tsx включает его
// безусловно, то есть под ним работает каждый npm run dev, а в проекте уже
// было три Critical на двойном вызове эффекта (задачи 9, 11, 12). Тесты,
// которые рендерят компонент вне строгого режима, такие дефекты пропускают —
// именно так задача 12 получила зелёный прогон при живом страже useRef.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import { StrictMode } from "react"
import type { ReactNode } from "react"
import { NewRouteSheet } from "./NewRouteSheet"
import { SavedRoutesSheet } from "./SavedRoutesSheet"
import { SitePickerSheet } from "./SitePickerSheet"
import type { RoutePointRow } from "../api/queries"
import type { SavedRoute, Site } from "../api/types"
import sitesFixture from "../../test/fixtures/sites.json"

const SITE = (sitesFixture as Site[])[0]!

// Три старта и три маршрута — минимум, на котором видно разницу между
// выбором ПО ИМЕНИ и выбором по индексу (Critical задачи 10: тап по дню
// второго старта открывал прогноз первого). Порядок намеренно не
// алфавитный: реализация «отсортировать и взять по индексу» на нём тоже
// краснеет.
const THREE_SITES: Site[] = [
  { ...SITE, name: "Гудаури", lat: 42.47, lon: 44.48 },
  { ...SITE, name: "Лалискури", lat: 42.51, lon: 42.32, aspect: "ЮВ", aspect_deg: 135, elevation_m: 900 },
  { ...SITE, name: "Казбеги", lat: 42.66, lon: 44.64, aspect: "З", aspect_deg: 270, elevation_m: 1750 },
]

// saved — ключ и форма настоящего GET /api/routes: ПОЛНЫЙ таймстамп в UTC
// (store.py:333 отдаёт `saved`, store.py:88-89 пишет туда isoformat в UTC),
// а не короткая дата. Разметка, приученная к дате, показывала пустоту
// (финальное ревью ветки, C1а).
const THREE_ROUTES: SavedRoute[] = [
  { name: "Гудаури — Коби", points: [[42.47, 44.48, "старт"], [42.53, 44.51, "Коби"]], saved: "2026-07-25T06:33:49+00:00" },
  { name: "Хребет на север", points: [[42.4, 44.4, null], [42.6, 44.4, null], [42.8, 44.4, "разворот"]], saved: "2026-07-26T06:33:49+00:00" },
  { name: "Казбеги — треугольник", points: [[42.66, 44.64, "старт"], [42.7, 44.8, "п1"], [42.6, 44.7, "п2"]], saved: "2026-07-27T20:41:02+00:00" },
]

type Call = { url: string; method: string; body: BodyInit | null | undefined }

const calls: Call[] = []

// Ответ может быть и промисом: тесту про «шторку открыли до ответа сервера»
// нужен запрос, который разрешается по команде, а не сразу.
function stubFetch(reply: (url: string, init?: RequestInit) => Response | Promise<Response>): void {
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), method: init?.method ?? "GET", body: init?.body })
    return Promise.resolve(reply(String(url), init))
  })
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } })
}

// Ответ по умолчанию на всё, чего тест не подделывает сам: списки должны
// быть списками — карта шторки рисует справочные пины стартов и на объекте
// вместо массива падает.
function defaultReply(url: string): Response {
  const path = url.split("?")[0]
  if (path === "/api/sites") return json(THREE_SITES)
  if (path === "/api/routes") return json([])
  return json({})
}

function callsTo(path: string): Call[] {
  return calls.filter((c) => c.url.split("?")[0] === path)
}

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return (
    <StrictMode>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </StrictMode>
  )
}

beforeEach(() => {
  calls.length = 0
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: { initData: "auth_date=1&hash=abc" } }
  stubFetch(defaultReply)
})

// Клик по карте приходит НЕ из React-события (слушатель ставит Leaflet), и
// состояние шторки меняется вне реактовой очереди — без act() React ругается
// и обновление может не доехать до проверки.
function tapMap(container: HTMLElement, x: number, y: number): void {
  const mapEl = container.querySelector(".leaflet-container")
  if (!mapEl) throw new Error("в шторке нет карты")
  act(() => {
    mapEl.dispatchEvent(new MouseEvent("click", { clientX: x, clientY: y, bubbles: true, cancelable: true }))
  })
}

// ------------------------------------------------------------ Новый маршрут

test("новый маршрут принимает точки, поставленные на карте", async () => {
  const onApply = vi.fn()
  const { container } = render(<NewRouteSheet onApply={onApply} />, { wrapper })

  tapMap(container, 10, 10)
  tapMap(container, 60, 40)

  // Пины на карте — то, что пилот видит сразу после тапа.
  expect(container.querySelectorAll(".leaflet-marker-icon")).toHaveLength(2)

  await userEvent.click(screen.getByRole("button", { name: /Показать маршрут/ }))

  expect(onApply).toHaveBeenCalledTimes(1)
  const [points] = onApply.mock.calls[0] as [RoutePointRow[], string | null]
  expect(points).toHaveLength(2)
  for (const p of points) {
    expect(typeof p[0]).toBe("number")
    expect(typeof p[1]).toBe("number")
  }
  // Две разные точки, а не одна и та же дважды: тап должен брать координаты
  // СВОЕГО нажатия, а не центр карты.
  expect(points[0]).not.toEqual(points[1])
  // Карта — единственный источник этих точек, на сервер за разбором никто
  // не ходил.
  expect(callsTo("/api/route/parse")).toHaveLength(0)
})

test("новый маршрут принимает список координат", async () => {
  const parsed: RoutePointRow[] = [
    [42.4776, 44.4787, "старт"],
    [42.3877, 44.4787, null],
    [42.2978, 44.4787, "финиш"],
  ]
  stubFetch((url) => (url === "/api/route/parse" ? json({ points: parsed }) : defaultReply(url)))

  const onApply = vi.fn()
  render(<NewRouteSheet onApply={onApply} />, { wrapper })

  await userEvent.type(screen.getByLabelText(/Список координат/), "42.4776, 44.4787{enter}42.3877, 44.4787")
  await userEvent.click(screen.getByRole("button", { name: "Разобрать" }))

  // Разобранные точки видны в шторке до того, как пилот их применит.
  expect(await screen.findByText(/финиш/)).toBeInTheDocument()

  const parseCalls = callsTo("/api/route/parse")
  expect(parseCalls).toHaveLength(1)
  expect(parseCalls[0]!.method).toBe("POST")
  const form = parseCalls[0]!.body as FormData
  expect(form).toBeInstanceOf(FormData)
  expect(form.get("text")).toBe("42.4776, 44.4787\n42.3877, 44.4787")
  // Ровно одно из двух полей на вызов (api.py:parse_route).
  expect(form.get("file")).toBeNull()

  await userEvent.click(screen.getByRole("button", { name: /Показать маршрут/ }))
  expect(onApply).toHaveBeenCalledWith(parsed, null)
})

test("новый маршрут принимает файл GPX", async () => {
  const parsed: RoutePointRow[] = [[42.4776, 44.4787, "GPX-точка"], [42.3877, 44.4787, null]]
  stubFetch((url) => (url === "/api/route/parse" ? json({ points: parsed }) : defaultReply(url)))

  const onApply = vi.fn()
  render(<NewRouteSheet onApply={onApply} />, { wrapper })

  const file = new File(["<gpx></gpx>"], "хребет.gpx", { type: "application/gpx+xml" })
  await userEvent.upload(screen.getByLabelText(/Файл GPX/), file)

  expect(await screen.findByText(/GPX-точка/)).toBeInTheDocument()

  const parseCalls = callsTo("/api/route/parse")
  expect(parseCalls).toHaveLength(1)
  const form = parseCalls[0]!.body as FormData
  expect(form).toBeInstanceOf(FormData)
  const sent = form.get("file")
  expect(sent).toBeInstanceOf(File)
  expect((sent as File).name).toBe("хребет.gpx")
  expect(form.get("text")).toBeNull()
})

test("сохранение маршрута с пустым именем не уходит на сервер", async () => {
  const onApply = vi.fn()
  const { container } = render(<NewRouteSheet onApply={onApply} />, { wrapper })

  // Точки есть — не сохраняется именно из-за пустого имени, а не потому,
  // что сохранять нечего.
  tapMap(container, 10, 10)
  tapMap(container, 60, 40)

  await userEvent.click(screen.getByRole("button", { name: "Сохранить" }))

  expect(callsTo("/api/routes")).toHaveLength(0)
  // Молча ничего не делать нельзя — пилот должен понять, чего не хватает.
  // Роль alert, а не поиск текста: подпись поля ввода тоже содержит слово
  // «имя», и поиск по тексту нашёл бы её вместо подсказки.
  expect(screen.getByRole("alert")).toHaveTextContent(/имя/i)

  // С именем тот же самый жест уходит на сервер — иначе тест был бы зелёным
  // и у кнопки, не работающей вовсе.
  await userEvent.type(screen.getByLabelText(/Имя маршрута/), "Хребет")
  await userEvent.click(screen.getByRole("button", { name: "Сохранить" }))

  const saveCalls = callsTo("/api/routes")
  expect(saveCalls).toHaveLength(1)
  expect(saveCalls[0]!.method).toBe("POST")
  expect(JSON.parse(String(saveCalls[0]!.body)).name).toBe("Хребет")
})

// Ре-ревью задачи 12 (N6): без onDragPoint MapView вовсе не делает маркеры
// перетаскиваемыми. Шторка «Новый маршрут» — единственное место, где точки
// двигают пальцем, и передача обоих колбэков ничем, кроме этого теста, не
// закреплена: пилот тащил бы пин, а маршрут считался бы по старым
// координатам. Рецепт событий — из map.test.tsx (which: 1, движение и
// отпускание на document.body).
test("точку нового маршрута можно передвинуть по карте", async () => {
  const onApply = vi.fn()
  const { container } = render(<NewRouteSheet onApply={onApply} />, { wrapper })

  tapMap(container, 10, 10)
  tapMap(container, 60, 40)
  const icons = container.querySelectorAll<HTMLElement>(".leaflet-marker-icon")
  expect(icons).toHaveLength(2)

  // Снимок ДО перетаскивания: без него тест зеленел бы и с неподвижным
  // маркером — две точки поставлены разными тапами и так различаются
  // координатами (мутация «убрать onDragPoint» такую проверку проходила).
  await userEvent.click(screen.getByRole("button", { name: /Показать маршрут/ }))
  const [before] = onApply.mock.calls[0] as [RoutePointRow[], string | null]

  const opts = (x: number, y: number): MouseEventInit =>
    ({ bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, which: 1 }) as MouseEventInit
  act(() => {
    icons[1]!.dispatchEvent(new MouseEvent("mousedown", opts(60, 40)))
    document.body.dispatchEvent(new MouseEvent("mousemove", opts(120, 90)))
    document.body.dispatchEvent(new MouseEvent("mouseup", opts(120, 90)))
  })

  await userEvent.click(screen.getByRole("button", { name: /Показать маршрут/ }))
  const [after] = onApply.mock.calls[1] as [RoutePointRow[], string | null]
  expect(after).toHaveLength(2)
  // Тащили ВТОРОЙ пин: первая точка осталась там же, вторая уехала.
  expect(after[0]).toEqual(before[0])
  expect(after[1]).not.toEqual(before[1])
})

// Ревью задачи 13 (N10): кнопка «Показать маршрут» была активна и при нуле
// точек, а её нажатие ЗАМЕНЯЕТ маршрут вкладки — пустой набор стирал уже
// посчитанный. Сценарий: разбор не удался, и пилот жмёт единственную заметную
// кнопку внизу, чтобы выйти.
test("пустой набор точек не применяется и не стирает прежний маршрут", async () => {
  const onApply = vi.fn()
  const { container } = render(<NewRouteSheet onApply={onApply} />, { wrapper })

  const apply = screen.getByRole("button", { name: /Показать маршрут/ })
  expect(apply).toBeDisabled()
  await userEvent.click(apply)
  expect(onApply).not.toHaveBeenCalled()

  // Появилась точка — кнопка ожила, и подпись склоняется по-русски
  // («1 точка», а не «1 точек»).
  tapMap(container, 10, 10)
  expect(screen.getByRole("button", { name: /Показать маршрут · 1 точка$/ })).toBeEnabled()
})

// ------------------------------------------------------- Сохранённые маршруты

test("сохранённый маршрут открывается тот, который выбрали", async () => {
  stubFetch((url) => (url === "/api/routes" ? json(THREE_ROUTES) : defaultReply(url)))
  const onPick = vi.fn()
  render(<SavedRoutesSheet onPick={onPick} />, { wrapper })

  // Не первый в списке: подмена «всегда первый» на первом элементе не видна
  // (разбор задачи 12).
  await userEvent.click(await screen.findByRole("button", { name: /Казбеги — треугольник/ }))

  expect(onPick).toHaveBeenCalledTimes(1)
  const [name, points] = onPick.mock.calls[0] as [string, RoutePointRow[]]
  expect(name).toBe("Казбеги — треугольник")
  expect(points).toEqual([[42.66, 44.64, "старт"], [42.7, 44.8, "п1"], [42.6, 44.7, "п2"]])
})

// Финальное ревью ветки, C1а: подпись маршрута читала несуществующий ключ
// `saved_at` (в фикстуре он был, в ответе сервера — нет), и после разделителя
// у пилота было пусто. Проверяется вся строка целиком: и число точек, и дата
// сохранения на своём месте.
test("под именем маршрута стоят число точек и дата сохранения", async () => {
  stubFetch((url) => (url === "/api/routes" ? json(THREE_ROUTES) : defaultReply(url)))
  render(<SavedRoutesSheet onPick={vi.fn()} />, { wrapper })

  const button = await screen.findByRole("button", { name: /Гудаури — Коби/ })
  expect(button).toHaveTextContent(/2 точки · \d{4}-\d{2}-\d{2}$/)
  // Дата — местная, а не срез таймстампа: ровно то, что делает чат
  // (bot.py:1088 _local_date). Проверяется на маршруте, сохранённом в
  // 20:41 UTC, — в поясе восточнее это уже следующий день.
  const late = await screen.findByRole("button", { name: /Казбеги — треугольник/ })
  const shown = new Date("2026-07-27T20:41:02+00:00")
  const expected = `${shown.getFullYear()}-${String(shown.getMonth() + 1).padStart(2, "0")}-${String(shown.getDate()).padStart(2, "0")}`
  expect(late).toHaveTextContent(`3 точки · ${expected}`)
})

test("маршрут без имён точек не теряет точки", async () => {
  stubFetch((url) => (url === "/api/routes" ? json(THREE_ROUTES) : defaultReply(url)))
  const onPick = vi.fn()
  render(<SavedRoutesSheet onPick={onPick} />, { wrapper })

  await userEvent.click(await screen.findByRole("button", { name: /Хребет на север/ }))

  const [, points] = onPick.mock.calls[0] as [string, RoutePointRow[]]
  // route.py:Point.name — `str | None`, и store хранит его как есть: имя
  // точки может быть null, и такая точка обязана доехать до расчёта.
  expect(points).toEqual([[42.4, 44.4, null], [42.6, 44.4, null], [42.8, 44.4, "разворот"]])
})

// ------------------------------------------------------------ Выбор старта

test("выбирается тот старт, по которому нажали", async () => {
  const onPick = vi.fn()
  render(<SitePickerSheet selected="Гудаури" onPick={onPick} />, { wrapper })

  await userEvent.click(await screen.findByRole("button", { name: /Казбеги/ }))

  expect(onPick).toHaveBeenCalledTimes(1)
  expect(onPick).toHaveBeenCalledWith("Казбеги")
})

test("в выбиралке старта отмечен текущий старт", async () => {
  render(<SitePickerSheet selected="Лалискури" onPick={vi.fn()} />, { wrapper })

  const active = await screen.findByRole("button", { name: /Лалискури/ })
  expect(active).toHaveAttribute("aria-pressed", "true")
  for (const name of ["Гудаури", "Казбеги"]) {
    expect(screen.getByRole("button", { name: new RegExp(name) })).toHaveAttribute("aria-pressed", "false")
  }
  // Подпись несёт то, чем старты различаются в поле: экспозицию и высоту.
  expect(within(active).getByText(/ЮВ/)).toBeInTheDocument()
})

// Site.aspect — строка В ТОМ ВИДЕ, В КАКОМ ЕЁ ЗАПИСАЛ АВТОР старта (store.py:216
// пишет как есть): поставочный sites.json в корне репозитория несёт латинское
// "S", а старт, заведённый из чата или из приложения, — «Ю». В одном списке
// это давало соседние строки «S 180°» и «Ю 180°». Румб считается из градусов,
// как в чате (engine.card), — авторская строка на экран не попадает.
test("румб в списке стартов один и тот же, кем бы старт ни был заведён", async () => {
  const mixed = [
    { ...SITE, name: "Лалискури", aspect: "S", aspect_deg: 180, elevation_m: 686 },
    { ...SITE, name: "Гудаури", aspect: "Ю", aspect_deg: 180, elevation_m: 2200 },
  ]
  stubFetch((url) => (url === "/api/sites" ? json(mixed) : defaultReply(url)))
  render(<SitePickerSheet selected="Гудаури" onPick={vi.fn()} />, { wrapper })

  const imported = await screen.findByRole("button", { name: /Лалискури/ })
  expect(imported).toHaveTextContent("Ю 180° · 686 м")
  expect(imported).not.toHaveTextContent("S")
})

// Ревью задачи 13 (N2): шторка кладётся в стек ГОТОВЫМ элементом, поэтому
// список, переданный ей пропом, застывал на момент нажатия. Пилот на холодном
// старте жал имя старта в шапке, читал «Нет стартов» — и продолжал читать это
// после того, как старты пришли, хотя в шапке уже было имя. Тест повторяет
// именно этот порядок: шторка открыта, СПИСКА ЕЩЁ НЕТ, ответ приходит потом.
test("выбиралка старта, открытая до ответа сервера, показывает пришедший список", async () => {
  let deliverSites = (): void => { throw new Error("fetch не был вызван") }
  const pending = new Promise<Response>((resolve) => {
    deliverSites = () => { resolve(json(THREE_SITES)) }
  })
  stubFetch(() => pending)

  render(<SitePickerSheet selected={null} onPick={vi.fn()} />, { wrapper })
  expect(screen.getByRole("status", { name: "Загрузка" })).toBeInTheDocument()
  expect(screen.queryByText("Нет стартов")).toBeNull()

  deliverSites()

  expect(await screen.findByRole("button", { name: /Казбеги/ })).toBeInTheDocument()
  // Отметка «текущий» тоже считается по пришедшему списку: явного выбора не
  // было (selected=null), значит отмечен первый старт — тот же, что показывает
  // оболочка (sites.ts:defaultSiteName).
  expect(screen.getByRole("button", { name: /Гудаури/ })).toHaveAttribute("aria-pressed", "true")
})

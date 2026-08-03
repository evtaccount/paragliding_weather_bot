import { act, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import { StrictMode } from "react"
import { App } from "./App"
import { fmtDate } from "./format"
// Приложение больше ничего не выбирает за пилота (просьба владельца, бриф
// explicit-site-and-day): старт и день — два нажатия в шапке, каждое со своей
// шторкой. Тесты, которым нужен посчитанный прогноз, проходят этот путь
// целиком, как пилот, а не подставляют состояние в обход.
import { pickDay, pickSite } from "../test/header"
import { isoInDays } from "../test/days"
import { RANGE_DAYS_2WEEKS } from "./domain"
import facts from "../test/fixtures/facts_1d.json"
import overview from "../test/fixtures/forecast_3d.json"
import scan from "../test/fixtures/scan.json"
import sites from "../test/fixtures/sites.json"
import prefs from "../test/fixtures/prefs.json"
import routeResult from "../test/fixtures/route.json"

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } })
}

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
  // Ответ по умолчанию — по КОНТРАКТУ эндпоинта, а не пустой "{}" на всё
  // подряд: раньше вкладка настроек была заглушкой <p>Настройки</p> и
  // подделка формы ответа никого не задевала. Теперь на ней настоящий экран
  // (задача 13), а он читает список моделей из /api/prefs и список стартов
  // из /api/sites — на "{}" вместо массива падал бы не он один, а всё
  // приложение: все четыре экрана смонтированы одновременно (см. разметку
  // вкладок ниже), поэтому исключение в скрытой вкладке уносит и видимую.
  vi.stubGlobal("fetch", (url: string) => {
    const path = String(url).split("?")[0]
    const body = path === "/api/sites" ? [] : path === "/api/prefs" ? prefs : {}
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200, headers: { "content-type": "application/json" } }))
  })
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
    const body = path === "/api/sites" ? [] : path === "/api/prefs" ? prefs : {}
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200, headers: { "content-type": "application/json" } }))
  })
  render(<App />)
  // Область поиска — именно шапка (role="banner" у <header>), а не весь
  // документ: без сужения тест был бы зелёным и на старой ошибке (спиннер в
  // шапке навсегда), просто найдя надпись соседнего экрана.
  const header = screen.getByRole("banner")
  expect(within(header).getByRole("button", { name: "Старт не выбран" })).toBeInTheDocument()

  // Про ПУСТУЮ библиотеку (а не просто «выбора не было») говорит сама шторка,
  // куда ведёт эта кнопка, — и говорит, что делать дальше. Шапке второй такой
  // подписи не нужно: выбор старта живёт в шторке, туда пилот и идёт.
  await userEvent.click(within(header).getByRole("button", { name: "Старт не выбран" }))
  // Ищем ВНУТРИ шторки: «Нет стартов» теперь говорит и «Обзор» — он
  // смонтирован всегда и на пустой библиотеке показывает то же самое (иначе
  // одна его половина предлагала бы выбрать старт там, где выбирать нечего).
  const sheet = await screen.findByRole("dialog")
  expect(within(sheet).getByText("Нет стартов")).toBeInTheDocument()
  // «Что делать дальше» — это вход в карту прямо здесь, а не отсылка на
  // другую вкладку: старт заводится не сходя со шторки, в которой пилот его
  // и не нашёл.
  expect(within(sheet).getByRole("button", { name: /Отметить новый на карте/ })).toBeInTheDocument()
})

// Клик по карте ставит Leaflet своим слушателем, вне реактовой очереди —
// без act() состояние шторки не доезжает до проверки (тот же приём, что в
// sheets/forms.test.tsx).
function tapMap(root: HTMLElement): void {
  const mapEl = root.querySelector(".pgbot-map")
  if (!mapEl) throw new Error("в шторке нет карты")
  act(() => {
    mapEl.dispatchEvent(new MouseEvent("click", { clientX: 10, clientY: 10, bubbles: true, cancelable: true }))
  })
}

// Весь путь «нужного старта в списке нет» целиком, как его проходит пилот:
// шапка → выбиралка → «Отметить новый на карте» → тап по карте → название →
// «Добавить старт». Заведённый старт СРАЗУ становится выбранным, и обе
// шторки закрываются: пилот открывал выбиралку, чтобы выбрать старт, и
// возвращать его в список значило бы попросить выбрать дважды.
//
// Этот же тест — единственная охрана связки onTap={pickOnMap} в шторке
// добавления: до задачи её удаление оставляло все 199 тестов зелёными.
test("старт, отмеченный на карте из выбиралки, сразу становится выбранным", async () => {
  const created = { ...sites[0]!, name: "Лалискури", lat: 42.51, lon: 42.32, elevation_m: 1874 }
  // Библиотека пополняется ответом сервера: выбор в шапке действует, только
  // пока старт есть в /api/sites (App.tsx: selectionAlive), и на застывшем
  // пустом списке имя нового старта в шапке не удержалось бы.
  const library: typeof sites = []
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    const path = String(url).split("?")[0]
    if (path === "/api/elevation") return Promise.resolve(json({ elevation_m: 1874 }))
    if (path === "/api/sites" && init?.method === "POST") {
      library.push(created)
      return Promise.resolve(json(created, 201))
    }
    const body = path === "/api/sites" ? library : path === "/api/prefs" ? prefs : {}
    return Promise.resolve(json(body))
  })

  render(<App />)
  const header = screen.getByRole("banner")
  await userEvent.click(await within(header).findByRole("button", { name: "Старт не выбран" }))
  await userEvent.click(await screen.findByRole("button", { name: /Отметить новый на карте/ }))

  // Верхняя шторка стека — та, что легла последней: у всех Sheet один и тот
  // же aria-labelledby, поэтому по имени их не различить.
  const addSheet = screen.getAllByRole("dialog").at(-1)!
  tapMap(addSheet)
  // Координаты подставил тап, высоту спросил сервер — пилот их не набирал.
  expect(await within(addSheet).findByText("1874 м")).toBeInTheDocument()
  expect(within(addSheet).getByLabelText(/Широта/)).not.toHaveValue("")

  await userEvent.type(within(addSheet).getByLabelText(/Название/), "Лалискури")
  await userEvent.click(within(addSheet).getByRole("button", { name: "Добавить старт" }))

  // В шапке стоит имя нового старта — выбирать его отдельно не пришлось.
  expect(await within(header).findByText("Лалискури")).toBeInTheDocument()
  // И обе шторки закрыты: пилот вернулся к приложению, а не в список стартов.
  await waitFor(() => { expect(screen.queryAllByRole("dialog")).toHaveLength(0) })
})

// Ревью ветки (Important, воспроизведено): кнопка «Добавить старт» на время
// запроса заперта (AddSiteSheet: busy), но Escape, кнопка «назад» Telegram и
// тап по затемнению — нет, и шторки под ответом сервера может уже не быть.
// Ответ, пришедший после отмены, ставил свой старт поверх выбранного руками и
// снимал со стека ДВЕ шторки — те, которые пилот открыл уже после отмены.
// Проверяется на настоящем дереве: и подмена выбора, и снятие чужой шторки
// видны только там, где есть и шапка, и стек.
test("ответ на отменённое добавление старта не перебивает выбор пилота и не закрывает чужие шторки", async () => {
  const created = { ...sites[0]!, name: "Лалискури", lat: 42.51, lon: 42.32, elevation_m: 1874 }
  // Ответ на POST придёт по команде теста — ровно в тот момент, когда шторки,
  // отправившей запрос, уже нет.
  let finishCreate = (): void => {}
  let createAsked = false
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    const path = String(url).split("?")[0]
    if (path === "/api/elevation") return Promise.resolve(json({ elevation_m: 1874 }))
    if (path === "/api/sites" && init?.method === "POST") {
      createAsked = true
      return new Promise<Response>((resolve) => { finishCreate = () => { resolve(json(created, 201)) } })
    }
    const body = path === "/api/sites" ? sites : path === "/api/prefs" ? prefs : {}
    return Promise.resolve(json(body))
  })

  render(<App />)
  const header = screen.getByRole("banner")
  await userEvent.click(await within(header).findByRole("button", { name: "Старт не выбран" }))
  await userEvent.click(await screen.findByRole("button", { name: /Отметить новый на карте/ }))
  const addSheet = screen.getAllByRole("dialog").at(-1)!
  tapMap(addSheet)
  await within(addSheet).findByText("1874 м")
  await userEvent.type(within(addSheet).getByLabelText(/Название/), "Лалискури")
  await userEvent.click(within(addSheet).getByRole("button", { name: "Добавить старт" }))
  expect(createAsked).toBe(true)

  // Пилот передумал ждать: Escape снимает шторку добавления, а в выбиралке под
  // ней он выбирает старт руками — этот выбор и есть его последнее слово.
  await userEvent.keyboard("{Escape}")
  await userEvent.click(await screen.findByRole("button", { name: /Гудаури/ }))
  expect(within(header).getByText("Гудаури")).toBeInTheDocument()
  // И открывает выбор дня — чужую шторку, до которой позднему ответу дела нет.
  await userEvent.click(within(header).getByRole("button", { name: "День не выбран" }))
  expect(screen.getAllByRole("dialog")).toHaveLength(1)

  await act(async () => {
    finishCreate()
    await new Promise((resolve) => { setTimeout(resolve, 20) })
  })

  expect(within(header).getByText("Гудаури")).toBeInTheDocument()
  expect(screen.getAllByRole("dialog")).toHaveLength(1)
})

// Ревью ветки (Important, воспроизведено): «заведённый старт сразу становится
// выбранным» держалось на перезапросе /api/sites — выбор действует, только
// пока имя есть в загруженном списке (App.tsx: selectionAlive), а список
// перезапрашивался уже после ответа POST. Пока перезапрос летел, шапка писала
// «Старт не выбран»; при отказе перезапроса (useSites: retry: false) выбор не
// появлялся вовсе, и объяснить это было негде — обе шторки уже закрыты.
// Отказ здесь — не экзотика, а самый жёсткий способ поймать зависимость от
// перезапроса: подделки остальных тестов отвечают мгновенно и успешно.
test("заведённый старт остаётся выбранным, даже если перезапрос списка отказал", async () => {
  const created = { ...sites[0]!, name: "Лалискури", lat: 42.51, lon: 42.32, elevation_m: 1874 }
  let listAsked = 0
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    const path = String(url).split("?")[0]
    if (path === "/api/elevation") return Promise.resolve(json({ elevation_m: 1874 }))
    if (path === "/api/sites" && init?.method === "POST") return Promise.resolve(json(created, 201))
    if (path === "/api/sites") {
      listAsked += 1
      // Библиотека пуста, а перезапрос после заведения отказывает: связь могла
      // отвалиться ровно в эту секунду, и старт от этого не перестал быть
      // заведённым — сервер ответил на POST 201.
      return Promise.resolve(listAsked === 1 ? json([]) : json({ detail: "нет связи" }, 500))
    }
    return Promise.resolve(json(path === "/api/prefs" ? prefs : {}))
  })

  render(<App />)
  const header = screen.getByRole("banner")
  await userEvent.click(await within(header).findByRole("button", { name: "Старт не выбран" }))
  await userEvent.click(await screen.findByRole("button", { name: /Отметить новый на карте/ }))
  const addSheet = screen.getAllByRole("dialog").at(-1)!
  tapMap(addSheet)
  await within(addSheet).findByText("1874 м")
  await userEvent.type(within(addSheet).getByLabelText(/Название/), "Лалискури")
  await userEvent.click(within(addSheet).getByRole("button", { name: "Добавить старт" }))

  expect(await within(header).findByText("Лалискури")).toBeInTheDocument()
  // Перезапрос ушёл и отказал — а имя в шапке от этого не пропало.
  await waitFor(() => { expect(listAsked).toBeGreaterThan(1) })
  await new Promise((resolve) => { setTimeout(resolve, 30) })
  expect(within(header).getByText("Лалискури")).toBeInTheDocument()
  // И экран считает старт выбранным по-настоящему: не хватает только дня.
  expect(screen.getByText("Выберите день")).toBeInTheDocument()
})

// Просьба владельца (бриф explicit-site-and-day): приложение открывалось
// готовым прогнозом какого-то старта на сегодня — старт брался первым из
// /api/sites, день подставлялся сам. Теперь ни один тяжёлый запрос не уходит,
// пока пилот не назвал ОБА. Проверяются оба гвоздя по отдельности: подписи в
// шапке ловят возврат предвыбора (любого из двух), а половина выбора ловит
// «хватит и старта».
test("на холодном старте прогноз не считается, пока не выбраны старт и день", async () => {
  const fetchMock = vi.fn((url: string) => {
    const path = String(url).split("?")[0]
    const body =
      path === "/api/sites" ? sites
      : path === "/api/prefs" ? prefs
      : path === "/api/forecast" && url.includes("range=1d") ? facts
      : path === "/api/forecast" ? overview
      : {}
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200, headers: { "content-type": "application/json" } }))
  })
  vi.stubGlobal("fetch", fetchMock)

  render(<App />)
  const header = screen.getByRole("banner")
  // Ждём не паузы, а признака полной готовности: подпись модели появляется
  // только после ответа /api/prefs, то есть и старты, и настройки уже
  // применены — будь у приложения предвыбор, запрос ушёл бы к этой минуте
  // (условие screenActive перестало держать его ещё раньше).
  await within(header).findByText(/ECMWF/)

  const forecasts = (): string[] => fetchMock.mock.calls
    .map(([u]) => String(u)).filter((u) => u.startsWith("/api/forecast"))
  expect(forecasts()).toHaveLength(0)
  expect(within(header).getByText("Старт не выбран")).toBeInTheDocument()
  expect(within(header).getByText("День не выбран")).toBeInTheDocument()
  // Экран не молчит и не крутит спиннер, а называет оба недостающих выбора.
  expect(screen.getByText("Выберите старт и день")).toBeInTheDocument()

  // Половина выбора — ещё не выбор: старт назван, дня нет, в сеть по-прежнему
  // никто не ходит, и экран говорит, чего именно не хватает теперь.
  await pickSite("Гудаури")
  await new Promise((resolve) => { setTimeout(resolve, 30) })
  expect(forecasts()).toHaveLength(0)
  expect(screen.getByText("Выберите день")).toBeInTheDocument()
})

// Вторая половина того же правила: сделанный выбор обязан доехать до запроса
// и до вердикта. Старт берётся НЕ первый и день НЕ сегодняшний — выбор по
// номеру в списке (а не по имени и дате) на первых элементах неотличим от
// правильного, ровно этот класс дефекта был Critical задачи 10.
test("выбор старта и дня в шапке доводит прогноз до вердикта", async () => {
  const threeSites = [
    sites[0]!,
    { ...sites[0]!, name: "Лалискури", lat: 42.51, lon: 42.32 },
    { ...sites[0]!, name: "Казбеги", lat: 42.66, lon: 44.64 },
  ]
  const fetchMock = vi.fn((url: string) => {
    const path = String(url).split("?")[0]
    const body =
      path === "/api/sites" ? threeSites
      : path === "/api/prefs" ? prefs
      : path === "/api/forecast" && url.includes("range=1d") ? facts
      : path === "/api/forecast" ? overview
      : {}
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200, headers: { "content-type": "application/json" } }))
  })
  vi.stubGlobal("fetch", fetchMock)

  render(<App />)
  await pickSite("Казбеги")
  const picked = await pickDay(2)

  expect(await screen.findByText(facts.assessment.label_ru)).toBeInTheDocument()
  await waitFor(() => {
    const asked = fetchMock.mock.calls
      .map(([u]) => new URL(String(u), "http://x").searchParams)
      .filter((p) => p.get("range") === "1d")
      .map((p) => `${p.get("site")} · ${p.get("date")}`)
    // Ровно один запрос и ровно за тем, что выбрали: ни старт первого в
    // списке, ни сегодняшний день сюда попасть не должны.
    expect(asked).toEqual([`Казбеги · ${picked}`])
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
  await pickSite("Гудаури")
  await pickDay(0)
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
  // Старт и период — руками: «Обзор» без них ничего не считает (Overview.tsx:
  // NeedsChoice), а тап по дню проверяется на посчитанном списке.
  await pickSite("Гудаури")
  await userEvent.click(screen.getByRole("tab", { name: "Обзор" }))
  await userEvent.click(screen.getByRole("button", { name: "3 дня" }))
  const target = overview.days_daytime[2]!
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(fmtDate(target.date)) }))

  expect(screen.getByRole("tab", { name: "Прогноз" })).toHaveAttribute("aria-selected", "true")
  await waitFor(() => {
    const calls = fetchMock.mock.calls.map(([u]) => String(u))
    expect(calls.some((u) => u.includes("range=1d") && u.includes(`date=${target.date}`))).toBe(true)
  })
})

// Ревью (Critical, воспроизведено): у пилота уже сейчас может быть НЕСКОЛЬКО
// сохранённых стартов — /api/scan существует именно затем, чтобы агрегировать
// лётные дни по всем сразу, не дожидаясь выбиралки старта (задача 13). Тап по
// дню второго старта в скане обязан открыть прогноз ВТОРОГО старта, а не
// первого из /api/sites: до правки App.tsx всегда брал site = первый элемент
// списка (запасной старт из sites.ts), а Overview.tsx звал onOpenDay(date) без
// имени старта — контекст "какой старт нажали" терялся, и «Прогноз» после
// тапа тихо показывал первый старт с датой второго, не подавая виду, что это
// не тот старт. Явная проверка на настоящем сетевом запросе и на шапке —
// шапка обязана показать имя того старта, чей прогноз реально открылся.
test("тап по дню ВТОРОГО старта в скане открывает прогноз именно этого старта, а не первого", async () => {
  const kazbegiDate = "2026-08-05"
  const twoSites = [sites[0]!, { ...sites[0]!, name: "Казбеги" }]
  const scanTwoSites = {
    sites: [
      scan.sites[0]!,
      { name: "Казбеги", aspect_deg: scan.sites[0]!.aspect_deg, days: [{ ...scan.sites[0]!.days[0]!, date: kazbegiDate }] },
    ],
    empty: [],
    failed: [],
  }
  const fetchMock = vi.fn((url: string) => {
    const path = url.split("?")[0]
    const body =
      path === "/api/sites" ? twoSites
      : path === "/api/prefs" ? prefs
      : path === "/api/scan" ? scanTwoSites
      : path === "/api/forecast" && url.includes("range=1d") ? facts
      : path === "/api/forecast" ? overview
      : {}
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }))
  })
  vi.stubGlobal("fetch", fetchMock)

  render(<App />)
  await userEvent.click(screen.getByRole("tab", { name: "Обзор" }))
  await userEvent.click(screen.getByRole("button", { name: "Все старты" }))
  const kazbegiGroup = await screen.findByRole("group", { name: "Казбеги" })
  await userEvent.click(within(kazbegiGroup).getByRole("button"))

  expect(screen.getByRole("tab", { name: "Прогноз" })).toHaveAttribute("aria-selected", "true")
  await waitFor(() => {
    // Ищем запрос ИМЕННО за днём, по которому кликнули (date=kazbegiDate), а
    // не любой запрос с range=1d: проверяется, что тап донёс до «Прогноза»
    // старт И дату СВОЕЙ строки, а не какие-нибудь ещё.
    const requestsForClickedDay = fetchMock.mock.calls
      .map(([u]) => new URL(String(u), "http://x").searchParams)
      .filter((params) => params.get("range") === "1d" && params.get("date") === kazbegiDate)
      .map((params) => params.get("site"))
    expect(requestsForClickedDay).toEqual(["Казбеги"])
  })
  const header = screen.getByRole("banner")
  expect(within(header).getByText("Казбеги")).toBeInTheDocument()
})

// Задача 13: точки маршрута живут в оболочке, а не в экране «Маршрут» —
// иначе выбранный маршрут пропадал бы при переключении вкладки. Путь целиком
// (кнопка на вкладке → шторка сохранённых → выбор → расчёт) не покрыт ни
// тестами шторок (они проверяют только колбэк), ни тестами экрана (он
// получает точки пропом). Маршрут берётся НЕ первый: подмена «всегда первый»
// на первом элементе неотличима (разбор задачи 12).
test("сохранённый маршрут, выбранный в шторке, уходит в расчёт маршрута", async () => {
  const saved = [
    { name: "Гудаури — Коби", points: [[42.47, 44.48, "старт"], [42.53, 44.51, "Коби"]], saved: "2026-07-25T06:33:49+00:00" },
    { name: "Хребет на север", points: [[42.4, 44.4, null], [42.6, 44.4, null], [42.8, 44.4, "разворот"]], saved: "2026-07-26T06:33:49+00:00" },
  ]
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const path = String(url).split("?")[0]
    const body =
      path === "/api/sites" ? sites
      : path === "/api/prefs" ? prefs
      : path === "/api/routes" ? saved
      : path === "/api/route" ? routeResult
      : path === "/api/forecast" && url.includes("range=1d") ? facts
      : path === "/api/forecast" ? overview
      : {}
    void init
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200, headers: { "content-type": "application/json" } }))
  })
  vi.stubGlobal("fetch", fetchMock)

  render(<App />)
  // День выбирается явно — маршруту он нужен так же, как прогнозу
  // (api.py:RouteIn.date), и сам экран его больше не подставляет.
  await pickDay(0)
  await userEvent.click(screen.getByRole("tab", { name: "Маршрут" }))
  await userEvent.click(screen.getByRole("button", { name: /Сохранённые/ }))
  await userEvent.click(await screen.findByRole("button", { name: /Хребет на север/ }))

  // Шторка закрылась сама — выбор сделан, держать её открытой не за чем.
  expect(screen.queryByRole("dialog")).toBeNull()

  await waitFor(() => {
    const posts = fetchMock.mock.calls.filter(([u, init]) =>
      String(u).split("?")[0] === "/api/route" && (init as RequestInit | undefined)?.method === "POST")
    expect(posts).toHaveLength(1)
    const sent = JSON.parse(String((posts[0]![1] as RequestInit).body)) as { points: unknown; name: unknown }
    expect(sent.points).toEqual(saved[1]!.points)
    expect(sent.name).toBe("Хребет на север")
  })
})

// Задача 13: имя старта в шапке — кнопка, открывающая выбиралку. Проверка на
// ТРЁХ стартах и НЕ на первом: выбор по индексу списка (а не по имени) даёт
// ровно тот Critical, что нашли в задаче 10 — приложение показывает один
// старт, а считает другой. Тест шторки этого не ловит: он проверяет только
// колбэк, а не то, что оболочка на него отреагировала.
test("выбор старта в шапке переключает прогноз на этот старт", async () => {
  const threeSites = [
    sites[0]!,
    { ...sites[0]!, name: "Лалискури", lat: 42.51, lon: 42.32 },
    { ...sites[0]!, name: "Казбеги", lat: 42.66, lon: 44.64 },
  ]
  const fetchMock = vi.fn((url: string) => {
    const path = String(url).split("?")[0]
    const body =
      path === "/api/sites" ? threeSites
      : path === "/api/prefs" ? prefs
      : path === "/api/forecast" && url.includes("range=1d") ? facts
      : path === "/api/forecast" ? overview
      : {}
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200, headers: { "content-type": "application/json" } }))
  })
  vi.stubGlobal("fetch", fetchMock)

  render(<App />)
  const header = screen.getByRole("banner")
  await pickSite("Казбеги")
  // День нужен тоже — без него прогноз не считается вовсе (бриф
  // explicit-site-and-day); сегодняшний берётся как самый обычный выбор
  // пилота, проверяется здесь СТАРТ.
  await pickDay(0)

  expect(within(header).getByText("Казбеги")).toBeInTheDocument()
  await waitFor(() => {
    const requested = fetchMock.mock.calls
      .map(([u]) => new URL(String(u), "http://x").searchParams)
      .filter((p) => p.get("range") === "1d")
      .map((p) => p.get("site"))
    expect(requested).toContain("Казбеги")
  })
})

// Ревью задачи 13 (N5): удаление старта инвалидирует список, но выбор пилота
// оставался строкой удалённого старта — шапка показывала призрак, а вкладка
// «Прогноз» отдавала его прогноз из кэша (staleTime 5 минут); на холодном
// кэше — 404 от api._site_or_404. Удаляется НЕ первый старт и НЕ тот, что
// выбран по умолчанию: подмена «сбрасывать всегда» и «сбрасывать первый»
// на таком наборе видна.
test("удалённый старт перестаёт быть текущим", async () => {
  let sitesNow = [
    sites[0]!,
    { ...sites[0]!, name: "Лалискури", lat: 42.51, lon: 42.32 },
    { ...sites[0]!, name: "Казбеги", lat: 42.66, lon: 44.64 },
  ]
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    const path = String(url).split("?")[0]!
    if (init?.method === "DELETE") {
      const removed = decodeURIComponent(path.slice("/api/sites/".length))
      sitesNow = sitesNow.filter((s) => s.name !== removed)
      return Promise.resolve(new Response(null, { status: 204 }))
    }
    const body =
      path === "/api/sites" ? sitesNow
      : path === "/api/prefs" ? prefs
      : path === "/api/forecast" && url.includes("range=1d") ? facts
      : path === "/api/forecast" ? overview
      : {}
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200, headers: { "content-type": "application/json" } }))
  })

  render(<App />)
  const header = screen.getByRole("banner")

  // Пилот выбрал «Казбеги» в шапке...
  await pickSite("Казбеги")
  expect(within(header).getByText("Казбеги")).toBeInTheDocument()

  // ...и удалил его же на вкладке «Настройки».
  await userEvent.click(screen.getByRole("tab", { name: "Настройки" }))
  await userEvent.click(await screen.findByRole("button", { name: /Казбеги 42,660/ }))
  const sheet = screen.getByRole("dialog")
  await userEvent.click(within(sheet).getByRole("button", { name: /Удалить старт/ }))
  await userEvent.click(within(sheet).getByRole("button", { name: /Да, удалить/ }))

  // Шапка возвращается к «старт не выбран», а не показывает удалённый:
  // запасного старта в приложении больше нет, и подставить вместо удалённого
  // соседний значило бы выбрать за пилота.
  await waitFor(() => {
    expect(within(header).queryByText("Казбеги")).toBeNull()
  })
  expect(within(header).getByText("Старт не выбран")).toBeInTheDocument()
})

// Финальное ревью ветки, I3. Все четыре экрана смонтированы разом (на этом
// держится отложенная подгонка карты, map/MapView.tsx), и скрытые ходили в
// сеть наравне с показанным: сервер держит ОДИН тяжёлый запрос на пилота
// (api.py:one_at_a_time), и запрос скрытого «Обзора» занимал слот раньше
// того экрана, на который пилот смотрит. Замерено ревьюером: один тап по
// чипу модели на «Маршруте» отправлял три тяжёлых запроса, собственный
// запрос пилота уходил третьим.
test("скрытые вкладки не ходят в сеть, а открытая — ходит", async () => {
  const fetchMock = vi.fn((url: string) => {
    const path = String(url).split("?")[0]
    const body =
      path === "/api/sites" ? sites
      : path === "/api/prefs" ? prefs
      : path === "/api/forecast" && url.includes("range=1d") ? facts
      : path === "/api/forecast" ? overview
      : path === "/api/scan" ? scan
      : {}
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }))
  })
  vi.stubGlobal("fetch", fetchMock)

  render(<App />)
  await pickSite("Гудаури")
  await pickDay(0)
  await screen.findByText(facts.assessment.label_ru)

  const heavy = (): string[] => fetchMock.mock.calls
    .map(([u]) => String(u))
    .filter((u) => u.startsWith("/api/forecast") || u.startsWith("/api/scan"))
  // Пилот стоит на «Прогнозе» — в сеть ушёл ровно его запрос.
  expect(heavy().filter((u) => u.includes("range=3d"))).toHaveLength(0)
  expect(heavy().filter((u) => u.includes("range=1d"))).toHaveLength(1)

  // Открыл «Обзор» и выбрал период — теперь его запрос законен.
  await userEvent.click(screen.getByRole("tab", { name: "Обзор" }))
  await userEvent.click(screen.getByRole("button", { name: "3 дня" }))
  await waitFor(() => {
    expect(heavy().filter((u) => u.includes("range=3d"))).toHaveLength(1)
  })
})

// Финальное ревью ветки, I4. /api/sites и /api/prefs идут параллельно, и
// порядок ответов ничем не задан. Пришли старты первыми — старт уже есть, а
// модель ещё нет: запрос уходил без model=, а когда настройки приезжали,
// модель попадала в ключ кэша, и ТОТ ЖЕ прогноз считался второй раз —
// показанный вердикт пропадал обратно в спиннер (замерено: показан на 79 мс,
// исчез на 332 мс). Здесь порядок задан явно: настройки отвечают по команде,
// уже после стартов.
test("на холодном старте прогноз считается один раз, а не дважды", async () => {
  let deliverPrefs = (): void => { throw new Error("настройки не запрашивались") }
  const pendingPrefs = new Promise<Response>((resolve) => {
    deliverPrefs = () => {
      resolve(new Response(JSON.stringify(prefs), { status: 200, headers: { "content-type": "application/json" } }))
    }
  })
  const fetchMock = vi.fn((url: string) => {
    const path = String(url).split("?")[0]
    if (path === "/api/prefs") return pendingPrefs
    const body =
      path === "/api/sites" ? sites
      : path === "/api/forecast" && url.includes("range=1d") ? facts
      : path === "/api/forecast" ? overview
      : {}
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }))
  })
  vi.stubGlobal("fetch", fetchMock)

  render(<App />)
  const forecasts = (): string[] => fetchMock.mock.calls
    .map(([u]) => String(u)).filter((u) => u.startsWith("/api/forecast"))

  // Выбор старта и дня — руками, и он же служит ожиданием: строку старта
  // шторка показывает только по ПРИШЕДШЕМУ /api/sites, то есть к этому месту
  // список не просто запрошен, а применён. По одному лишь вызову fetch
  // проверка была бы пустой — ответы стартов и настроек прикладываются одним
  // пакетом, и гонка, ради которой написан тест, не воспроизводится вовсе
  // (проверено мутацией: она оставалась зелёной).
  await pickSite("Гудаури")
  await pickDay(0)

  // Выбор сделан целиком, настройки — ещё в пути. Запрос без model= не
  // уходит: сервер посчитал бы его по сохранённой настройке, и тот же ответ
  // пришлось бы считать заново под другим ключом кэша.
  expect(forecasts()).toHaveLength(0)

  deliverPrefs()
  await screen.findByText(facts.assessment.label_ru)
  await new Promise((resolve) => { setTimeout(resolve, 30) })

  expect(forecasts()).toHaveLength(1)
  expect(forecasts()[0]).toContain("model=ecmwf")
})

// То же правило, но для второй вкладки. Условие «ждём ответа /api/prefs»
// живёт одной строкой на все четыре экрана (App.screenActive), а проверялось
// только через «Прогноз»: снятие условия для «Обзора» оставляло весь пакет
// зелёным (проверка второго круга финального ревью, N6). Считается запрос
// диапазона (range=3d) — именно его шлёт «Обзор»; /api/scan уходит только в
// режиме «Все старты», куда пилот на холодном старте ещё не заходил.
test("на холодном старте обзор считается один раз, а не дважды", async () => {
  let deliverPrefs = (): void => { throw new Error("настройки не запрашивались") }
  const pendingPrefs = new Promise<Response>((resolve) => {
    deliverPrefs = () => {
      resolve(new Response(JSON.stringify(prefs), { status: 200, headers: { "content-type": "application/json" } }))
    }
  })
  const fetchMock = vi.fn((url: string) => {
    const path = String(url).split("?")[0]
    if (path === "/api/prefs") return pendingPrefs
    const body =
      path === "/api/sites" ? sites
      : path === "/api/forecast" && String(url).includes("range=1d") ? facts
      : path === "/api/forecast" ? overview
      : {}
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }))
  })
  vi.stubGlobal("fetch", fetchMock)

  render(<App />)
  const ranges = (): string[] => fetchMock.mock.calls
    .map(([u]) => String(u)).filter((u) => u.startsWith("/api/forecast") && u.includes("range=3d"))

  await pickSite("Гудаури")
  await userEvent.click(screen.getByRole("tab", { name: "Обзор" }))
  await userEvent.click(screen.getByRole("button", { name: "3 дня" }))
  await new Promise((resolve) => { setTimeout(resolve, 30) })

  // Старт и период выбраны, настройки — ещё нет: запрос без model= не уходит.
  expect(ranges()).toHaveLength(0)

  deliverPrefs()
  await new Promise((resolve) => { setTimeout(resolve, 30) })

  expect(ranges()).toHaveLength(1)
  expect(ranges()[0]).toContain("model=ecmwf")
})

// Третья вкладка того же правила. У «Маршрута» оно наблюдается только через
// настоящий выбор сохранённого маршрута: без точек экран выходит рано и
// запроса не шлёт вовсе, поэтому снятие условия именно для него оставалось
// незамеченным дольше остальных (проверка второго круга финального ревью,
// N6). Расчёт маршрута — мутация в эффекте, а не запрос-подписка, и без
// условия он уходит ДВАЖДЫ: первый раз без настроек, второй — когда они
// приезжают и меняют зависимости эффекта. Оба похода занимают единственный
// слот пилота (api.py:one_at_a_time).
test("на холодном старте маршрут считается один раз, а не дважды", async () => {
  const saved = [
    { name: "Хребет на север", points: [[42.4, 44.4, null], [42.6, 44.4, null]], saved: "2026-07-26T06:33:49+00:00" },
  ]
  let deliverPrefs = (): void => { throw new Error("настройки не запрашивались") }
  const pendingPrefs = new Promise<Response>((resolve) => {
    deliverPrefs = () => {
      resolve(new Response(JSON.stringify(prefs), { status: 200, headers: { "content-type": "application/json" } }))
    }
  })
  const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
    const path = String(url).split("?")[0]
    if (path === "/api/prefs") return pendingPrefs
    const body =
      path === "/api/sites" ? sites
      : path === "/api/routes" ? saved
      : path === "/api/route" ? routeResult
      : path === "/api/forecast" && String(url).includes("range=1d") ? facts
      : path === "/api/forecast" ? overview
      : {}
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }))
  })
  vi.stubGlobal("fetch", fetchMock)

  render(<App />)
  const routePosts = (): unknown[] => fetchMock.mock.calls.filter(([u, init]) =>
    String(u).split("?")[0] === "/api/route" && (init as RequestInit | undefined)?.method === "POST")

  // День выбирается до всего: список дней локальный, ответа сервера не ждёт,
  // и тест должен упереться в ОТСУТСТВИЕ настроек, а не в невыбранный день.
  await pickDay(0)
  await userEvent.click(screen.getByRole("tab", { name: "Маршрут" }))
  await userEvent.click(screen.getByRole("button", { name: /Сохранённые/ }))
  await userEvent.click(await screen.findByRole("button", { name: /Хребет на север/ }))
  await new Promise((resolve) => { setTimeout(resolve, 30) })

  // Точки и день выбраны, настройки — ещё нет: расчёт не уходит.
  expect(routePosts()).toHaveLength(0)

  deliverPrefs()
  await waitFor(() => { expect(routePosts()).toHaveLength(1) })
  await new Promise((resolve) => { setTimeout(resolve, 30) })

  expect(routePosts()).toHaveLength(1)
})

// Оболочка не подставляет день и «Маршруту». Тест нужен отдельно от того, что
// стоит в Route.test.tsx: тот проверяет сам экран при date={null}, а здесь —
// что оболочка это null и передаёт, а не подменяет сегодняшним днём. Без него
// возврат подстановки в App.tsx проходил незамеченным: все остальные тесты
// выбирают день явно, и запасная ветка не исполняется ни разу.
test("маршрут, выбранный без дня, не считается", async () => {
  const saved = [
    { name: "Хребет на север", points: [[42.4, 44.4, null], [42.6, 44.4, null]], saved: "2026-07-26T06:33:49+00:00" },
  ]
  const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
    const path = String(url).split("?")[0]
    const body =
      path === "/api/sites" ? sites
      : path === "/api/prefs" ? prefs
      : path === "/api/routes" ? saved
      : path === "/api/route" ? routeResult
      : {}
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }))
  })
  vi.stubGlobal("fetch", fetchMock)

  render(<App />)
  await userEvent.click(screen.getByRole("tab", { name: "Маршрут" }))
  await userEvent.click(screen.getByRole("button", { name: /Сохранённые/ }))
  await userEvent.click(await screen.findByRole("button", { name: /Хребет на север/ }))
  await new Promise((resolve) => { setTimeout(resolve, 30) })

  const routePosts = fetchMock.mock.calls.filter(([u, init]) =>
    String(u).split("?")[0] === "/api/route" && (init as RequestInit | undefined)?.method === "POST")
  expect(routePosts).toHaveLength(0)
  expect(screen.getByText("Выберите день")).toBeInTheDocument()
})

// ───────────────────────────────── шаг по дням шевронами в шапке
//
// Выбранный день меняется не только шторкой: соседние дни — самое частое
// движение пилота («а завтра?»), и ради него открывать список из четырнадцати
// строк незачем. Шевроны шагают по тому же окну, которое показывает выбиралка
// (src/days.ts: forecastDays) — иначе пилот дошагал бы до дня, которого в
// списке нет.

const PREV_DAY = "Предыдущий день"
const NEXT_DAY = "Следующий день"

test("шеврон вперёд переводит на следующий день", async () => {
  render(<App />)
  const header = screen.getByRole("banner")
  await pickDay(3)

  await userEvent.click(within(header).getByRole("button", { name: NEXT_DAY }))

  expect(within(header).getByText(fmtDate(isoInDays(4)))).toBeInTheDocument()
})

test("шеврон назад переводит на предыдущий день", async () => {
  render(<App />)
  const header = screen.getByRole("banner")
  await pickDay(3)

  await userEvent.click(within(header).getByRole("button", { name: PREV_DAY }))

  expect(within(header).getByText(fmtDate(isoInDays(2)))).toBeInTheDocument()
})

// Границы окна — не «кнопка не сработает», а «кнопки нет»: за ними прогноза не
// существует вовсе (engine.build_url просит ровно forecast_days=RANGE_DAYS[rng]).
test("на сегодняшнем дне шеврона назад нет", async () => {
  render(<App />)
  const header = screen.getByRole("banner")
  await pickDay(0)

  expect(within(header).queryByRole("button", { name: PREV_DAY })).toBeNull()
  // Вперёд с сегодняшнего дня — есть куда: без этой половины тест был бы
  // зелёным и на шапке, потерявшей оба шеврона разом.
  expect(within(header).getByRole("button", { name: NEXT_DAY })).toBeInTheDocument()
})

test("на последнем дне окна шеврона вперёд нет", async () => {
  render(<App />)
  const header = screen.getByRole("banner")
  await pickDay(RANGE_DAYS_2WEEKS - 1)

  expect(within(header).queryByRole("button", { name: NEXT_DAY })).toBeNull()
  expect(within(header).getByRole("button", { name: PREV_DAY })).toBeInTheDocument()
})

// Пока день не выбран, шагать не от чего: шеврон в этом состоянии обещал бы
// движение по списку, в котором пилот ещё не стоит.
test("пока день не выбран, шевронов нет", () => {
  render(<App />)
  const header = screen.getByRole("banner")

  expect(within(header).queryByRole("button", { name: PREV_DAY })).toBeNull()
  expect(within(header).queryByRole("button", { name: NEXT_DAY })).toBeNull()
  expect(within(header).getByRole("button", { name: "День не выбран" })).toBeInTheDocument()
})

// Шаг шевроном — такой же выбор дня, как строка в шторке: прогноз обязан
// пересчитаться на новый день, а не остаться на прежнем.
test("шаг шевроном пересчитывает прогноз на новый день", async () => {
  const fetchMock = vi.fn((url: string) => {
    const path = String(url).split("?")[0]
    const body = path === "/api/sites" ? sites : path === "/api/prefs" ? prefs : facts
    return Promise.resolve(json(body))
  })
  vi.stubGlobal("fetch", fetchMock)
  render(<App />)
  await pickSite("Гудаури")
  await pickDay(0)
  await waitFor(() => { expect(dayForecastDates(fetchMock)).toContain(isoInDays(0)) })

  await userEvent.click(within(screen.getByRole("banner")).getByRole("button", { name: NEXT_DAY }))

  await waitFor(() => { expect(dayForecastDates(fetchMock)).toContain(isoInDays(1)) })
})

// Даты дневных запросов прогноза — только они меняются от шага по дням
// (диапазонному /api/forecast дата безразлична, см. шапку Overview.tsx).
function dayForecastDates(fetchMock: { mock: { calls: unknown[][] } }): (string | null)[] {
  return fetchMock.mock.calls
    .map((c) => new URL(String(c[0]), "http://localhost"))
    .filter((u) => u.pathname === "/api/forecast" && u.searchParams.get("range") === "1d")
    .map((u) => u.searchParams.get("date"))
}

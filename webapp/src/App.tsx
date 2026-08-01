// Оболочка приложения: шапка с контекстом (старт · дата · чип модели),
// четыре вкладки, стек шторок, тема Telegram. Сами экраны живут в
// screens/*, шторки — в sheets/*; здесь только состояние, общее для всех
// четырёх экранов: выбранный старт, дата, разовая модель и точки маршрута.
//
// К window.Telegram здесь и нигде в приложении не обращаются напрямую —
// только через telegram.ts (initData/colorScheme/themeVars/ready/onBack),
// это единственная защита от падения вне Telegram (см. telegram.ts).
import { createContext, useContext, useCallback, useEffect, useRef, useState } from "react"
import type { ReactNode } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { usePrefs, useSites } from "./api/queries"
import type { RoutePointRow } from "./api/queries"
import type { Prefs, Site } from "./api/types"
import { fmtDate } from "./format"
import { Forecast } from "./screens/Forecast"
import { Overview } from "./screens/Overview"
import { Route } from "./screens/Route"
import { Settings } from "./screens/Settings"
import { ModelPickerSheet } from "./sheets/ModelPickerSheet"
import { SitePickerSheet } from "./sheets/SitePickerSheet"
import * as telegram from "./telegram"
import { resolveThemeVars } from "./theme"
import { Chip } from "./ui/Chip"
import { Sheet } from "./ui/Sheet"
import { Spinner } from "./ui/Spinner"

// ────────────────────────────────────────────────────────────── шторки
// Стек шторок: push кладёт шторку сверху, pop снимает верхнюю. Живёт в
// App.tsx (здесь, в Shell) и раздаётся детям через SheetsContext — так у
// всех четырёх экранов один общий стек, а не свой у каждого.
type SheetEntry = { id: number; title: string; node: ReactNode }

type Sheets = {
  push: (node: ReactNode, title: string) => void
  pop: () => void
  stack: SheetEntry[]
}

const SheetsContext = createContext<Sheets | null>(null)

export function useSheetsContext(): Sheets {
  const value = useContext(SheetsContext)
  if (!value) throw new Error("useSheetsContext вызван вне SheetsContext.Provider")
  return value
}

function useSheets(): Sheets {
  const [stack, setStack] = useState<SheetEntry[]>([])
  const nextId = useRef(0)

  const push = useCallback((node: ReactNode, title: string) => {
    nextId.current += 1
    setStack((prev) => [...prev, { id: nextId.current, title, node }])
  }, [])

  const pop = useCallback(() => {
    setStack((prev) => prev.slice(0, -1))
  }, [])

  return { push, pop, stack }
}

// Провайдер стека шторок, отдельный от Shell: экранным тестам (например
// screens/Forecast.test.tsx) нужен настоящий стек с настоящим рендером
// <Sheet> (тест проверяет видимый заголовок открытой шторки), а не только
// заглушка контекста — SheetsProvider даёт это без всей оболочки (шапка,
// вкладки, тема Telegram), которая тестам экрана не нужна и потребовала бы
// лишних подделок. Shell использует этот же компонент в production-дереве
// (см. ниже), а не держит собственную копию — раскладка стека (шторки как
// сиблинги контента, а не поверх одной конкретной вкладки) не должна
// разойтись между тестовым и настоящим деревом.
export function SheetsProvider({ children }: { children: ReactNode }) {
  const sheets = useSheets()
  return (
    <SheetsContext.Provider value={sheets}>
      {children}
      {sheets.stack.map((entry) => (
        <Sheet key={entry.id} title={entry.title} onClose={sheets.pop}>
          {entry.node}
        </Sheet>
      ))}
    </SheetsContext.Provider>
  )
}

// ────────────────────────────────────────────────────────────── вкладки
type TabKey = "day" | "over" | "route" | "set"

// Иконки и подписи — дословно из миниapp/prototype.html:440-455.
const TABS: { key: TabKey; label: string; icon: ReactNode }[] = [
  {
    key: "day", label: "Прогноз",
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M2.5 9.5C6 5.5 18 5.5 21.5 9.5" />
        <path d="M2.5 9.5 12 20l9.5-10.5" />
        <path d="M12 20V9" />
      </svg>
    ),
  },
  {
    key: "over", label: "Обзор",
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 20V13" />
        <path d="M9 20V8" />
        <path d="M14 20v-5" />
        <path d="M19 20V4" />
      </svg>
    ),
  },
  {
    key: "route", label: "Маршрут",
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="6" cy="6" r="2.4" />
        <circle cx="18" cy="18" r="2.4" />
        <path d="M8.4 6H14a3.6 3.6 0 0 1 0 7.2H9a3.6 3.6 0 0 0 0 4.8h6.6" />
      </svg>
    ),
  },
  {
    key: "set", label: "Настройки",
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="3" />
        <path d="M12 2.8v2.4M12 18.8v2.4M21.2 12h-2.4M5.2 12H2.8M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7M18.5 18.5l-1.7-1.7M7.2 7.2 5.5 5.5" />
      </svg>
    ),
  },
]

// Вкладка «Маршрут» читает готовый список точек, а не создаёт его сама:
// точки приходят из шторок «Сохранённые маршруты» и «Новый маршрут» и
// хранятся здесь, в оболочке, — иначе выбранный маршрут пропадал бы при
// каждом переключении вкладки. Пустой массив — начальное состояние и
// константа МОДУЛЯ, а не литерал внутри JSX: Route.tsx перечитывает проп
// `points` в зависимостях своего эффекта и зовёт mutate() заново при смене
// ссылки — новый `[]` на каждый рендер Shell слал бы этот эффект вхолостую
// на каждый чужой ре-рендер (экран и так рано выходит по
// `points.length < 2`, но зачем создавать новую ссылку без нужды).
const NO_ROUTE_POINTS: RoutePointRow[] = []

// ────────────────────────────────────────────────────────────── шапка
// Возвращает null и когда список стартов ещё грузится, и когда он пуст —
// оба случая различает разметка ниже (sites.isPending), а не эта функция:
// ей самой достаточно знать только "есть ли имя старта".
// Экспортируется ради выбиралки старта (sheets/SitePickerSheet.tsx): отметку
// «текущий» она ставит по тому же правилу, по которому оболочка выбирает
// старт, — иначе при пустом selectedSite шторка не отметила бы ни одного
// старта, хотя приложение показывает первый.
export function siteName(sites: Site[] | undefined): string | null {
  return sites?.[0]?.name ?? null
}

// Подпись чипа модели — по ДЕЙСТВУЮЩЕЙ модели, а не по постоянной настройке:
// разовый выбор (чип в шапке) меняет модель всех запросов текущего сеанса, и
// чип обязан показывать именно её, иначе экран посчитан по одной модели, а
// подписан другой.
function modelLabel(prefs: Prefs | undefined, model: string | null): string | undefined {
  if (!prefs) return undefined
  const key = model ?? prefs.model_key
  // Ключ модели как запасная подпись — на случай разовой модели, которой нет
  // в списке (список приходит из engine.MODELS вместе с настройками, и
  // разойтись они могут только при обновлении сервера между двумя запросами).
  // Страховки `?.` на самом models здесь больше нет: она стояла ради подделки
  // "{}" в тестах оболочки, а те теперь отвечают по контракту эндпоинта —
  // экран настроек читает models без неё и на "{}" всё равно упал бы.
  return prefs.models.find((m) => m.key === key)?.label ?? key
}

function todayIso(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, "0")
  const day = String(now.getDate()).padStart(2, "0")
  return `${now.getFullYear()}-${month}-${day}`
}

const queryClient = new QueryClient()

// Сброс для тестов — тот же класс проблемы, что и resetQueueForTests()
// в api/queue.ts (см. комментарий там): queryClient здесь — процессный
// синглтон на весь модуль, общий для КАЖДОГО render(<App />) в тестах
// одного файла. Кэш живёт 5 минут (STALE_TIME_MS, api/queries.ts) — без
// сброса второй и последующие тесты в App.test.tsx читают ["sites"]/
// ["prefs"]/["forecast", ...] из КЭША первого теста, а не из собственного
// vi.stubGlobal("fetch", ...) конкретного теста. Найдено на тесте про
// <StrictMode> (task-9 review): он первым в файле требует настоящих данных
// facts из своей фикстуры, а не только структурных подписей вкладок — и
// без сброса получал ["sites"] от прогона предыдущего теста ("шапка...
// пуст", sites: []), из-за чего site оставался null и экран так и не
// доходил до реального контента. Вызывается в test/setup.ts перед КАЖДЫМ
// тестом, а не только в App.test.tsx — по той же причине, по которой
// resetQueueForTests() зовётся глобально, а не точечно.
export function resetAppQueryClientForTests(): void {
  queryClient.clear()
}

function ShellContent() {
  const [tab, setTab] = useState<TabKey>("day")
  // Дата «Прогноза» — состояние, а не константа: экран «Обзор» (задача 10)
  // переключает на конкретный день по тапу, и это должно быть настоящим
  // переключением (см. task-10-brief), а не сбросом на сегодня при каждом
  // рендере. Начальное значение — todayIso(), как и раньше, пока пилот ни
  // разу не тапнул по дню в обзоре.
  const [date, setDate] = useState(todayIso())
  // Текущий старт — тоже состояние, а не всегда первый элемент /api/sites
  // (было так до ревью этой задачи, Critical: клик по дню ВТОРОГО старта в
  // скане «Все старты» открывал прогноз ПЕРВОГО — приложение никак не
  // запоминало, какой старт реально выбрали, siteName(sites.data) заново
  // брал sites.data[0] на каждом рендере). null означает "явного выбора
  // ещё не было" — тогда используется первый старт из списка (см. вычисление
  // site ниже). Это же состояние меняет выбиралка старта из шапки
  // (openSitePicker ниже) и переход «Смотреть прогноз» из карточки старта на
  // экране настроек — не только тап по дню в скане.
  const [selectedSite, setSelectedSite] = useState<string | null>(null)
  // Разовая модель: параметр ЗАПРОСА, а не настройка пилота (api.py:
  // _model_for — `model=` из query побеждает store.prefs и никуда не
  // сохраняется). Живёт в оболочке, потому что действует на все экраны
  // сеанса разом, и обнуляется при смене постоянной модели — иначе прежний
  // разовый выбор молча перебивал бы только что сохранённую настройку.
  const [onceModel, setOnceModel] = useState<string | null>(null)
  // Маршрут пилота: точки и имя, выбранные в шторках вкладки «Маршрут».
  const [routePoints, setRoutePoints] = useState<RoutePointRow[]>(NO_ROUTE_POINTS)
  const [routeName, setRouteName] = useState<string | null>(null)
  const sheets = useSheetsContext()
  const sites = useSites()
  const prefs = usePrefs()
  const bodyRef = useRef<HTMLElement>(null)

  // ready()/expand() — один раз при монтировании (App.tsx, задача 6).
  useEffect(() => {
    telegram.ready()
  }, [])

  // Переменные темы Telegram — на document.documentElement, чтобы
  // styles.css (var(--surface) и т.п.) их подхватил. resolveThemeVars
  // берёт схему (colorScheme() — есть всегда, даже без themeParams) и
  // накладывает присланные Telegram поля на ЦЕЛЬНУЮ палитру той же
  // схемы — недостающие поля не берутся из чужой (см. theme.ts, правка
  // ревью: было наоборот, каждая переменная бралась независимо и при
  // частичном themeParams получался тёмный фон со светлым текстом).
  useEffect(() => {
    const vars = resolveThemeVars(telegram.colorScheme(), telegram.themeVars())
    for (const [key, value] of Object.entries(vars)) {
      document.documentElement.style.setProperty(key, value)
    }
  }, [])

  // Кнопка «назад» Telegram: пока стек шторок не пуст — снимает верхнюю
  // шторку; когда стек опустел — обработчик СНИМАЕТСЯ (onBack(null)),
  // иначе кнопка осталась бы мёртвой, а Telegram не смог бы закрыть
  // приложение сам.
  useEffect(() => {
    if (sheets.stack.length === 0) {
      telegram.onBack(null)
      return
    }
    telegram.onBack(() => sheets.pop())
  }, [sheets.stack.length, sheets.pop])

  // Escape закрывает верхнюю шторку — как в макете (keydown, строка 1902).
  // Слушатель один, на уровне стека, а не внутри каждого Sheet: иначе при
  // нескольких открытых шторках одно нажатие закрыло бы их все разом.
  useEffect(() => {
    if (sheets.stack.length === 0) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") sheets.pop()
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [sheets.stack.length, sheets.pop])

  // Сброс прокрутки при смене вкладки — как $("#body").scrollTop = 0 в
  // switchTab (миниapp/prototype.html:1878).
  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = 0
  }, [tab])

  // Выбранный старт действует, только пока он есть в библиотеке. Удалили его
  // (здесь на вкладке «Настройки», в чате командой /delsite или с другого
  // устройства) — приложение возвращается к запасному варианту, а не показывает
  // призрак: запрос по исчезнувшему старту получает 404 (api.py:_site_or_404),
  // а пока в кэше TanStack лежит его прогноз (staleTime 5 минут) — пилот
  // смотрел бы прогноз старта, которого нет. Найдено ревью задачи 13 (N5).
  //
  // Проверка ТОЛЬКО по загруженному списку: пока sites.data не пришёл,
  // «старта нет в списке» ничего не значит, и сбрасывать выбор нельзя —
  // иначе холодный старт приложения терял бы выбор пилота на каждый
  // ре-рендер до ответа сервера.
  const selectionAlive =
    selectedSite !== null && (sites.data === undefined || sites.data.some((s) => s.name === selectedSite))
  const site = selectionAlive ? selectedSite : siteName(sites.data)
  const model = onceModel ?? prefs.data?.model_key ?? null

  // Тап по дню в «Обзоре» — настоящее переключение (старт и дата ИМЕННО
  // этого дня плюс переход на вкладку «Прогноз»), а не только смена вкладки:
  // задача 8 передавала в Forecast константный todayIso() и не менявшийся
  // первый старт; это заменяет оба на выбор пилота (task-10-brief, Critical
  // ревью — см. комментарий у selectedSite выше). Диапазонные строки
  // «Обзора» (3d/week/2weeks) зовут это с тем же site, что уже показан —
  // setSelectedSite там не меняет видимого старта, но держит переключение
  // однородным для обоих режимов Overview, а не разными колбэками.
  function openDay(dayOwnerSite: string, pickedDate: string): void {
    setSelectedSite(dayOwnerSite)
    setDate(pickedDate)
    setTab("day")
  }

  // Выбор старта — по имени: имя и есть ключ старта и в store, и в каждом
  // запросе (site=...). Индекс в списке не переживает ни перезагрузку
  // /api/sites, ни удаление соседнего старта (Critical задачи 10).
  function pickSite(name: string): void {
    setSelectedSite(name)
    sheets.pop()
  }

  // Данные шторкам НЕ передаются: sheets.push кладёт в стек готовый элемент,
  // и его пропы застывают на момент нажатия (SheetsProvider отдаёт тот же
  // объект элемента на каждом рендере). Шторка, открытая до ответа сервера,
  // так навсегда оставалась с пустым списком: пилот жал имя старта на холодном
  // старте и читал «Нет стартов», когда старты уже пришли (ревью задачи 13,
  // N2). Поэтому список стартов и настройки шторки читают сами — подпиской
  // на тот же кэш TanStack, что и оболочка.
  //
  // Через проп идёт только `selected` — сырой выбор пилота, а не вычисленный
  // `site`: измениться, пока шторка открыта, он не может (все три места, где
  // он меняется, эту шторку закрывают или живут на другом экране), а запасной
  // старт шторка выберет по тому же siteName() из живого списка.
  function openSitePicker(): void {
    sheets.push(<SitePickerSheet selected={selectedSite} onPick={pickSite} />, "Старт")
  }

  // Разовая модель применяется сразу и никуда не сохраняется; постоянную
  // сохраняет сама шторка (PATCH /api/prefs), и после этого разовый выбор
  // снимается — дальше действует новая настройка.
  function openModelPicker(): void {
    sheets.push(
      <ModelPickerSheet
        once={onceModel}
        onPickOnce={(key) => { setOnceModel(key); sheets.pop() }}
        onPickPermanent={() => { setOnceModel(null); sheets.pop() }}
      />,
      "Метеомодель",
    )
  }

  return (
    <div className="app">
      <header className="ctx">
        <div className="ctx__top">
          {/* Имя старта и чип модели — кнопки, как в макете (prototype.html:
              417-423, aria-haspopup="dialog"): это два самых частых действия
              пилота, и обоим нужен один тап из любого экрана. */}
          <button type="button" className="site" aria-haspopup="dialog" onClick={openSitePicker}>
            {/* Список стартов пуст (не идёт запрос — прогнав isPending) — понятный
                текст вместо спиннера, который никогда бы не пропал: пустой массив
                success-запроса не значит, что старт вот-вот появится. Шторка при
                этом всё равно открывается и отправляет за добавлением старта. */}
            <span className="site__name">{sites.isPending ? <Spinner /> : (site ?? "Нет стартов")}</span>
          </button>
          <Chip live onClick={openModelPicker}>
            {/* «· разово» отличает разовый выбор от постоянной настройки: без
                пометки пилот не отличит «сегодня смотрю по GFS» от «у меня
                теперь всегда GFS» (макет, prototype.html:423). */}
            {modelLabel(prefs.data, model) ?? <Spinner />}{onceModel !== null ? " · разово" : ""}
          </Chip>
        </div>
        <div className="ctx__date">
          <span className="dateline">{fmtDate(date)}</span>
        </div>
      </header>

      <main className="body" ref={bodyRef}>
        <section className="view" hidden={tab !== "day"} aria-label="Прогноз на день">
          <Forecast site={site} date={date} model={model} />
        </section>
        <section className="view" hidden={tab !== "over"} aria-label="Обзор">
          <Overview site={site} model={model} onOpenDay={openDay} />
        </section>
        <section className="view" hidden={tab !== "route"} aria-label="Маршрут">
          <Route
            points={routePoints}
            name={routeName}
            date={date}
            model={model}
            onPickRoute={(points, name) => { setRoutePoints(points); setRouteName(name); sheets.pop() }}
          />
        </section>
        <section className="view" hidden={tab !== "set"} aria-label="Настройки">
          <Settings
            currentSite={site}
            onceModel={onceModel}
            onPickOnce={(key) => { setOnceModel(key); sheets.pop() }}
            onPickPermanent={() => { setOnceModel(null); sheets.pop() }}
            onOpenSiteForecast={(name) => { setSelectedSite(name); setTab("day"); sheets.pop() }}
          />
        </section>
      </main>

      <div className="tabs" role="tablist" aria-label="Разделы">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key ? "true" : "false"}
            className="tab"
            onClick={() => setTab(t.key)}
          >
            {t.icon}
            <span>{t.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// Shell — обвязка ShellContent в SheetsProvider (см. выше): вынесена
// отдельно, чтобы ShellContent мог читать стек шторок через
// useSheetsContext(), а не заново создавать свой.
function Shell() {
  return (
    <SheetsProvider>
      <ShellContent />
    </SheetsProvider>
  )
}

export function App() {
  // Подпись пустая — приложение открыто не из Telegram: initData()
  // деградирует к "" вместо исключения (telegram.ts), здесь это условие
  // читается и превращается в понятный экран вместо пустоты/падения.
  if (telegram.initData() === "") {
    return (
      <div className="offline">
        <div className="empty">
          <b>Не Telegram</b>
          Откройте приложение из Telegram — вне него нельзя подтвердить, кто вы.
        </div>
      </div>
    )
  }

  return (
    <QueryClientProvider client={queryClient}>
      <Shell />
    </QueryClientProvider>
  )
}

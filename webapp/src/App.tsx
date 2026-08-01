// Оболочка приложения: шапка с контекстом (старт · дата · чип модели),
// четыре вкладки, стек шторок, тема Telegram. Сами экраны — заглушки,
// их наполняют задачи 8-13 (см. task-6-brief).
//
// К window.Telegram здесь и нигде в приложении не обращаются напрямую —
// только через telegram.ts (initData/colorScheme/themeVars/ready/onBack),
// это единственная защита от падения вне Telegram (см. telegram.ts).
import { createContext, useContext, useCallback, useEffect, useRef, useState } from "react"
import type { ReactNode } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { usePrefs, useSites } from "./api/queries"
import type { Prefs, Site } from "./api/types"
import { fmtDate } from "./format"
import * as telegram from "./telegram"
import { resolveThemeVars } from "./theme"
import { Chip } from "./ui/Chip"
import { Sheet } from "./ui/Sheet"
import { Spinner } from "./ui/Spinner"

// ────────────────────────────────────────────────────────────── шторки
// Стек шторок: push кладёт шторку сверху, pop снимает верхнюю. Живёт в
// App.tsx (здесь, в Shell) и раздаётся детям через SheetsContext — так у
// будущих экранов (задачи 8-13) есть один общий стек, а не свой у каждого.
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

// ────────────────────────────────────────────────────────────── шапка
function siteLabel(sites: Site[] | undefined): string | undefined {
  return sites?.[0]?.name
}

function modelLabel(prefs: Prefs | undefined): string | undefined {
  if (!prefs) return undefined
  // `?.` на models — не по типу (Prefs.models всегда массив), а по факту:
  // в тестах оболочки (App.test.tsx) fetch подделан пустым "{}", и без
  // страховки .find уронил бы рендер на любом неполном ответе.
  return prefs.models?.find((m) => m.key === prefs.model_key)?.label ?? prefs.model_key
}

function todayIso(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, "0")
  const day = String(now.getDate()).padStart(2, "0")
  return `${now.getFullYear()}-${month}-${day}`
}

const queryClient = new QueryClient()

function Shell() {
  const [tab, setTab] = useState<TabKey>("day")
  const sheets = useSheets()
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

  return (
    <SheetsContext.Provider value={sheets}>
      <div className="app">
        <header className="ctx">
          <div className="ctx__top">
            <span className="site">
              <span className="site__name">{siteLabel(sites.data) ?? <Spinner />}</span>
            </span>
            <Chip live>{modelLabel(prefs.data) ?? <Spinner />}</Chip>
          </div>
          <div className="ctx__date">
            <span className="dateline">{fmtDate(todayIso())}</span>
          </div>
        </header>

        <main className="body" ref={bodyRef}>
          <section className="view" hidden={tab !== "day"} aria-label="Прогноз на день">
            <p>Прогноз</p>
          </section>
          <section className="view" hidden={tab !== "over"} aria-label="Обзор">
            <p>Обзор</p>
          </section>
          <section className="view" hidden={tab !== "route"} aria-label="Маршрут">
            <p>Маршрут</p>
          </section>
          <section className="view" hidden={tab !== "set"} aria-label="Настройки">
            <p>Настройки</p>
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

        {sheets.stack.map((entry) => (
          <Sheet key={entry.id} title={entry.title} onClose={sheets.pop}>
            {entry.node}
          </Sheet>
        ))}
      </div>
    </SheetsContext.Provider>
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

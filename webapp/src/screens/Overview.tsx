// Экран «Обзор»: прогноз на несколько дней вперёд (сегменты 3d/week/2weeks,
// GET /api/forecast?range=...) и отдельный режим «Все старты»
// (GET /api/scan) — раскладка `renderOver` (miniapp/prototype.html:943-1014)
// и `renderScan` (miniapp/prototype.html:1015-1066).
//
// Два разных запроса за двумя разными формами ответа (см. комментарий у
// ForecastOverview/OverviewRow в api/types.ts — их легко перепутать):
// диапазонные сегменты идут через useForecast(site, range, ...) и
// ForecastOverview.days_daytime, «Все старты» — через useScan(model) и
// Scan.sites[].days (OverviewRow[]).
//
// `date` диапазонному /api/forecast безразличен: engine.build_url формирует
// URL для range≠"1d" через `forecast_days=RANGE_DAYS[rng]` и не читает date
// вовсе (engine.py:146-154) — диапазон всегда считается "от сегодня", а не
// от даты, выбранной ранее на экране прогноза. Поэтому сюда передаётся `null`
// независимо от того, какой день сейчас выбран в шапке приложения — иначе
// смена дня в «Прогнозе" молча меняла бы ключ кэша этого запроса, ничего не
// меняя в самом ответе сервера.
//
// Причина ограничения в строке дня вытесняет описание погоды — `.day__f`
// (miniapp/prototype.html:252-253) однострочный, с ellipsis, обе фразы не
// влезают, а причина полезнее пилоту: она говорит, что оценивать, а не
// просто "переменная облачность". Погода показывается только в лид-панели
// "Лучший день", у которой отдельная, более просторная строка
// (miniapp/prototype.html:972).
import { useState } from "react"
import type { ForecastRange } from "../api/queries"
import { useForecast, useScan } from "../api/queries"
import type { ForecastOverview, OverviewRow } from "../api/types"
import { colorOfCategory } from "../charts/palette"
import { compass, fmtDate, fmtNum } from "../format"
import { ErrorBox } from "../ui/ErrorBox"
import { Spinner } from "../ui/Spinner"

// onOpenDay несёт имя старта, а не только дату: в режиме «Все старты»
// строка дня принадлежит КОНКРЕТНОМУ старту группы (Scan.sites[i].name), а
// не тому "текущему" старту, чей прогноз показан на диапазонных сегментах
// (проп site ниже). Без имени старта в колбэке вызывающий код (App.tsx) не
// может понять, чей именно день нажали, и молча подставляет прежний
// текущий старт — это и было причиной Critical-находки ревью (тап по дню
// второго старта в скане открывал прогноз первого).
type OverviewProps = {
  site: string | null
  model: string | null
  onOpenDay: (site: string, date: string) => void
}

type RangeKey = Exclude<ForecastRange, "1d"> | "scan"

// Подписи и порядок — дословно из миниapp/prototype.html:948.
const RANGE_TABS: { key: RangeKey; label: string }[] = [
  { key: "3d", label: "3 дня" },
  { key: "week", label: "Неделя" },
  { key: "2weeks", label: "2 недели" },
  { key: "scan", label: "Все старты" },
]

function isNotFly(category: string): boolean {
  return category === "no_fly" || category === "danger"
}

function flyTag(category: string): string {
  return isNotFly(category) ? "не лётно" : "лётно"
}

type OverviewDay = ForecastOverview["days_daytime"][number]

// Причина ограничения важнее описания погоды (см. комментарий в шапке файла);
// описание погоды — запасной вариант ровно тогда, когда ограничивать нечего
// (assessment.limiting_factor_ru === null — Assessment.limiting_factor_ru
// того же значения, что и на экране "Прогноз", см. Forecast.tsx).
function overviewDayLine(day: OverviewDay): string {
  const reason = day.assessment.limiting_factor_ru ?? day.weather
  const precip = day.precip_mm > 0.2 ? ` · ${fmtNum(day.precip_mm, 1)} мм` : ""
  return `до ${fmtNum(day.wind_max_ms, 1)} порыв ${fmtNum(day.gust_max_ms, 1)} · ${day.wind_dir_window} · ${reason}${precip}`
}

// OverviewRow (форма строк /api/scan) не несёт готовую строку направления —
// в отличие от ForecastOverview.days_daytime[].wind_dir_window (уже
// "Ю (180°)"), здесь только сырые градусы (dom), поэтому compass() нужен
// именно тут, а не в overviewDayLine выше.
function scanRowLine(row: OverviewRow): string {
  const reason = row.limiting ?? row.label
  return `до ${fmtNum(row.wmax, 1)} порыв ${fmtNum(row.gmax, 1)} · ${compass(row.dom)} · ${reason}`
}

function bestOverviewDay(days: OverviewDay[]): OverviewDay {
  return days.reduce((best, day) => (
    (day.assessment.score ?? -Infinity) > (best.assessment.score ?? -Infinity) ? day : best
  ))
}

function NoSites() {
  return (
    <div className="empty">
      <b>Нет стартов</b>
      Добавьте старт, чтобы увидеть обзор.
    </div>
  )
}

function RangeView({ site, range, model, onOpenDay }: {
  site: string | null
  range: Exclude<RangeKey, "scan">
  model: string | null
  onOpenDay: (site: string, date: string) => void
}) {
  const forecast = useForecast(site, range, null, model)

  if (site === null) {
    return <NoSites />
  }
  // Отдельное имя (не "site") для узкого string ниже — строки дня зовут
  // onOpenDay(activeSite, day.date) этим именем, а не параметром site,
  // чтобы не полагаться на то, что сужение до string переживёт замыкание
  // внутри .map(): дешёвая подстраховка на месте, где однажды уже перепутали
  // "какой старт" с "какая дата" (Critical, ревью этой задачи).
  const activeSite = site
  if (forecast.isPending) {
    return <Spinner />
  }
  if (forecast.isError) {
    return <ErrorBox error={forecast.error} onRetry={() => { void forecast.refetch() }} />
  }

  const overview = forecast.data
  const days = overview.days_daytime

  // Сервер по контракту (engine.facts_overview) не отдаёт пустой
  // days_daytime на настоящий диапазон — по факту это не только гипотеза:
  // ревью этой же задачи поймало ровно такой пустой ответ ({days_daytime: []})
  // в одном из тестов App.test.tsx (упрощённая подделка fetch для теста не
  // про «Обзор»), и без этого guard'а bestOverviewDay ниже падал бы —
  // .reduce без начального значения на [] бросает исключение, а не просто
  // отдаёт "нет данных". Дешёвая защита, а падать экрану обзора не из-за
  // чего даже на "невозможном" по контракту вводе.
  if (days.length === 0) {
    return (
      <div className="empty">
        <b>Нет данных</b>
        Сервер не прислал ни одного дня для этого диапазона.
      </div>
    )
  }

  const best = bestOverviewDay(days)

  return (
    <>
      <div className="panel">
        <div className="panel__head">
          <span className="lbl">Лучший день</span>
          <span className="lbl">{overview.site.name} · {days.length} дн.</span>
        </div>
        <div className="verdict">
          <div>
            <div className="verdict__win">{fmtDate(best.date)}</div>
            <div className="verdict__sub">
              {best.weather} · до {fmtNum(best.wind_max_ms, 1)} м/с, порыв {fmtNum(best.gust_max_ms, 1)} · {best.wind_dir_window}
            </div>
          </div>
          <div className="verdict__score">
            <div className="verdict__num" style={{ color: colorOfCategory(best.assessment.category) }}>
              {best.assessment.score ?? "—"}
            </div>
            <div className="verdict__cat">{best.assessment.label_ru}</div>
          </div>
        </div>
      </div>

      <div className="days" role="group" aria-label="Дни диапазона">
        {days.map((day) => (
          <button key={day.date} type="button" className="day" onClick={() => onOpenDay(activeSite, day.date)}>
            <div className="day__d">{fmtDate(day.date)}</div>
            <div className="day__m">
              <div
                className="day__bar"
                style={{ background: colorOfCategory(day.assessment.category), width: `${Math.max(6, day.assessment.score ?? 0)}%` }}
              />
              <div className="day__f">{overviewDayLine(day)}</div>
            </div>
            <div className="day__s" style={{ color: colorOfCategory(day.assessment.category) }}>
              {day.assessment.score ?? "—"}
              <small>{flyTag(day.assessment.category)}</small>
            </div>
          </button>
        ))}
      </div>
      <div className="attrib">Тап по дню открывает подробный прогноз — экран перерисуется, ничего не добавится в историю</div>
    </>
  )
}

function ScanView({ model, onOpenDay }: { model: string | null; onOpenDay: (site: string, date: string) => void }) {
  const scan = useScan(model)

  if (scan.isPending) {
    return <Spinner />
  }
  if (scan.isError) {
    return <ErrorBox error={scan.error} onRetry={() => { void scan.refetch() }} />
  }

  const data = scan.data

  return (
    <>
      {/* key={s.name}/aria-label={s.name} по имени старта, не по индексу:
          тот же приём, что и в useDeleteSite(name) (api/queries.ts) — имя
          старта уже принято уникальным идентификатором в остальном
          приложении (это же имя приходит в /api/sites и используется как
          ключ операций над стартом), а не заводится здесь заново. Риск
          низкий и не новый для этого экрана. */}
      {data.sites.map((s) => (
        <div key={s.name} className="sitegrp">
          <div className="sitegrp__h">
            <b>{s.name}</b>
            {/* Scan.sites[].aspect_deg — ГРАДУСЫ (forecast.py:91), а пилот
                читает румб: в чате тот же скан печатает «🪂 Гудаури (Ю)»
                (bot.py:244, engine.card). Печать значения как есть давала
                «180 · 2 лётных» — финальное ревью ветки, C1б. */}
            <span className="lbl">{s.aspect_deg === null ? "—" : compass(s.aspect_deg)} · {s.days.length} лётных</span>
          </div>
          <div className="days" role="group" aria-label={s.name}>
            {s.days.map((row) => (
              <button key={row.date} type="button" className="day" onClick={() => onOpenDay(s.name, row.date)}>
                <div className="day__d">{fmtDate(row.date)}</div>
                <div className="day__m">
                  <div className="day__bar" style={{ background: colorOfCategory(row.category), width: `${Math.max(6, row.score)}%` }} />
                  <div className="day__f">{scanRowLine(row)}</div>
                </div>
                <div className="day__s" style={{ color: colorOfCategory(row.category) }}>{row.score}</div>
              </button>
            ))}
          </div>
        </div>
      ))}

      {data.empty.length > 0 && (
        <div className="empty">
          <b>Без лётных дней</b>
          {data.empty.join(", ")} — на неделе ни одного окна ≥ удовлетворительного.
        </div>
      )}
      {data.failed.length > 0 && (
        <div className="empty">
          <b>Не удалось получить</b>
          {data.failed.join(", ")}. Открой старт вручную, чтобы повторить запрос.
        </div>
      )}
    </>
  )
}

export function Overview({ site, model, onOpenDay }: OverviewProps) {
  const [range, setRange] = useState<RangeKey>("3d")

  return (
    <>
      <div className="seg" role="group" aria-label="Диапазон обзора">
        {RANGE_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            aria-pressed={range === t.key}
            onClick={() => setRange(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {range === "scan"
        ? <ScanView model={model} onOpenDay={onOpenDay} />
        : <RangeView site={site} range={range} model={model} onOpenDay={onOpenDay} />}
    </>
  )
}

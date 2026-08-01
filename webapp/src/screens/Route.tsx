// Экран «Маршрут»: вердикт, разрез рельефа, таблица точек, перебор времени
// вылета, разбор от ИИ — раскладка ровно из renderRoute (miniapp/
// prototype.html:1067-1194). Карта в макете (строки 1071-1082) сюда не
// перенесена: заголовок задачи называет ровно четыре элемента (вердикт,
// разрез, карточка точки, разбор маршрута) — карта, сохранённые маршруты и
// «Новый маршрут» принадлежат задаче 13 (там же появится способ добавить
// точки; здесь их подставляют извне).
//
// Экран НЕ создаёт маршрут и не хранит его — он получает готовый список
// точек пропом (`points`, формат [lat, lon, name] — как ответ
// /api/route/parse и как хранит store, см. RoutePointRow в api/queries.ts) и
// сам зовёт POST /api/route через useRoute(). Пока задача 13 не даёт способа
// поставить точки, вызывающий код (App.tsx) передаёт пустой массив — экран
// показывает явное «нет маршрута», а не вечную загрузку.
//
// ВАЖНО про пропы `points`/`name`/`date`/`model`: эффект ниже перечитывает их
// в зависимостях и зовёт mutate() заново при любом изменении ссылки —
// вызывающий код обязан передавать СТАБИЛЬНУЮ ссылку на массив `points`
// (состояние, а не литерал `[]`/новый массив на каждый рендер), иначе экран
// будет слать запрос на каждый чужой ре-рендер родителя. App.tsx хранит
// пустой маршрут константой вне компонента ровно по этой причине.
import { useEffect, useState } from "react"
import { useRoute } from "../api/queries"
import type { RoutePointRow } from "../api/queries"
import type { RoutePoint } from "../api/types"
import { useSheetsContext } from "../App"
import { colorOfCategory } from "../charts/palette"
import { RouteProfile } from "../charts/RouteProfile"
import { compass, fmtNum } from "../format"
import { PointCardSheet, roleLabel } from "../sheets/PointCardSheet"
import { RouteAnalysisSheet } from "../sheets/RouteAnalysisSheet"
import { ErrorBox } from "../ui/ErrorBox"
import { Spinner } from "../ui/Spinner"

type RouteProps = {
  points: RoutePointRow[]
  name: string | null
  date: string
  model: string | null
}

function alongCell(v: number | null): string {
  return v === null ? "н/д" : `${v >= 0 ? "→" : "←"}${fmtNum(Math.abs(v))}`
}

function windCell(deg: number | null, kmh: number | null): string {
  return deg === null || kmh === null ? "н/д" : `${compass(deg)} ${fmtNum(kmh)}`
}

const CELL: { padding: string; textAlign: "left" | "center" | "right"; fontSize: number } = {
  padding: "6px 8px", textAlign: "left", fontSize: 12,
}

export function Route({ points, name, date, model }: RouteProps) {
  const sheets = useSheetsContext()
  // null — сервер сам выбирает время вылета (начало термического окна первой
  // точки, route.py:get_route). Пилот переопределяет его чипом времени вылета
  // ниже — тогда сюда попадает конкретное «ЧЧ:ММ» из departure_scan.
  const [departure, setDeparture] = useState<string | null>(null)
  const route = useRoute()
  const { mutate } = route

  useEffect(() => {
    if (points.length < 2) return
    mutate({ points, name, date, departure, model })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, name, date, departure, model, mutate])

  if (points.length < 2) {
    return (
      <div className="empty">
        <b>Нет маршрута</b>
        Отметьте хотя бы две точки, чтобы увидеть профиль маршрута.
      </div>
    )
  }
  if (route.isError) {
    return <ErrorBox error={route.error} onRetry={() => mutate({ points, name, date, departure, model })} />
  }
  if (!route.isSuccess) {
    return <Spinner />
  }

  const result = route.data
  const lastPoint: RoutePoint | undefined = result.points[result.points.length - 1]

  function openPointCard(p: RoutePoint): void {
    sheets.push(
      <PointCardSheet point={p} />,
      `${fmtNum(p.km)} км · ${p.eta ?? "без времени"} · ${roleLabel(p.role)}`,
    )
  }

  return (
    <>
      <div className="panel">
        <div className="panel__head">
          <span className="lbl">Маршрут</span>
          <span className="lbl">{result.route.sample_count} точек · шаг {fmtNum(result.route.sample_step_km)} км</span>
        </div>
        <div className="verdict">
          <div>
            <div className="verdict__win">{fmtNum(result.route.total_km)} км</div>
            <div className="verdict__sub">
              {result.route.name} · вылет {result.route.departure} → прилёт ~{lastPoint?.eta ?? "—"}
            </div>
          </div>
          <div className="verdict__score">
            <div className="verdict__num" style={{ color: colorOfCategory(result.verdict.category) }}>
              {result.verdict.score === null ? "—" : fmtNum(result.verdict.score, 1)}
            </div>
            <div className="verdict__cat">{result.verdict.label}</div>
          </div>
        </div>

        {result.verdict.blocked_at_km !== null && (
          <div className="limiting">
            <span className="limiting__k">Обрывается</span>
            <span>
              на {fmtNum(result.verdict.blocked_at_km)} км
              {result.verdict.blocked_reason !== null ? ` · ${result.verdict.blocked_reason}` : ""}
              {result.verdict.flyable_until_km !== null ? ` · лётно до ${fmtNum(result.verdict.flyable_until_km)} км` : ""}
            </span>
          </div>
        )}
        {result.verdict.bottleneck !== null && (
          <div className="limiting">
            <span className="limiting__k">Узкое место</span>
            <span>{fmtNum(result.verdict.bottleneck.score)} на {fmtNum(result.verdict.bottleneck.km)} км</span>
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel__head">
          <span className="lbl">Разрез маршрута</span>
          <span className="lbl">метры MSL</span>
        </div>
        <RouteProfile
          points={result.points}
          terrain={result.terrain}
          bottleneckKm={result.verdict.bottleneck?.km ?? null}
        />
      </div>

      <div className="panel">
        <div className="panel__head">
          <span className="lbl">Точки</span>
          <span className="lbl">тап — карточка точки</span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr>
                <th scope="col" style={CELL}>км</th>
                <th scope="col" style={CELL}>время</th>
                <th scope="col" style={CELL}>вдоль</th>
                <th scope="col" style={CELL}>ветер</th>
                <th scope="col" style={CELL}>балл</th>
              </tr>
            </thead>
            <tbody>
              {result.points.map((p) => (
                <tr
                  key={p.km}
                  role="button"
                  tabIndex={0}
                  aria-label={`${fmtNum(p.km)} км · ${p.eta ?? "без времени"} · ${roleLabel(p.role)}`}
                  style={{ cursor: "pointer" }}
                  onClick={() => openPointCard(p)}
                  onKeyDown={(e) => { if (e.key === "Enter") openPointCard(p) }}
                >
                  <td style={CELL}>{fmtNum(p.km)}</td>
                  <td style={CELL}>{p.eta ?? "—"}</td>
                  <td style={CELL}>{alongCell(p.wind_along_kmh)}</td>
                  <td style={CELL}>{windCell(p.wind_working_alt_dir, p.wind_working_alt_kmh)}</td>
                  <td style={{ ...CELL, fontWeight: 700, color: p.category === null ? undefined : colorOfCategory(p.category) }}>
                    {p.score ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <div className="panel__head">
          <span className="lbl">Время вылета</span>
          <span className="lbl">перебор по окну</span>
        </div>
        <div role="group" aria-label="Время вылета" style={{ display: "flex", gap: 7, flexWrap: "wrap", marginTop: 9 }}>
          {result.departure_scan.map((entry) => {
            const isActive = entry.departure === result.route.departure
            const isBest = result.best_departure !== null && entry.departure === result.best_departure.departure
            return (
              <button
                key={entry.departure}
                type="button"
                className="chip"
                aria-pressed={isActive}
                style={isActive ? { borderColor: "var(--ink)", color: "var(--ink)" } : undefined}
                title={isBest ? "Лучший вылет" : undefined}
                onClick={() => setDeparture(entry.departure)}
              >
                {entry.departure} → {entry.score === null ? "—" : fmtNum(entry.score, 1)}{isBest ? " ★" : ""}
              </button>
            )
          })}
        </div>
        {result.reverse.better && (
          <div className="attrib">
            Обратный маршрут лучше: {result.reverse.score === null ? "—" : fmtNum(result.reverse.score, 1)} против{" "}
            {result.verdict.score === null ? "—" : fmtNum(result.verdict.score, 1)}
          </div>
        )}
      </div>

      <div className="acts">
        <button
          type="button"
          className="act act--wide"
          onClick={() => sheets.push(
            <RouteAnalysisSheet points={points} name={name} date={date} departure={departure} model={model} />,
            "Разбор маршрута",
          )}
        >
          <b>Разбор от ИИ</b>
          <span>тактика по узкому месту</span>
        </button>
      </div>

      {result.notes.map((n, i) => <div key={`${i}-${n}`} className="attrib">{n}</div>)}
    </>
  )
}

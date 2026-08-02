// Экран «Маршрут»: карта, вердикт, разрез рельефа, таблица точек, перебор
// времени вылета, разбор от ИИ, кнопки «Сохранённые» и «Новый маршрут» —
// раскладка ровно из renderRoute (miniapp/prototype.html:1067-1194, кнопки —
// строки 1182-1186).
//
// Кнопки источника маршрута показываются в ЛЮБОМ состоянии экрана, а не
// только рядом с посчитанным маршрутом: пока маршрута нет (свежий сеанс) или
// пока он считается, это единственный способ его задать — спрятать их
// значило бы запереть пилота на экране «Нет маршрута» навсегда.
//
// Карта (строки 1071-1082 макета) — ПОКАЗ уже посчитанного маршрута, а не
// способ его задать: в макете drawMap рисует трассу и пины точек, а
// «Точки на карте» живут в отдельной шторке «Новый маршрут» (1781-1804,
// sheets/NewRouteSheet.tsx). Поэтому MapView здесь без onTap/onDragPoint —
// карта только показывает (см. комментарий у Props в map/MapView.tsx).
//
// Экран НЕ создаёт маршрут и не хранит его — он получает готовый список
// точек пропом (`points`, формат [lat, lon, name] — как ответ
// /api/route/parse и как хранит store, см. RoutePointRow в api/queries.ts) и
// сам зовёт POST /api/route через useRoute(). Точки выбирают шторки ниже
// («Сохранённые» и «Новый маршрут»), а хранит их App.tsx; пока выбора не
// было, приходит пустой массив — экран показывает явное «нет маршрута», а
// не вечную загрузку.
//
// ВАЖНО про пропы `points`/`name`/`date`/`model`: эффект ниже перечитывает их
// в зависимостях и зовёт mutate() заново при любом изменении ссылки —
// вызывающий код обязан передавать СТАБИЛЬНУЮ ссылку на массив `points`
// (состояние, а не литерал `[]`/новый массив на каждый рендер), иначе экран
// будет слать запрос на каждый чужой ре-рендер родителя. App.tsx хранит
// пустой маршрут константой вне компонента ровно по этой причине.
import { useEffect, useMemo, useState } from "react"
import { useRoute } from "../api/queries"
import type { RoutePointRow } from "../api/queries"
import type { RoutePoint, Site } from "../api/types"
import { useSheetsContext } from "../App"
import { BAND, TERRAIN, colorOfCategory } from "../charts/palette"
import { RouteProfile } from "../charts/RouteProfile"
import { compass, fmtNum, fmtPoints } from "../format"
import { MapView } from "../map/MapView"
import { NewRouteSheet } from "../sheets/NewRouteSheet"
import { PointCardSheet, roleLabel } from "../sheets/PointCardSheet"
import { RouteAnalysisSheet } from "../sheets/RouteAnalysisSheet"
import { SavedRoutesSheet } from "../sheets/SavedRoutesSheet"
import { ErrorBox } from "../ui/ErrorBox"
import { Spinner } from "../ui/Spinner"

type RouteProps = {
  points: RoutePointRow[]
  name: string | null
  date: string
  model: string | null
  // Выбранный маршрут уходит наверх, а не остаётся здесь: точки хранит
  // оболочка (App.tsx), иначе они пропадали бы при переключении вкладки.
  onPickRoute: (points: RoutePointRow[], name: string | null) => void
}

// route.py:FEASIBILITY_RU — дословно те же четыре строки, что печатает
// карточка маршрута в Telegram (route.py:756-761, показывается всегда:
// _verdict_lines кладёт её строкой под баллом). Без неё экран рисует
// одинаковый вердикт для «проходится» и «не успеваешь до закрытия окна»:
// балл и категория у них совпадают (route.json: вылет 15:30 — too_slow при
// том же 70,5 и «отличная лётная»), различает их только это поле.
// Незнакомый ключ показывается как есть, а не подменяется чужим смыслом —
// тот же приём, что и ROLE_RU в sheets/PointCardSheet.tsx.
const FEASIBILITY_RU: Record<string, string> = {
  completable: "маршрут проходится",
  blocked_at_km: "маршрут обрывается",
  too_slow: "не успеваешь до закрытия окна",
  unknown: "данных не хватает для вердикта",
}

function feasibilityLabel(feasibility: string): string {
  return FEASIBILITY_RU[feasibility] ?? feasibility
}

function alongCell(v: number | null): string {
  return v === null ? "н/д" : `${v >= 0 ? "→" : "←"}${fmtNum(Math.abs(v))}`
}

function windCell(deg: number | null, kmh: number | null): string {
  return deg === null || kmh === null ? "н/д" : `${compass(deg)} ${fmtNum(kmh)}`
}

// route.py:_signed — знак минуса тот же типографский «−», что и в карточке
// Telegram, чтобы запас окна читался одинаково в боте и в приложении.
function signedMin(v: number): string {
  return `${v < 0 ? "−" : "+"}${fmtNum(Math.abs(v))}`
}

// Стартов на карте маршрута нет (макет рисует только трассу и её точки), но
// проп MapView обязателен — пустой массив держим КОНСТАНТОЙ модуля: новый
// литерал на каждый рендер пересобирал бы маркеры стартов вхолостую (эффект
// MapView зависит от ссылки на массив).
const NO_SITES: Site[] = []

// Карта маршрута отдельным компонентом ради useMemo: MapView пересобирает
// маркеры при смене ССЫЛКИ на points, а экран перерисовывается ещё и от
// чужих причин (открытие шторки меняет контекст стека).
//
// Подпись пина — дословно из макета (prototype.html:1350: «Точка N км, балл
// X»), и нажатие на пин открывает ту же карточку точки, что и строка
// таблицы (там же, 1355): на карте пилот видит, ГДЕ точка, и тапает по ней,
// а не ищет её километр в таблице.
function RouteMap({ points, onOpenPoint }: { points: RoutePoint[]; onOpenPoint: (p: RoutePoint) => void }) {
  const mapPoints = useMemo(
    () => points.map((p) => ({
      lat: p.lat,
      lon: p.lon,
      title: `Точка ${fmtNum(p.km)} км, балл ${p.score === null ? "—" : fmtNum(p.score)}`,
    })),
    [points],
  )
  return (
    <div className="map">
      <MapView points={mapPoints} sites={NO_SITES} onPointTap={(i) => onOpenPoint(points[i]!)} />
    </div>
  )
}

// Две кнопки источника маршрута — фрагмент, а не отдельная панель: в макете
// они стоят в одном блоке .acts с «Разбором от ИИ» (prototype.html:
// 1182-1186), а в состояниях без посчитанного маршрута разбирать нечего, и
// тот же фрагмент оборачивается в собственный .acts.
//
// newRouteWide — широкая ли «Новый маршрут» (act--wide, grid-column: 1 / -1).
// В макете широкая именно она (mk(..., true), строка 1185), и рядом с
// «Разбором от ИИ» получается ряд из двух кнопок плюс широкая под ними —
// так и рисуется полное состояние экрана. В состояниях без посчитанного
// маршрута кнопок ровно две, и обе занимают по половине ряда: широкая там
// оставила бы «Сохранённые» одинокой половинкой с дырой справа.
function RouteSourceButtons(
  { onPickRoute, newRouteWide = false }: { onPickRoute: RouteProps["onPickRoute"]; newRouteWide?: boolean },
) {
  const sheets = useSheetsContext()
  return (
    <>
      <button
        type="button"
        className="act"
        onClick={() => sheets.push(
          <SavedRoutesSheet onPick={(pickedName, pickedPoints) => onPickRoute(pickedPoints, pickedName)} />,
          "Сохранённые маршруты",
        )}
      >
        <b>Сохранённые</b>
        <span>маршруты, сохранённые под именем</span>
      </button>
      <button
        type="button"
        className={newRouteWide ? "act act--wide" : "act"}
        onClick={() => sheets.push(<NewRouteSheet onApply={onPickRoute} />, "Новый маршрут")}
      >
        <b>Новый маршрут</b>
        <span>точки на карте, GPX или KML</span>
      </button>
    </>
  )
}

export function Route({ points, name, date, model, onPickRoute }: RouteProps) {
  const sheets = useSheetsContext()
  // Выбранное чипом время вылета хранится ВМЕСТЕ с маршрутом, для которого его
  // выбрали, и действует только пока показывают этот самый маршрут.
  //
  // Экран никогда не размонтируется (вкладки скрыты через hidden, а не сняты
  // с дерева, см. App.tsx), поэтому обычное состояние `departure` пережило бы
  // смену маршрута: пилот подобрал 18:00 маршруту А, открыл сохранённый
  // маршрут Б — и Б посчитался бы не по своему термическому окну (его сервер
  // выбирает сам, route.py:get_route), а по времени, подобранному для А.
  // Вернуть «пусть выбирает сервер» пилоту при этом нечем: чипы задают только
  // конкретное время. Найдено ревью задачи 13 (N1), воспроизведено на смене
  // маршрута.
  //
  // Сравнение по ССЫЛКЕ на массив точек, а не по его содержимому: тот же
  // маршрут, пришедший заново (перевыбор того же имени в «Сохранённых»), —
  // это новый расчёт, и время вылета для него сервер снова подбирает сам.
  const [pickedDeparture, setPickedDeparture] = useState<{ points: RoutePointRow[]; time: string } | null>(null)
  // null — сервер сам выбирает время вылета (начало термического окна первой
  // точки, route.py:get_route).
  const departure = pickedDeparture !== null && pickedDeparture.points === points ? pickedDeparture.time : null
  const route = useRoute()
  const { mutate } = route

  useEffect(() => {
    if (points.length < 2) return
    mutate({ points, name, date, departure, model })
  }, [points, name, date, departure, model, mutate])

  if (points.length < 2) {
    return (
      <>
        <div className="empty">
          <b>Нет маршрута</b>
          Отметьте хотя бы две точки, чтобы увидеть профиль маршрута.
        </div>
        <div className="acts"><RouteSourceButtons onPickRoute={onPickRoute} /></div>
      </>
    )
  }
  if (route.isError) {
    return (
      <>
        <ErrorBox error={route.error} onRetry={() => mutate({ points, name, date, departure, model })} />
        <div className="acts"><RouteSourceButtons onPickRoute={onPickRoute} /></div>
      </>
    )
  }
  if (!route.isSuccess) {
    return (
      <>
        <Spinner />
        <div className="acts"><RouteSourceButtons onPickRoute={onPickRoute} /></div>
      </>
    )
  }

  const result = route.data
  const lastPoint: RoutePoint | undefined = result.points[result.points.length - 1]

  // Запас окна — у первой и последней точки, где домен его посчитал: ровно
  // тот же отбор, что и в карточке Telegram (route.py:990-993 — margins[0] и
  // margins[-1] среди непустых, а не у крайних точек маршрута, у которых
  // запас может быть не посчитан вовсе).
  const margins = result.points.map((p) => p.time_margin_min).filter((v): v is number => v !== null)
  const marginLine =
    margins.length === 0
      ? null
      : `Запас окна: старт ${signedMin(margins[0]!)} мин · финиш ${signedMin(margins[margins.length - 1]!)} мин`

  function openPointCard(p: RoutePoint): void {
    sheets.push(
      <PointCardSheet point={p} />,
      `${fmtNum(p.km)} км · ${p.eta ?? "без времени"} · ${roleLabel(p.role)}`,
    )
  }

  return (
    <>
      <RouteMap points={result.points} onOpenPoint={openPointCard} />

      <div className="panel">
        <div className="panel__head">
          <span className="lbl">Маршрут</span>
          <span className="lbl">{fmtPoints(result.route.sample_count)} · шаг {fmtNum(result.route.sample_step_km)} км</span>
        </div>
        <div className="verdict">
          <div>
            <div className="verdict__win">{fmtNum(result.route.total_km)} км</div>
            {/* Имя маршрута необязательно (api.py:RouteIn — `name: str | None
                = None`, forecast.py:799 кладёт его в ответ как есть), поэтому
                разделитель живёт вместе с именем: иначе строка начиналась бы
                с висячего « · вылет …». */}
            <div className="verdict__sub">
              {result.route.name === null ? "" : `${result.route.name} · `}
              вылет {result.route.departure} → прилёт ~{lastPoint?.eta ?? "—"}
            </div>
          </div>
          <div className="verdict__score">
            <div className="verdict__num" style={{ color: colorOfCategory(result.verdict.category) }}>
              {result.verdict.score === null ? "—" : fmtNum(result.verdict.score, 1)}
            </div>
            <div className="verdict__cat">{result.verdict.label}</div>
            <div className="verdict__cat">{feasibilityLabel(result.verdict.feasibility)}</div>
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
        {/* Легенда — prototype.html:1113-1119. Три слоя разреза без подписей
            неразличимы: пилот не знает, что за прозрачная зона над рельефом.
            Цвета квадратиков берутся из тех же констант палитры и с той же
            прозрачностью, которыми нарисован сам разрез (RouteProfile), —
            иначе легенда объясняла бы не то, что нарисовано. Без рельефа
            разреза нет вовсе, и объяснять нечего. */}
        {result.terrain !== null && (
          <div className="legend">
            <span><i style={{ background: TERRAIN }} />рельеф</span>
            <span><i style={{ background: BAND, opacity: 0.34 }} />рабочий коридор</span>
            <span><i style={{ background: "var(--air-deep)" }} />база облаков</span>
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel__head">
          <span className="lbl">Точки</span>
          <span className="lbl">тап — карточка точки</span>
        </div>
        <div style={{ overflowX: "auto" }}>
          {/* Колонки и классы ячеек — .rtable из макета (prototype.html:
              284-294): моноширинный шрифт, числа вправо, приглушённые
              колонки времени и ветра (.u), жирный балл (.sc). */}
          <table className="rtable">
            <thead>
              <tr>
                <th scope="col">км</th>
                <th scope="col">время</th>
                <th scope="col">вдоль</th>
                <th scope="col">ветер</th>
                <th scope="col">балл</th>
              </tr>
            </thead>
            <tbody>
              {result.points.map((p) => (
                <tr
                  key={p.km}
                  role="button"
                  tabIndex={0}
                  aria-label={`${fmtNum(p.km)} км · ${p.eta ?? "без времени"} · ${roleLabel(p.role)}`}
                  onClick={() => openPointCard(p)}
                  onKeyDown={(e) => { if (e.key === "Enter") openPointCard(p) }}
                >
                  <td>{fmtNum(p.km)}</td>
                  <td className="u">{p.eta ?? "—"}</td>
                  <td>{alongCell(p.wind_along_kmh)}</td>
                  <td className="u">{windCell(p.wind_working_alt_dir, p.wind_working_alt_kmh)}</td>
                  <td className="sc" style={{ color: p.category === null ? undefined : colorOfCategory(p.category) }}>
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
            const score = entry.score === null ? "—" : fmtNum(entry.score, 1)
            // Балл не различает варианты вылета: в route.json 15:30
            // (too_slow) и 07:00 (completable) оба показывают 70,5. Поэтому у
            // непроходимых вариантов проходимость печатается ВИДИМЫМ текстом
            // чипа, а не только в его доступном имени: приложение открывают в
            // Telegram на телефоне, где нет ни курсора, чтобы всплыл title, ни
            // скринридера, чтобы прочесть aria-label (ре-ревью task-12, N3).
            // У проходимых вариантов чип остаётся коротким, как в макете
            // (prototype.html:1155-1163) — предупреждать не о чем.
            const feasibility = feasibilityLabel(entry.feasibility)
            const warning = entry.feasibility === "completable" ? "" : ` · ${feasibility}`
            return (
              <button
                key={entry.departure}
                type="button"
                className="chip chip--dep"
                aria-pressed={isActive}
                aria-label={`${entry.departure} → ${score} · ${feasibility}`}
                style={isActive ? { borderColor: "var(--ink)", color: "var(--ink)" } : undefined}
                title={isBest ? `Лучший вылет · ${feasibility}` : feasibility}
                onClick={() => setPickedDeparture({ points, time: entry.departure })}
              >
                {entry.departure} → {score}{isBest ? " ★" : ""}{warning}
              </button>
            )
          })}
        </div>
        {/* Строка запаса окна и обратного маршрута — prototype.html:1166.
            Запас берётся у первой и последней точки с посчитанным запасом,
            как в карточке Telegram (route.py:990-993); обратный маршрут
            показывается ВСЕГДА, а не только когда он лучше: «обратный — 84,0»
            против «прямой — 70,5» пилот сравнивает сам, а исчезающая строка
            выглядела бы как отсутствие данных. */}
        <div className="attrib">
          {marginLine === null ? "" : `${marginLine}. `}
          Обратный маршрут — {result.reverse.score === null ? "—" : fmtNum(result.reverse.score, 1)}
          {result.reverse.better ? " (лучше прямого)" : ""}
        </div>
      </div>

      <div className="acts">
        <button
          type="button"
          className="act"
          onClick={() => sheets.push(
            <RouteAnalysisSheet points={points} name={name} date={date} departure={departure} model={model} />,
            "Разбор маршрута",
          )}
        >
          <b>Разбор от ИИ</b>
          <span>тактика по узкому месту</span>
        </button>
        <RouteSourceButtons onPickRoute={onPickRoute} newRouteWide />
      </div>

      {result.notes.map((n, i) => <div key={`${i}-${n}`} className="attrib">{n}</div>)}
    </>
  )
}

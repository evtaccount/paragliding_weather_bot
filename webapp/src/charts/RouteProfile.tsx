// Прибор «Разрез маршрута» — своя SVG-отрисовка (без библиотек графиков,
// запрещены заданием). Раскладка — buildSection (miniapp/prototype.html:
// 1195-1265): сетка высот слева, рельеф заливкой снизу, рабочий коридор
// (от рельефа до потолка термички) прозрачной заливкой поверх, база облаков
// пунктиром, точки маршрута — вертикальный пунктир + кружок цвета категории.
//
// ГЛАВНОЕ (см. комментарий в forecast.py рядом с формированием ответа
// /api/route и task-12-brief.md): рельеф приходит ОТДЕЛЬНОЙ сеткой co своим
// километражом (`terrain.km`/`terrain.elevations`) — `terrain_grid` в
// домене делит каждое плечо маршрута на целое число равных частей, поэтому
// шаг у разных плеч разный. Рисовать рельеф по ИНДЕКСУ сэмпла (считая шаг
// одинаковым по всей длине) — распространённая и малозаметная ошибка: на
// коротких маршрутах со сравнимыми по длине плечами она почти не видна, а на
// маршруте с плечами разной длины рельеф молча съезжает относительно точек
// погоды. Поэтому x-координата ЛЮБОЙ точки на этом графике (рельефа или
// маршрута) — функция её КИЛОМЕТРА (`terrain.km[i]` или `point.km`), а не её
// порядкового номера в массиве; обе шкалы делят один и тот же километраж
// (последний км рельефной сетки — единственная общая система координат
// между рельефом и погодой на этом графике).
//
// Рабочий коридор и база облаков известны только В ТОЧКАХ маршрута
// (forecast.py:_ceiling_m и route.py:cloud_base_m считают их на сэмпл, не на
// каждый километр рельефной сетки) — линии между соседними точками соединены
// отрезками (обычная практика графиков, а не выдумывание данных: как и
// метеограмма соединяет часовые отсчёты прямыми, не имея данных между ними).
// Верх коридора — thermal_ceiling_m (рельеф плюс глубина пограничного слоя,
// forecast.py:_ceiling_m:568-578), а НЕ cloud_base_m: база облаков выше
// потолка термички и рисуется отдельным пунктиром — рисовать коридор до неё
// значило бы завышать рабочую высоту.
//
// Цвета: TERRAIN/BAND — из palette.ts (те же, что и в AirColumn.tsx, чтобы
// рельеф на разных приборах выглядел одинаково); цвет точки — colorOfCategory
// категории лётности этой точки. Пунктир базы облаков и нейтральные штрихи —
// через переменные темы (var(--air-deep)/var(--ink)/var(--rule)/var(--faint)),
// как и в AirColumn.tsx — не цвет данных, а акцент темы.
import { BAND, TERRAIN, colorOfCategory } from "./palette"
import type { RoutePoint } from "../api/types"

type RouteProfileProps = {
  points: RoutePoint[]
  terrain: { km: number[]; elevations: number[] } | null
  bottleneckKm: number | null
}

const WIDTH = 340
const HEIGHT = 150
const PAD_L = 30
const PAD_R = 8
const PAD_TOP = 10
const PAD_BOTTOM = 20
const CHART_H = HEIGHT - PAD_TOP - PAD_BOTTOM
const GRID_STEP_M = 500

// Точка «плывёт» внутри рабочего коридора — на 55% высоты от рельефа до его
// верха, как в макете (buildSection: `p.terrain + (p.base - p.terrain) *
// .55`; у макета верх коридора называется base, здесь это
// thermal_ceiling_m — см. шапку файла). Чисто отображение, на расчёт не
// влияет.
const MARKER_BAND_FRACTION = 0.55

// Километр точки округлён доменом до 0,1 (forecast.py:_point_dict — `"km":
// round(s.km, 1)`), а километр узкого места приходит СЫРЫМ float того же
// сэмпла (criteria.py:802 — `{"km": worst["km"], ...}`, в forecast.py не
// округляется). На route.json это 10.007557221018047 против 10,0 — строгое
// равенство не совпадало никогда, и подпись узкого места на разрезе не
// выделялась ни разу (ревью task-12, Important-4). Сравниваются поэтому оба
// километра, приведённые к той же десятой, что и сам домен.
function sameKm(a: number, b: number): boolean {
  return Math.round(a * 10) === Math.round(b * 10)
}

export function RouteProfile({ points, terrain, bottleneckKm }: RouteProfileProps) {
  if (terrain === null || terrain.km.length === 0) {
    return (
      <p style={{ fontSize: 12.5, color: "var(--muted)", margin: 0 }}>
        Рельеф недоступен — разрез не построен.
      </p>
    )
  }

  const domainKm = terrain.km[terrain.km.length - 1]!
  const x = (km: number): number =>
    domainKm <= 0 ? PAD_L : PAD_L + (km / domainKm) * (WIDTH - PAD_L - PAD_R)

  const ceilings = points.map((p) => p.thermal_ceiling_m).filter((v): v is number => v !== null)
  const bases = points.map((p) => p.cloud_base_m).filter((v): v is number => v !== null)
  const lo = Math.min(...terrain.elevations) - 100
  const hi = Math.max(...terrain.elevations, ...ceilings, ...bases, lo + 1) + 200
  const span = Math.max(hi - lo, 1)
  const y = (m: number): number => PAD_TOP + CHART_H - ((m - lo) / span) * CHART_H

  const gridValues: number[] = []
  for (let v = Math.ceil(lo / GRID_STEP_M) * GRID_STEP_M; v < hi; v += GRID_STEP_M) gridValues.push(v)

  // Контур рельефа: одна вершина на каждый км рельефной сетки (не на каждую
  // точку маршрута) — ровно то, что должен ловить тест «разрез рисует
  // рельеф из terrain, а не из точек».
  const terrainOutline = terrain.km.map((km, i) => `${x(km)},${y(terrain.elevations[i]!)}`).join(" ")
  const terrainFill =
    `${terrainOutline} ${x(terrain.km[terrain.km.length - 1]!)},${HEIGHT - PAD_BOTTOM} ` +
    `${x(terrain.km[0]!)},${HEIGHT - PAD_BOTTOM}`

  // Рабочий коридор и база облаков — только там, где домен их посчитал
  // (route.py: оба null без рельефа или без нужных рядов погоды у этой
  // точки), соединены отрезками между соседними такими точками.
  const bandPoints = points.filter((p) => p.terrain_m !== null && p.thermal_ceiling_m !== null)
  const baseTop = bandPoints.map((p) => `${x(p.km)},${y(p.thermal_ceiling_m!)}`).join(" ")
  const baseBottom = [...bandPoints].reverse().map((p) => `${x(p.km)},${y(p.terrain_m!)}`).join(" ")
  const bandPolygon = bandPoints.length >= 2 ? `${baseTop} ${baseBottom}` : null

  const cloudBasePoints = points.filter((p) => p.cloud_base_m !== null)
  const cloudBaseLine =
    cloudBasePoints.length >= 2
      ? cloudBasePoints.map((p) => `${x(p.km)},${y(p.cloud_base_m!)}`).join(" ")
      : null

  const isBottleneck = (km: number): boolean => bottleneckKm !== null && sameKm(km, bottleneckKm)

  function markerY(p: RoutePoint): number {
    if (p.terrain_m === null) return y(lo)
    if (p.thermal_ceiling_m === null) return y(p.terrain_m)
    return y(p.terrain_m + (p.thermal_ceiling_m - p.terrain_m) * MARKER_BAND_FRACTION)
  }

  return (
    <svg
      className="route-section"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      width="100%"
      role="img"
      aria-label="Разрез маршрута: рельеф, рабочий коридор и база облаков"
    >
      {gridValues.map((v) => (
        <g key={v}>
          <line x1={PAD_L} x2={WIDTH - PAD_R} y1={y(v)} y2={y(v)} style={{ stroke: "var(--rule)" }} strokeWidth={1} />
          <text x={PAD_L - 5} y={y(v) + 3} textAnchor="end" fontSize={8} style={{ fill: "var(--faint)" }}>
            {v}
          </text>
        </g>
      ))}

      {/* Классы route-band/route-cloud-base — как и route-terrain ниже: не
          для стилей (цвета и штрих заданы атрибутами), а чтобы тест мог
          отличить слой коридора от заливки рельефа и пунктир базы от прочих
          линий, не гадая по атрибуту fill. */}
      {bandPolygon !== null && <polygon className="route-band" points={bandPolygon} fill={BAND} opacity={0.34} />}

      {cloudBaseLine !== null && (
        <polyline
          className="route-cloud-base"
          points={cloudBaseLine}
          fill="none"
          style={{ stroke: "var(--air-deep)" }}
          strokeWidth={1.5}
          strokeDasharray="4 3"
        />
      )}

      <polygon points={terrainFill} fill={TERRAIN} />
      <polyline className="route-terrain" points={terrainOutline} fill="none" style={{ stroke: TERRAIN }} strokeWidth={1} />

      {points.map((p) => (
        <g key={p.km}>
          <line
            x1={x(p.km)} x2={x(p.km)} y1={PAD_TOP} y2={HEIGHT - PAD_BOTTOM}
            style={{ stroke: "var(--rule)" }} strokeWidth={1} strokeDasharray="2 3"
          />
          <circle
            cx={x(p.km)} cy={markerY(p)} r={4}
            fill={p.category === null ? "var(--faint)" : colorOfCategory(p.category)}
            style={{ stroke: "var(--panel)" }} strokeWidth={1.5}
          />
          <text
            x={x(p.km)} y={HEIGHT - 6} textAnchor="middle" fontSize={8}
            style={{ fill: isBottleneck(p.km) ? "var(--ink)" : "var(--faint)" }}
            fontWeight={isBottleneck(p.km) ? 700 : 400}
          >
            {Math.round(p.km)}
          </text>
        </g>
      ))}
    </svg>
  )
}

// Прибор 3: метеограмма — температура, ветер, порывы по часам, своя
// SVG-отрисовка (без библиотек графиков, запрещены заданием). Раскладка —
// из макета (miniapp/prototype.html:1705-1765, buildMeteogram): один общий
// график, где температура и ветер/порывы делят одну область высоты, каждый
// ряд — своя шкала (нет общей подписанной оси), сетка и подписи проведены
// по шкале ветра, лётное окно подсвечено прямоугольником, ось часов внизу
// подписана через один (каждый чётный час), легенда цветов — тремя
// строками сверху слева, прямо внутри SVG (как и в макете — не HTML).
//
// Отличие от макета: там шкалы захардкожены под демо-данные
// (tLo=16/tHi=32°, wLo=0/wHi=12 м/с) — на настоящих числах жаркий или
// холодный день, либо очень слабый/сильный ветер, обрезался бы графиком,
// рассчитанным на чужие границы. Вместо этого границы считаются из самих
// данных тем же приёмом, что charts.py:meteogram_png (backend-график той
// же метеограммы): tmn=min(temp)-2/tmx=max(temp)+2, wmx=max(max(gust)+1,4)
// — тот же запас в 2° и тот же пол в 4 м/с, что уже проверены на реальных
// прогонах бота.
//
// Цвета рядов и подсветки окна — только из palette.ts (TEMP/WIND/GUST/BAND):
// литералов цвета здесь нет.
import { BAND, GUST, TEMP, WIND } from "./palette"
import type { HourFact } from "../api/types"

type MeteogramProps = {
  hours: HourFact[]
  window: number[] | null
}

const WIDTH = 340
const HEIGHT = 190
const PAD_L = 26
const PAD_R = 26
const PAD_TOP = 12
const PAD_BOTTOM = 22
const CHART_H = HEIGHT - PAD_TOP - PAD_BOTTOM
const WIND_GRID_STEP = 4 // м/с — тот же шаг, что подписи 0/4/8/12 в макете

const LEGEND: [string, string][] = [
  [TEMP, "температура, °"],
  [WIND, "ветер, м/с"],
  [GUST, "порывы"],
]

function hourOf(time: string): number {
  return Number(time.slice(0, 2))
}

function pathFor(values: number[], x: (i: number) => number, y: (v: number) => number): string {
  return values.map((v, i) => `${i === 0 ? "M" : "L"} ${x(i)} ${y(v)}`).join(" ")
}

export function Meteogram({ hours, window }: MeteogramProps) {
  // hours.length - 1 в знаменателе x(i) — при одном-единственном часе (в
  // брифовых фикстурах такого нет, но делить на 0 нельзя) высота берётся
  // как минимум 1, тогда единственная точка встаёт в padL и не падает.
  const lastIndex = Math.max(hours.length - 1, 1)
  const x = (i: number): number => PAD_L + (i / lastIndex) * (WIDTH - PAD_L - PAD_R)

  const temps = hours.map((h) => h.temp_c)
  const winds = hours.map((h) => h.wind_ms)
  const gusts = hours.map((h) => h.gust_ms)

  const tLo = Math.min(...temps) - 2
  const tHi = Math.max(...temps) + 2
  const wLo = 0
  const wHi = Math.max(Math.max(...gusts) + 1, 4)

  const yTemp = (v: number): number => PAD_TOP + ((tHi - v) / (tHi - tLo)) * CHART_H
  const yWind = (v: number): number => PAD_TOP + ((wHi - v) / (wHi - wLo)) * CHART_H

  const gridValues: number[] = []
  for (let v = 0; v <= wHi; v += WIND_GRID_STEP) gridValues.push(v)

  const winStart = window?.[0]
  const winEnd = window?.[1]
  const iStart = winStart === undefined ? -1 : hours.findIndex((h) => hourOf(h.time) === winStart)
  const iEnd = winEnd === undefined ? -1 : hours.findIndex((h) => hourOf(h.time) === winEnd)

  return (
    <svg
      className="meteogram"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      width="100%"
      role="img"
      aria-label="Метеограмма: температура, ветер и порывы по часам"
    >
      {iStart >= 0 && iEnd >= 0 && (
        <rect x={x(iStart)} y={PAD_TOP} width={x(iEnd) - x(iStart)} height={CHART_H} fill={BAND} opacity={0.13} />
      )}

      {gridValues.map((v) => (
        <g key={v}>
          <line
            x1={PAD_L}
            y1={yWind(v)}
            x2={WIDTH - PAD_R}
            y2={yWind(v)}
            style={{ stroke: "var(--rule)" }}
            strokeWidth={1}
          />
          <text x={WIDTH - PAD_R + 4} y={yWind(v) + 3} fontSize={8} style={{ fill: "var(--faint)" }}>
            {v}
          </text>
        </g>
      ))}

      <path
        d={pathFor(gusts, x, yWind)}
        fill="none"
        stroke={GUST}
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
        strokeDasharray="4 3"
      />
      <path d={pathFor(winds, x, yWind)} fill="none" stroke={WIND} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      <path d={pathFor(temps, x, yTemp)} fill="none" stroke={TEMP} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

      {hours.map((h, i) => {
        const hour = hourOf(h.time)
        if (hour % 2 !== 0) return null
        return (
          <text
            key={h.time}
            x={x(i)}
            y={HEIGHT - 6}
            textAnchor="middle"
            fontSize={8}
            style={{ fill: "var(--faint)" }}
          >
            {String(hour).padStart(2, "0")}
          </text>
        )
      })}

      {LEGEND.map(([color, label], i) => (
        <g key={label}>
          <rect x={PAD_L} y={PAD_TOP + 2 + i * 11} width={7} height={2.5} fill={color} />
          <text x={PAD_L + 11} y={PAD_TOP + 6 + i * 11} fontSize={7.5} style={{ fill: "var(--muted)" }}>
            {label}
          </text>
        </g>
      ))}
    </svg>
  )
}

// Прибор 1: полоса часов дня — своя SVG-отрисовка, без библиотек графиков
// (запрещены заданием). Раскладка и смысл столбиков — из макета
// (miniapp/prototype.html: renderDay, строки 765-806): один столбик на
// каждый час светлого времени, высота = балл часа, цвет = категория часа,
// подсветка — лётное окно.
//
// Цвет столбика и подсветки окна — только из palette.ts (colorOfCategory,
// BAND): литералов цвета здесь нет.
//
// score/lim у часа бывают null (criteria.py:HourAssessment.compact) — час
// без данных получает category "no_data" (см. criteria.NO_DATA) и рисуется
// нулевым столбиком, а не выдуманной высотой.
import { BAND, colorOfCategory } from "./palette"
import type { HourFact } from "../api/types"

// window — не кортеж [number, number]: у Assessment.fly_window (api/types.ts)
// тип number[] | null, потому что это JSON-массив без гарантии длины на
// уровне типа. Кортеж здесь дал бы ошибку строгой сборки на самом первом
// тесте (charts.test.tsx передаёт F.assessment.fly_window напрямую) — не
// расхождение в данных, а несовпадение формы типа с уже существующим
// Assessment, который менять в этой задаче не входит.
type HourStripProps = {
  hours: HourFact[]
  window: number[] | null
}

const BAR_W = 18
const GAP = 6
const CHART_H = 78 // высота полосы столбиков — как в макете (.strip__bars height:104px минус подпись)
const PAD_TOP = 16 // место под числом балла над столбиком
const PAD_BOTTOM = 16 // место под подписью часа

function hourOf(time: string): number {
  return Number(time.slice(0, 2))
}

export function HourStrip({ hours, window }: HourStripProps) {
  const slot = BAR_W + GAP
  const width = hours.length * slot - GAP
  const height = PAD_TOP + CHART_H + PAD_BOTTOM
  const baseline = PAD_TOP + CHART_H

  return (
    <svg
      className="hour-strip"
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      role="img"
      aria-label="Полоса часов дня — балл и категория по часам"
    >
      {hours.map((h, i) => {
        const hour = hourOf(h.time)
        const winStart = window?.[0]
        const winEnd = window?.[1]
        const inWindow = winStart !== undefined && winEnd !== undefined && hour >= winStart && hour <= winEnd
        const x = i * slot
        const barH = h.score === null ? 0 : Math.max(0, Math.round((h.score / 100) * CHART_H))
        const color = colorOfCategory(h.cat)
        return (
          <g key={h.time} data-hour={hour} data-in-window={inWindow ? "true" : "false"}>
            {inWindow && <rect x={x} y={PAD_TOP} width={BAR_W} height={CHART_H} fill={BAND} opacity={0.18} />}
            <rect x={x} y={baseline - barH} width={BAR_W} height={barH} rx={2} fill={color} />
            <text
              x={x + BAR_W / 2}
              y={PAD_TOP - 5}
              textAnchor="middle"
              fontSize={10}
              style={{ fill: "var(--muted)" }}
            >
              {h.score === null ? "—" : Math.round(h.score)}
            </text>
            <text
              x={x + BAR_W / 2}
              y={height - 4}
              textAnchor="middle"
              fontSize={10}
              style={{ fill: "var(--faint)" }}
            >
              {String(hour).padStart(2, "0")}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

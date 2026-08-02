// Прибор 2: столб воздуха — своя SVG-отрисовка (без библиотек графиков).
// Снизу вверх: рельеф → старт (site.elevation_m) → рабочий коридор →
// потолок термиков (thermal_ceiling_m_msl) → база облаков (elevation_m +
// lcl_m_agl). Раскладка и смысл — из макета (miniapp/prototype.html:
// renderDay, столб воздуха, строки 823-889): рельеф и коридор заливкой,
// потолок и база — горизонтальными линиями с подписями высоты.
//
// Заливки рельефа/коридора — только из palette.ts (TERRAIN/BAND):
// литералов цвета здесь нет. Нейтральные штрихи и подписи (оси, линии,
// текст) берут цвет через переменные темы (var(--ink) и т.п.), которые уже
// выставляет theme.ts — так же, как остальные экраны оболочки.
//
// ECMWF (модель по умолчанию) не отдаёт boundary_layer_height — тогда
// thermal_ceiling_m_agl/msl приходят null (engine.py:_series_available).
// Потолок в этом случае подписывается «потолок неизвестен», а не
// рисуется по выдуманной высоте: ни линии, ни коридора без него нет.
//
// Имя модели, которой считается потолок, приходит с ответом
// (facts.site.ceiling_model) — см. подпись внизу графика.
import { BAND, TERRAIN } from "./palette"
import type { Facts } from "../api/types"

type AirColumnProps = { facts: Facts }

const WIDTH = 320
const HEIGHT = 210
const COL_X = 54 // левая граница цветной колонки — после шкалы высот
const COL_W = 64
const LABEL_X = COL_X + COL_W + 10
const TOP_PAD = 14
const BOTTOM_PAD = 22
const CHART_H = HEIGHT - TOP_PAD - BOTTOM_PAD
const GRID_STEP_M = 500

export function AirColumn({ facts }: AirColumnProps) {
  const elevation = facts.site.elevation_m
  const ceilingMsl = facts.thermal_ceiling_m_msl
  const ceilingAgl = facts.thermal_ceiling_m_agl
  const baseMsl = elevation + facts.lcl_m_agl

  // Границы шкалы — как в charts.py:ceiling_png (zmn = elev - 100, zmx с
  // запасом сверху над самой высокой известной отметкой).
  const lo = elevation - 100
  const hi = Math.max(baseMsl, ceilingMsl ?? baseMsl, elevation) + 200
  const span = Math.max(hi - lo, 1)

  const y = (m: number): number => TOP_PAD + CHART_H - ((m - lo) / span) * CHART_H

  const gridValues: number[] = []
  for (let v = Math.ceil(lo / GRID_STEP_M) * GRID_STEP_M; v < hi; v += GRID_STEP_M) gridValues.push(v)

  const yStart = y(elevation)
  const yBase = y(baseMsl)
  const yCeiling = ceilingMsl === null ? null : y(ceilingMsl)

  return (
    <svg
      className="air-column"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      width="100%"
      role="img"
      aria-label="Столб воздуха — рельеф, старт, рабочий коридор, потолок и база облаков"
    >
      {gridValues.map((v) => (
        <g key={v}>
          <line
            x1={COL_X}
            y1={y(v)}
            x2={WIDTH - 4}
            y2={y(v)}
            style={{ stroke: "var(--rule)" }}
            strokeWidth={1}
          />
          <text
            x={COL_X - 6}
            y={y(v)}
            textAnchor="end"
            dominantBaseline="middle"
            fontSize={9}
            style={{ fill: "var(--faint)" }}
          >
            {v}
          </text>
        </g>
      ))}

      {/* рельеф — от низа шкалы до высоты старта */}
      <rect x={COL_X} y={yStart} width={COL_W} height={TOP_PAD + CHART_H - yStart} fill={TERRAIN} />

      {/* рабочий коридор — от старта до потолка; без потолка коридор не рисуется,
          его верхняя граница попросту неизвестна */}
      {yCeiling !== null && (
        <rect x={COL_X} y={yCeiling} width={COL_W} height={yStart - yCeiling} fill={BAND} opacity={0.42} />
      )}

      {/* линия потолка */}
      {yCeiling !== null && (
        <line
          x1={COL_X}
          y1={yCeiling}
          x2={WIDTH - 4}
          y2={yCeiling}
          style={{ stroke: "var(--ink)" }}
          strokeWidth={1.5}
        />
      )}

      {/* линия базы облаков — выше потолка, пунктиром */}
      <line
        x1={COL_X}
        y1={yBase}
        x2={WIDTH - 4}
        y2={yBase}
        style={{ stroke: "var(--air-deep)" }}
        strokeWidth={1.5}
        strokeDasharray="4 3"
      />

      <text x={LABEL_X} y={yBase - 4} fontSize={11} style={{ fill: "var(--muted)" }}>
        база облаков {Math.round(baseMsl)} м
      </text>

      {ceilingMsl === null ? (
        <text x={LABEL_X} y={y(elevation + facts.lcl_m_agl / 2)} fontSize={11} style={{ fill: "var(--muted)" }}>
          потолок неизвестен
        </text>
      ) : (
        <text x={LABEL_X} y={yCeiling! - 4} fontSize={11} style={{ fill: "var(--muted)" }}>
          потолок · {Math.round(ceilingMsl)} м
          {ceilingAgl !== null ? ` · рабочий коридор ${Math.round(ceilingAgl)} м` : ""}
        </text>
      )}

      <text x={LABEL_X} y={yStart - 4} fontSize={11} style={{ fill: "var(--muted)" }}>
        старт · {elevation} м
      </text>

      {/* Модель для потолка не совпадает с моделью, выбранной пилотом для
          остального прогноза (miniapp/README.md:39-41): она одна отдаёт
          boundary_layer_height, а ECMWF (модель по умолчанию) — нет. Её имя
          берётся из ответа (facts.site.ceiling_model, engine.py:facts_1day по
          CEILING_MODEL_KEY), а не пишется здесь словом: подпись «по GFS» была
          одной из трёх копий константы и пережила бы её смену молча —
          пилот читал бы «по GFS» под высотой, посчитанной другой моделью
          (финальное ревью ветки, I1). */}
      <text x={4} y={HEIGHT - 6} fontSize={9.5} style={{ fill: "var(--faint)" }}>
        Высота термического слоя всегда считается по {facts.site.ceiling_model}, а не по выбранной модели
      </text>
    </svg>
  )
}

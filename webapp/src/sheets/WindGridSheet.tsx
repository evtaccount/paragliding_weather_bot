// Тело шторки «Ветер по высотам» — таблица «высота × час»: строки — уровни
// сверху вниз по убыванию alt_m_msl, столбцы — часы; в ячейке стрелка
// направления ветра и скорость. Раскладка — openWindGrid (miniapp/
// prototype.html:1487-1532): тот же порядок строк/столбцов, тот же
// поворот стрелки (остриём вниз = азимут 180°, ветер дует В сторону
// dir+180, поэтому поворот SVG = dir — комментарий там же, строки
// 1512-1513) и то же правило округления числа (num(spd, spd<10?1:0) —
// строка 1517, здесь fmtNum с тем же условием).
//
// Раскраска ячеек по силе ветра (charts._grid_cell_color, строки
// 1508-1511 макета) сюда не перенесена: она читает пороги
// criteria.grade_of() ОТДЕЛЬНО для каждого уровня (у земли, на 925 и на
// 850 пороги разные — charts.py:311-313), а WindGrid (api/types.ts) отдаёт
// только числа ветра, не категорию. Подбирать пороги на фронтенде заново
// значило бы дублировать питоновскую шкалу вслепую и рисковать разойтись с
// ней молча — как раз то, чего избегает palette.ts для остальных цветов
// (см. комментарий там). Бриф просит стрелку и скорость — это есть; сама
// таблица и подпись/выделение старта — тоже.
//
// Свой запрос: /api/forecast/wind-grid — отдельный эндпоинт от
// /api/forecast, поэтому шторка сама вызывает useWindGrid(...), а не
// переиспользует facts экрана (в отличие от MeteogramSheet, которому
// отдельный запрос не нужен).
import type { CSSProperties } from "react"
import { useWindGrid } from "../api/queries"
import { compass, fmtNum, fmtWind } from "../format"
import { ErrorBox } from "../ui/ErrorBox"
import { Spinner } from "../ui/Spinner"

type WindGridSheetProps = {
  site: string
  date: string | null
  model: string | null
}

const CELL: CSSProperties = { border: "1px solid var(--rule)", padding: "6px 8px", fontSize: 12 }

export function WindGridSheet({ site, date, model }: WindGridSheetProps) {
  const grid = useWindGrid(site, date, model)

  if (grid.isPending) return <Spinner />
  if (grid.isError) return <ErrorBox error={grid.error} onRetry={() => { void grid.refetch() }} />

  const data = grid.data
  // Сверху вниз по убыванию высоты — как в charts.wind_grid_png
  // (`list(reversed(grid["levels"]))`, «high altitude on top»); сортируем
  // явно, а не полагаемся на порядок ответа сервера (engine.wind_grid
  // отдаёт levels по ВОЗРАСТАНИЮ, engine.py:923).
  const levels = [...data.levels].sort((a, b) => b.alt_m_msl - a.alt_m_msl)

  return (
    <div>
      <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 0, marginBottom: 12 }}>
        Строки — высоты, столбцы — часы. Стрелка показывает, куда дует ветер; число — скорость, м/с.
        {/* Размер таблицы — из САМОГО ответа, а не подпись, обещанная заранее:
            уровней остаётся столько, сколько их выше старта плюс один
            ближайший снизу (engine.py:919-923), столбцов — сколько светлых
            часов у этой даты. Кнопка, ведущая сюда, обещала «6 уровней ×
            10 часов» и была неверна уже на фикстуре проекта, 5 × 16
            (финальное ревью ветки, I3). */}
        {" "}Здесь {levels.length} × {data.hours.length} — высот и часов светового дня.
      </p>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              <th scope="col" style={CELL} />
              {data.hours.map((hour) => (
                <th key={hour} scope="col" style={{ ...CELL, textAlign: "center" }}>{hour}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {levels.map((level) => (
              <tr
                key={level.label}
                data-launch={level.is_launch ? "true" : "false"}
                style={level.is_launch ? { background: "var(--air-wash)" } : undefined}
              >
                <th
                  scope="row"
                  style={{ ...CELL, textAlign: "left", fontWeight: level.is_launch ? 700 : 500 }}
                >
                  {level.label}
                  {level.is_launch ? " · старт" : ""}
                  <div style={{ fontSize: 10, color: "var(--faint)", fontWeight: 400 }}>
                    {level.alt_m_msl} м MSL
                  </div>
                </th>
                {data.hours.map((hour) => {
                  // Ищем по номеру часа, а не берём level.hourly[i] по индексу
                  // тем же порядковым номером, что и колонка заголовка: домен
                  // это гарантирует (engine.py:897-926 строит и hours, и
                  // hourly каждого уровня по ОДНОМУ И ТОМУ ЖЕ списку индексов
                  // day), но поиск по ключу не даёт рассинхрону строк и
                  // столбцов молча сдвинуть таблицу, если это когда-нибудь
                  // перестанет быть так — отсутствующий час просто рисует
                  // прочерк, а не съезжает на соседнюю колонку.
                  const cell = level.hourly.find((h) => h.hour === hour)
                  return (
                    <td
                      key={hour}
                      style={{ ...CELL, textAlign: "center" }}
                      title={cell ? `${fmtWind(cell.wind_ms)}, ${compass(cell.dir_deg)} ${cell.dir_deg}°` : undefined}
                    >
                      {cell ? (
                        <>
                          {/* Остриём вниз = азимут 180°; ветер дует В сторону dir+180,
                              поэтому поворот SVG равен dir (см. комментарий сверху). */}
                          <svg
                            viewBox="0 0 24 24"
                            width={14}
                            height={14}
                            aria-hidden="true"
                            style={{ transform: `rotate(${cell.dir_deg}deg)`, display: "block", margin: "0 auto" }}
                          >
                            <path
                              d="M12 3v18M12 21l-5-6M12 21l5-6"
                              style={{ stroke: "var(--ink)", fill: "none" }}
                              strokeWidth={2}
                            />
                          </svg>
                          <b style={{ fontSize: 12 }}>{fmtNum(cell.wind_ms, cell.wind_ms < 10 ? 1 : 0)}</b>
                        </>
                      ) : (
                        <span style={{ color: "var(--faint)" }}>—</span>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

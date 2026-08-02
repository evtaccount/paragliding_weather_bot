// Тело шторки «Карточка точки» — рисует уже загруженную точку маршрута
// (Route.tsx передаёт готовый RoutePoint, отдельного запроса нет — тот же
// приём, что и в MeteogramSheet). Раскладка и порядок строк — дословно из
// route.py:render_point_card (текст той же карточки для Telegram) и
// openPointCard (miniapp/prototype.html:1577-1631): бейдж балла, «Ограничивает»,
// вето, затем пары ключ-значение (ветер на высоте потолка / вдоль курса /
// поперёк / земля у старта и финиша / потоки / скорость по земле / база /
// рельеф / коридор / запас времени), CAPE·LI·CIN, облачность, видимость.
//
// «Что тянет вниз» (худшие субоценки) карточки в Telegram сюда НЕ перенесено:
// route.py:_worst_subs подписывает subs через criteria.PARAMS — словарь
// названий параметров, который существует только в бэкенде и не отдаётся ни
// одним эндпоинтом API. Показать subs здесь значило бы либо вывести сырые
// английские ключи (нарушает «весь текст интерфейса на русском»), либо
// завести свой словарь переводов в вебапе — вторую копию знания, которая
// молча разойдётся с criteria.py при следующей правке параметров (тот же
// риск, из-за которого WindGridSheet.tsx не переносит пороги раскраски
// ячеек, см. комментарий там).
//
// Ветер и его составляющие уже приходят в км/ч (RoutePoint.wind_along_kmh и
// т.д.), а вот наземный ветер («Земля») — из RouteWeather, в м/с (те же
// единицы, что во всём открытом прогнозе open-meteo) — конвертация тем же
// коэффициентом, что и route.py:ms_to_kmh.
import { colorOfCategory } from "../charts/palette"
import { MS_TO_KMH, ROLE_RU } from "../domain"
import { compass, fmtNum } from "../format"
import type { RoutePoint, RouteWeather } from "../api/types"

// ROLE_RU и MS_TO_KMH живут в ../domain — там же, где остальные копии
// значений питона, и под сверкой tests/test_webapp_sync.py: до неё
// переименование роли в route.py давало заголовок шторки вида
// «12,5 км · 14:30 · goal», и ни один тест этого не замечал (финальное ревью
// ветки, I4).
export function roleLabel(role: string): string {
  return ROLE_RU[role] ?? role
}

// `weather` — RouteWeather (40 ключей) либо `{}` без единого ключа (точка с
// eta:null, см. комментарий у RoutePoint.weather в api/types.ts). `key in w`
// сужает объединение без `any` и без падения на пустом объекте.
function weatherField<K extends keyof RouteWeather>(w: RoutePoint["weather"], key: K): RouteWeather[K] | null {
  return key in w ? (w as RouteWeather)[key] : null
}

function kv(label: string, value: string): { label: string; value: string } {
  return { label, value }
}

function windPair(deg: number | null, kmh: number | null): string {
  return deg === null || kmh === null ? "н/д" : `${fmtNum(kmh)} км/ч ${compass(deg)}`
}

function alongCrossPair(v: number | null): string {
  return v === null ? "н/д" : `${fmtNum(Math.abs(v))} км/ч ${v >= 0 ? "→" : "←"}`
}

function qty(v: number | null, unit: string, dec = 0): string {
  return v === null ? "н/д" : `${fmtNum(v, dec)} ${unit}`
}

// Без единицы измерения — для чисел, которые сами по себе индекс (CAPE,
// LI, CIN, проценты облачности), а не физическая величина с единицей.
function num(v: number | null, dec = 0): string {
  return v === null ? "н/д" : fmtNum(v, dec)
}

type PointCardSheetProps = { point: RoutePoint }

export function PointCardSheet({ point: p }: PointCardSheetProps) {
  const rows: { label: string; value: string }[] = []

  const windLabel = p.thermal_ceiling_m === null ? "Ветер" : `Ветер ${fmtNum(p.thermal_ceiling_m)} м`
  rows.push(kv(windLabel, windPair(p.wind_working_alt_dir, p.wind_working_alt_kmh)))
  rows.push(kv("  вдоль курса", alongCrossPair(p.wind_along_kmh)))
  rows.push(kv("  поперёк", alongCrossPair(p.wind_cross_kmh)))

  // Наземный ветер имеет смысл только там, где пилот стоит на земле — в
  // воздухе (enroute) он ни на что не влияет, показывать его — предлагать
  // решение по числу, которое не участвовало в оценке (тот же довод, что и
  // в route.py:render_point_card).
  if (p.role === "takeoff" || p.role === "goal") {
    const ground = weatherField(p.weather, "wind_speed_10m")
    const gust = weatherField(p.weather, "wind_gusts_10m")
    const groundText =
      ground === null ? "н/д" : `${fmtNum(ground * MS_TO_KMH)}${gust === null ? "" : `/${fmtNum(gust * MS_TO_KMH)}`} км/ч`
    rows.push(kv("Земля", groundText))
  }

  rows.push(kv("Потоки", qty(p.w_star_ms, "м/с", 1)))
  rows.push(kv("Скорость по земле", qty(p.effective_ground_speed_kmh, "км/ч")))
  rows.push(kv("База", qty(p.cloud_base_m, "м")))
  rows.push(kv("Рельеф", p.terrain_m === null ? "н/д" : `${fmtNum(p.terrain_m)} м${p.is_terrain_peak ? " ▲" : ""}`))
  rows.push(kv("Коридор", qty(p.working_band_m, "м")))
  rows.push(kv("Запас времени", qty(p.time_margin_min, "мин")))

  const cape = weatherField(p.weather, "cape")
  const li = weatherField(p.weather, "lifted_index")
  const cin = weatherField(p.weather, "convective_inhibition")
  const cloudLow = weatherField(p.weather, "cloud_cover_low")
  const cloudMid = weatherField(p.weather, "cloud_cover_mid")
  const precip = weatherField(p.weather, "precipitation")
  const vis = weatherField(p.weather, "visibility")

  return (
    <div>
      {p.score !== null && (
        <span
          style={{
            display: "inline-block", padding: "4px 9px", borderRadius: 7, fontSize: 13, fontWeight: 700,
            color: "var(--panel)", background: p.category === null ? "var(--faint)" : colorOfCategory(p.category),
          }}
        >
          {fmtNum(p.score, 1)}
        </span>
      )}

      {p.limiting !== null && (
        <p style={{ fontSize: 13, margin: "11px 0 4px" }}>
          <em>Ограничивает:</em> {p.limiting}
        </p>
      )}

      {p.vetoes.map((veto) => (
        <p key={veto} style={{ fontSize: 13, margin: "4px 0", color: "var(--faint)" }}>
          ⛔ {veto}
        </p>
      ))}

      {/* Раскладка пар — класс .kv из макета (prototype.html:378-383):
          моноширинный шрифт, разделители строк и tabular-nums, без которых
          числа в правой колонке не выстраиваются друг под другом. Инлайновых
          повторов тех же свойств здесь нет — они молча перебивали бы правила
          styles.css при следующей правке макета. */}
      <div className="kv" style={{ marginTop: 10 }}>
        {rows.map((row) => (
          <div key={row.label}>
            <span>{row.label}</span>
            <b>{row.value}</b>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 12, fontSize: 11.5, color: "var(--faint)" }}>
        CAPE {num(cape)} · LI {num(li, 1)} · CIN {num(cin)}
      </div>
      <div style={{ fontSize: 11.5, color: "var(--faint)" }}>
        Облачность {num(cloudLow)}/{num(cloudMid)} · дождь {qty(precip, "мм", 1)}
      </div>
      <div style={{ fontSize: 11.5, color: "var(--faint)" }}>
        Видимость {vis === null ? "н/д" : `${fmtNum(vis / 1000)} км`}
      </div>
    </div>
  )
}

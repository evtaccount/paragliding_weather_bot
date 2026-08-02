// Шторка «Сохранённые маршруты» — раскладка из макета (openSaved,
// miniapp/prototype.html:1766-1780).
//
// Хранится только геометрия: store держит точки маршрута ([[lat, lon, имя]]),
// а погода считается заново при каждом открытии (POST /api/route) — поэтому
// выбор маршрута здесь ничего не считает, а только отдаёт точки наверх.
//
// Удаления маршрута тут нет намеренно: макет его не предлагает, а в чате
// оно есть (/delroute, bot.py:1100) — тупика для пилота не возникает.
import { useSavedRoutes } from "../api/queries"
import { fmtPoints, fmtSavedDate } from "../format"
import type { RoutePointRow } from "../api/queries"
import type { SavedRoute } from "../api/types"
import { ErrorBox } from "../ui/ErrorBox"
import { Spinner } from "../ui/Spinner"

// SavedRoute.points — «сырая» форма хранения: список списков, у которого
// третий элемент бывает и строкой, и null (api/types.ts:SavedRoute;
// api.py:save_route пишет [[p.lat, p.lon, p.name]], а route.py:330 типизирует
// p.name как `str | None`). Расчёту маршрута нужна строгая тройка
// RoutePointRow, поэтому приведение живёт здесь, а не в типах.
//
// Проверка `typeof p[2] === "string"` не избыточна: без неё безымянная точка
// уехала бы в POST /api/route строкой "null" — а трек из GPX без подписей
// точек как раз такой (ревью задачи 13, N3: прежний комментарий называл тип
// неверно и звал эту проверку снять).
function toRows(points: SavedRoute["points"]): RoutePointRow[] {
  return points.map((p) => [Number(p[0]), Number(p[1]), typeof p[2] === "string" ? p[2] : null])
}

type Props = {
  onPick: (name: string, points: RoutePointRow[]) => void
}

export function SavedRoutesSheet({ onPick }: Props) {
  const routes = useSavedRoutes()

  if (routes.isPending) return <Spinner />
  if (routes.isError) return <ErrorBox error={routes.error} onRetry={() => { void routes.refetch() }} />

  if (routes.data.length === 0) {
    return (
      <div className="empty">
        <b>Пока пусто</b>
        Соберите маршрут в шторке «Новый маршрут» и сохраните его под именем.
      </div>
    )
  }

  return (
    <>
      <div className="pick">
        {routes.data.map((route) => (
          <button
            key={route.name}
            type="button"
            onClick={() => onPick(route.name, toRows(route.points))}
          >
            <b>{route.name}</b>
            {/* route.saved — полный ISO-таймстамп в UTC (api/types.ts:
                SavedRoute), поэтому дата собирается fmtSavedDate, а не
                печатается как есть: сырое значение дало бы в строке
                «2 точки · 2026-07-25T06:33:49+00:00», а срез до "T" —
                вчерашнее число всем, кто сохранил маршрут вечером. */}
            <s>{fmtPoints(route.points.length)} · {fmtSavedDate(route.saved)}</s>
          </button>
        ))}
      </div>
      <div className="attrib">Хранится только геометрия — погода считается заново при каждом открытии</div>
    </>
  )
}

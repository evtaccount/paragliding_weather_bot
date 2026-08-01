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
import type { RoutePointRow } from "../api/queries"
import type { SavedRoute } from "../api/types"
import { ErrorBox } from "../ui/ErrorBox"
import { Spinner } from "../ui/Spinner"

// SavedRoute.points описан по фикстуре как (number | string)[][] (api/
// types.ts) — форма «строка точки» там не сужена, а расчёту маршрута нужен
// именно RoutePointRow. Приведение живёт здесь, а не в типах: store пишет
// точки как [[p.lat, p.lon, p.name]] (api.py:save_route), где p.name —
// `str | None` (route.py:330), то есть третий элемент бывает и строкой, и
// null, и его нельзя просто привести к string.
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
            <s>{route.points.length} точек · {route.saved_at}</s>
          </button>
        ))}
      </div>
      <div className="attrib">Хранится только геометрия — погода считается заново при каждом открытии</div>
    </>
  )
}

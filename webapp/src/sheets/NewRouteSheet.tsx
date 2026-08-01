// Шторка «Новый маршрут» — три способа задать маршрут, все три уже понимает
// бот (макет: openNewRoute, miniapp/prototype.html:1781-1804):
//   1) точки на карте — тап ставит точку, перетаскивание её двигает;
//   2) список координат — по точке на строку, разбирает route.parse_text;
//   3) файл GPX или KML — разбирает route.parse_upload.
// В макете это три пункта меню-заглушки; здесь все три работают в одной
// шторке, потому что результат у них общий — список точек, который тут же
// видно на карте, и пилот может дособрать его руками (поставить точку после
// разбора трека, подвинуть неудачную).
//
// Карта получает И onTap, И onDragPoint: без второго MapView вообще не
// делает маркеры перетаскиваемыми (map/MapView.tsx, ре-ревью задачи 12) —
// пилот тащил бы пин, а маршрут считался бы по старым координатам.
//
// Пределы домена (сколько точек, какого размера файл, какое имя) здесь не
// продублированы числами: их проверяет сервер (api.py:_points_or_400,
// parse_route, store.name_error) и объясняет пилоту готовым текстом —
// ErrorBox показывает именно его. Своя проверка здесь одна, и она не про
// пределы: пустое имя не отправляется вовсе, чтобы не гонять заведомо
// отказной запрос ради текста, который и так известен. «Разобрать» с пустым
// полем при этом на сервер уходит — его ответ («Пришли файл GPX/KML или
// список координат») говорит, чего он ждёт от этого поля, и своей копии
// этого объяснения приложение не держит.
import { useMemo, useState } from "react"
import { useParseRoute, useSaveRoute, useSites } from "../api/queries"
import type { ParseRouteInput, RoutePointRow } from "../api/queries"
import type { Site } from "../api/types"
import { fmtNum } from "../format"
import { MapView } from "../map/MapView"
import { ErrorBox } from "../ui/ErrorBox"
import { Spinner } from "../ui/Spinner"

type Props = {
  // Отдаёт собранный маршрут наверх: точки и имя (null у безымянного —
  // api.py:RouteIn.name необязателен). Кто вызвал, тот и закрывает шторку.
  onApply: (points: RoutePointRow[], name: string | null) => void
}

// Пустой список стартов — константа модуля: MapView пересобирает маркеры при
// смене ССЫЛКИ на массив (см. комментарий в screens/Route.tsx).
const NO_SITES: Site[] = []

export function NewRouteSheet({ onApply }: Props) {
  const [points, setPoints] = useState<RoutePointRow[]>([])
  const [text, setText] = useState("")
  const [name, setName] = useState("")
  const [nameMissing, setNameMissing] = useState(false)
  // Что разбирали в последний раз — чтобы кнопка «Повторить» у ошибки
  // повторяла именно это, а не отправляла пустой запрос (файл после разбора
  // из поля ввода не достать: input type=file его не хранит между рендерами).
  const [lastParse, setLastParse] = useState<ParseRouteInput | null>(null)

  const sites = useSites()
  const parse = useParseRoute()
  const save = useSaveRoute()

  // Старты на карте — справочные: пилот собирает маршрут «от своего старта»,
  // и без них непонятно, где на карте он сам.
  const mapSites = sites.data ?? NO_SITES
  const mapPoints = useMemo(
    () => points.map((p, i) => ({ lat: p[0], lon: p[1], title: p[2] ?? `Точка ${i + 1}` })),
    [points],
  )

  function runParse(input: ParseRouteInput): void {
    setLastParse(input)
    // Разбор ЗАМЕНЯЕТ набор точек, а не дополняет его: пилот выбрал другой
    // источник маршрута, а не добавил трек к уже поставленным точкам.
    parse.mutate(input, { onSuccess: (data) => setPoints(data.points) })
  }

  function saveRoute(): void {
    const trimmed = name.trim()
    if (trimmed === "") {
      setNameMissing(true)
      return
    }
    setNameMissing(false)
    save.mutate({ name: trimmed, points })
  }

  return (
    <>
      <div className="map">
        <MapView
          points={mapPoints}
          sites={mapSites}
          onTap={(p) => setPoints((prev) => [...prev, [p.lat, p.lon, null]])}
          onDragPoint={(i, p) => setPoints((prev) => prev.map((row, j) => (j === i ? [p.lat, p.lon, row[2]] : row)))}
        />
      </div>
      <div className="attrib">Тап по карте ставит точку, перетаскивание её двигает</div>

      <label className="field">
        <span>Список координат — по точке на строку: широта, долгота, имя</span>
        <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="42.4776, 44.4787, старт" />
      </label>
      <button type="button" className="btn" onClick={() => runParse({ text })}>Разобрать</button>

      <label className="field">
        <span>Файл GPX или KML</span>
        <input
          type="file"
          accept=".gpx,.kml"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) runParse({ file })
          }}
        />
      </label>

      {parse.isPending && <Spinner />}
      {parse.isError && (
        <ErrorBox error={parse.error} onRetry={() => { if (lastParse) runParse(lastParse) }} />
      )}

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel__head">
          <span className="lbl">Точки</span>
          <span className="lbl">{points.length}</span>
        </div>
        {points.length === 0 ? (
          <div className="attrib">Пока ни одной — поставьте их на карте или разберите список/файл</div>
        ) : (
          <div className="kv">
            {points.map((p, i) => (
              // Ключ — по координатам и месту в списке: имена точек
              // повторяются (у половины треков их нет вовсе), а одинаковые
              // координаты в одном маршруте законны (замкнутый треугольник
              // возвращается в старт).
              <div key={`${i}-${p[0]}-${p[1]}`}>
                <span>{i + 1}. {p[2] ?? "без имени"}</span>
                <b>{fmtNum(p[0], 4)}, {fmtNum(p[1], 4)}</b>
              </div>
            ))}
          </div>
        )}
        {points.length > 0 && (
          <button type="button" className="btn" onClick={() => setPoints([])}>Очистить</button>
        )}
      </div>

      <label className="field">
        <span>Имя маршрута — под ним он попадёт в «Сохранённые»</span>
        <input type="text" value={name} onChange={(e) => { setName(e.target.value); setNameMissing(false) }} />
      </label>
      <button type="button" className="btn" onClick={saveRoute}>Сохранить</button>
      {nameMissing && (
        <div className="attrib" role="alert">Введите имя — без имени маршрут не сохранить.</div>
      )}
      {save.isPending && <Spinner />}
      {save.isError && <ErrorBox error={save.error} onRetry={saveRoute} />}
      {save.isSuccess && (
        <div className="attrib" role="status">
          Сохранён{save.data.overwritten ? " — прежний маршрут с этим именем заменён" : ""}
        </div>
      )}

      <button
        type="button"
        className="btn btn--primary"
        onClick={() => onApply(points, name.trim() === "" ? null : name.trim())}
      >
        Показать маршрут · {points.length} точек
      </button>
    </>
  )
}

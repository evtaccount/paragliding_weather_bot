// Обёртка над Leaflet: карта — приватность важнее прямого запроса к чужому
// тайловому серверу (см. Caddyfile и task-11-brief) — тайлы идут только
// через свой домен ("/tiles/{z}/{x}/{y}.png"), поэтому у tile.openstreetmap.org
// не остаётся ни адреса устройства пилота, ни района, куда он смотрит.
// Атрибуция OpenStreetMap внизу карты обязательна условиями использования
// данных — Leaflet рисует её сам через штатный attribution-контрол, здесь
// только передаётся текст.
//
// Карта создаётся один раз в эффекте при монтировании (пересоздавать её на
// каждый рендер незачем и дорого — Leaflet сам не умеет "обновить" карту
// другим набором опций). Маркеры точек маршрута и стартов — отдельные
// эффекты, каждый пересобирает свой набор при изменении соответствующего
// пропа, не трогая карту и маркеры другого набора.
import { useEffect, useRef } from "react"
import L from "leaflet"
import "leaflet/dist/leaflet.css"
import type { Site } from "../api/types"
import { routePointIcon, siteIcon } from "./pins"

export type LatLon = { lat: number; lon: number }

// Точка на карте — координаты плюс необязательная подпись. Подпись нужна
// потому, что Leaflet делает маркер клавиатурной кнопкой (Marker._initIcon
// при keyboard:true ставит role="button" и tabindex), а кнопка без имени —
// пустая строка для скринридера и для теста. В макете пин подписан «Точка N
// км, балл X» (prototype.html:1350), эту же подпись передаёт экран маршрута.
export type MapPoint = LatLon & { title?: string }

// Все три колбэка необязательны: экран «Маршрут» (screens/Route.tsx)
// показывает картой уже посчитанный маршрут и НЕ владеет его точками (они
// приходят пропом извне), поэтому ставить и двигать их ему нечем.
// Перетаскиваемый маркер без обработчика был бы враньём: он остался бы там,
// куда его бросили, хотя маршрут и его разбор не изменились. Поэтому без
// onDragPoint маркеры не перетаскиваются вовсе, а без onTap карта не
// слушает клик. Ставит и двигает точки шторка «Новый маршрут» (задача 13) —
// она передаёт оба колбэка. onPointTap — нажатие на сам пин: в макете это
// второй способ открыть карточку точки, наравне со строкой таблицы
// (prototype.html:1355).
type Props = {
  points: MapPoint[]
  sites: Site[]
  onTap?: (p: LatLon) => void
  onDragPoint?: (i: number, p: LatLon) => void
  onPointTap?: (i: number) => void
}

const TILE_URL = "/tiles/{z}/{x}/{y}.png"
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a>'
const TILE_MAX_ZOOM = 19

// Нет ни одной точки маршрута, ни одного старта (свежая установка) — карту
// всё равно нужно на что-то навести. Гудаури — старт по умолчанию бота (см.
// tests/fixtures.py и test/fixtures/sites.json).
const FALLBACK_CENTER: L.LatLngExpression = [42.47, 44.48]
const DEFAULT_ZOOM = 12

// Поля вокруг маршрута при подгонке области просмотра — чтобы крайние пины
// не липли к рамке карты и была видна трасса за ними.
const FIT_PADDING: L.PointExpression = [24, 24]

export function MapView({ points, sites, onTap, onDragPoint, onPointTap }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)

  // Колбэки в ref: родитель обычно передаёт новую функцию на каждый рендер,
  // а карту из-за этого пересоздавать не нужно — эффект создания карты
  // выполняется один раз (см. ниже), поэтому актуальные onTap/onDragPoint/
  // onPointTap читаются через ref, а не попадают в его зависимости.
  const onTapRef = useRef(onTap)
  const onDragPointRef = useRef(onDragPoint)
  const onPointTapRef = useRef(onPointTap)
  onTapRef.current = onTap
  onDragPointRef.current = onDragPoint
  onPointTapRef.current = onPointTap

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const first = points[0] ?? sites[0]
    const center: L.LatLngExpression = first ? [first.lat, first.lon] : FALLBACK_CENTER

    const map = L.map(container)
    // Область просмотра — по всему маршруту, а не по его первой точке.
    // Наводка на первую точку с постоянным зумом показывает окрестности
    // старта: на route.json (40 км строго на юг, широта 42,5) зум 12 — это
    // 28 м/пиксель, то есть около 10 × 7,6 км в рамке 4/3, и четыре пина из
    // пяти оказываются за краем (ре-ревью task-12, N1).
    //
    // Подгонка требует известного размера контейнера (Leaflet берёт его из
    // clientWidth/clientHeight): при нулевом размере getBoundsZoom считает
    // масштаб от отрицательной ширины и даёт NaN. Ноль бывает не только в
    // jsdom: неактивная вкладка приложения скрыта через `display: none`
    // (styles.css, `.view[hidden]`), и карта, созданная в этот момент,
    // размера не имеет. Тогда — прежняя наводка на первую точку, а не
    // сломанный масштаб.
    const size = map.getSize()
    const canFit = points.length >= 2 && size.x > 0 && size.y > 0
    if (canFit) {
      map.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lon])), { padding: FIT_PADDING })
    } else {
      map.setView(center, DEFAULT_ZOOM)
    }
    L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION, maxZoom: TILE_MAX_ZOOM }).addTo(map)

    map.on("click", (e: L.LeafletMouseEvent) => {
      onTapRef.current?.({ lat: e.latlng.lat, lon: e.latlng.lng })
    })

    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
    }
    // Карта создаётся один раз при монтировании — сюда намеренно не входят
    // ни points/sites (нужны только для НАЧАЛЬНОЙ области просмотра: центра
    // или подгонки под маршрут; дальше её двигает пилот, и переставлять её
    // под каждую правку точек значило бы отменять его жест), ни onTap
    // (читается через ref).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Маркеры стартов — справочные, неподвижные, пересобираются при смене sites.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const markers = sites.map((s) => {
      const marker = L.marker([s.lat, s.lon], { icon: siteIcon(), keyboard: false })
      marker.bindTooltip(s.name)
      marker.addTo(map)
      return marker
    })

    return () => {
      for (const m of markers) m.remove()
    }
  }, [sites])

  // Трасса и маркеры точек маршрута — один набор, пересобирается при смене
  // points. Трасса (в макете её рисует drawMap, prototype.html:1339-1342) —
  // единственное, что показывает ПОРЯДОК точек: без линии пять одинаковых
  // пинов не читаются как маршрут. Цвет линии — не свойство Leaflet, а класс
  // .pgbot-track в styles.css (var(--ink)): цвета в этом проекте живут
  // только в CSS-переменных темы и в charts/palette.ts.
  // interactive: false — линия не должна перехватывать нажатия у пинов.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const draggable = onDragPointRef.current !== undefined

    // Отрисовщик задан явно (new L.SVG()), а не оставлен на автовыбор:
    // фабрика L.svg() отдаёт слой только если у браузера есть
    // createSVGRect (Browser.svg) — проверка времён VML и IE8. Там, где её
    // нет, Leaflet возвращает null, и добавление линии роняет всю карту
    // (`Cannot use 'in' operator to search for '_leaflet_id' in null`) —
    // ровно это и происходит в jsdom, где идут тесты карты.
    const track =
      points.length >= 2
        ? L.polyline(points.map((p) => [p.lat, p.lon] as L.LatLngTuple), {
            className: "pgbot-track", interactive: false, renderer: new L.SVG(),
          }).addTo(map)
        : null

    const markers = points.map((p, i) => {
      const marker = L.marker([p.lat, p.lon], { icon: routePointIcon(), draggable, title: p.title })
      marker.on("dragend", () => {
        const pos = marker.getLatLng()
        onDragPointRef.current?.(i, { lat: pos.lat, lon: pos.lng })
      })
      marker.on("click", () => onPointTapRef.current?.(i))
      marker.addTo(map)
      return marker
    })

    return () => {
      track?.remove()
      for (const m of markers) m.remove()
    }
  }, [points])

  return <div ref={containerRef} className="pgbot-map" style={{ width: "100%", height: "100%" }} />
}

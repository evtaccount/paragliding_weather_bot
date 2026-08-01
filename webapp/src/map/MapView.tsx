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

// onTap/onDragPoint необязательны: экран «Маршрут» (screens/Route.tsx)
// показывает картой уже посчитанный маршрут и НЕ владеет его точками (они
// приходят пропом извне), поэтому ставить и двигать их ему нечем.
// Перетаскиваемый маркер без обработчика был бы враньём: он остался бы там,
// куда его бросили, хотя маршрут и его разбор не изменились. Поэтому без
// onDragPoint маркеры не перетаскиваются вовсе, а без onTap карта не
// слушает клик. Ставит и двигает точки шторка «Новый маршрут» (задача 13) —
// она передаёт оба колбэка.
type Props = {
  points: LatLon[]
  sites: Site[]
  onTap?: (p: LatLon) => void
  onDragPoint?: (i: number, p: LatLon) => void
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

export function MapView({ points, sites, onTap, onDragPoint }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)

  // Колбэки в ref: родитель обычно передаёт новую функцию на каждый рендер,
  // а карту из-за этого пересоздавать не нужно — эффект создания карты
  // выполняется один раз (см. ниже), поэтому актуальные onTap/onDragPoint
  // читаются через ref, а не попадают в его зависимости.
  const onTapRef = useRef(onTap)
  const onDragPointRef = useRef(onDragPoint)
  onTapRef.current = onTap
  onDragPointRef.current = onDragPoint

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const first = points[0] ?? sites[0]
    const center: L.LatLngExpression = first ? [first.lat, first.lon] : FALLBACK_CENTER

    const map = L.map(container).setView(center, DEFAULT_ZOOM)
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
    // ни points/sites (нужны только для начального центра), ни onTap
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

  // Маркеры точек маршрута — перетаскиваемые (только когда есть кому отдать
  // новое положение, см. Props), пересобираются при смене points.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const draggable = onDragPointRef.current !== undefined

    const markers = points.map((p, i) => {
      const marker = L.marker([p.lat, p.lon], { icon: routePointIcon(), draggable })
      marker.on("dragend", () => {
        const pos = marker.getLatLng()
        onDragPointRef.current?.(i, { lat: pos.lat, lon: pos.lng })
      })
      marker.addTo(map)
      return marker
    })

    return () => {
      for (const m of markers) m.remove()
    }
  }, [points])

  return <div ref={containerRef} className="pgbot-map" style={{ width: "100%", height: "100%" }} />
}

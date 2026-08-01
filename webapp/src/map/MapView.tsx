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
// слушает клик. Ставит и двигает точки шторка «Новый маршрут»
// (sheets/NewRouteSheet.tsx) — она передаёт оба колбэка. onPointTap — нажатие на сам пин: в макете это
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

// Центр «пока смотреть больше не на что»: первая точка маршрута, иначе
// первый старт, иначе Гудаури.
function centerOf(points: MapPoint[], sites: Site[]): L.LatLngExpression {
  const first = points[0] ?? sites[0]
  return first ? [first.lat, first.lon] : FALLBACK_CENTER
}

// Область просмотра — по ВСЕМУ маршруту, а не по его первой точке. Наводка
// на первую точку с постоянным зумом показывает окрестности старта: на
// route.json (40 км строго на юг, широта 42,5) зум 12 — это 28 м/пиксель, то
// есть около 10 × 7,6 км в рамке 4/3, и четыре пина из пяти оказываются за
// краем (ре-ревью task-12, N1). Маршрута нет — остаётся наводка на точку.
function applyInitialView(map: L.Map, points: MapPoint[], sites: Site[]): void {
  if (points.length >= 2) {
    map.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lon])), { padding: FIT_PADDING })
    return
  }
  map.setView(centerOf(points, sites), DEFAULT_ZOOM)
}

// Размер контейнера, каким его видит Leaflet (он берёт его из
// clientWidth/clientHeight). Ноль — обычное состояние, а не экзотика: все
// четыре экрана приложения смонтированы одновременно, а неактивные скрыты
// атрибутом hidden (App.tsx + styles.css, `.view[hidden] { display: none }`).
function hasSize(el: HTMLElement): boolean {
  return el.clientWidth > 0 && el.clientHeight > 0
}

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

  // Поставлена ли НАСТОЯЩАЯ область просмотра (при известном размере
  // контейнера). false означает, что карта живёт на временной наводке и
  // подгонку ещё предстоит сделать — см. эффект отложенной подгонки ниже.
  const viewFittedRef = useRef(false)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    // Отрисовщик векторных слоёв — ОДИН на карту, опцией: Leaflet добавляет
    // отрисовщик на карту слоем (Path.beforeAdd → map.addLayer(renderer)), а
    // снятие пути его не снимает, поэтому свой L.SVG() у каждой трассы
    // копился бы пустыми <svg> в overlay-слое — по одному на каждый перебор
    // времени вылета и на каждое перетаскивание точки (ре-ревью task-12,
    // N10: пять смен точек давали шесть <svg> при одном <path>).
    //
    // Задан явно, а не оставлен на автовыбор: фабрика L.svg() отдаёт слой
    // только если у браузера есть createSVGRect (Browser.svg) — проверка
    // времён VML и IE8. Там, где её нет, Leaflet возвращает null и добавление
    // линии роняет всю карту («Cannot use 'in' operator to search for
    // '_leaflet_id' in null») — ровно это и происходит в jsdom, где идут
    // тесты карты. В браузере L.svg() возвращает ровно new SVG(options), так
    // что путь остаётся тем же самым.
    const map = L.map(container, { renderer: new L.SVG() })

    // Карте нужен центр раньше слоёв (без него Leaflet не даёт их добавить),
    // поэтому сначала — временная наводка, а настоящая область просмотра
    // ставится только при известном размере контейнера: при нулевом размере
    // getBoundsZoom возвращает Infinity (проверено пробником ре-ревью,
    // task-12 N12), и fitBounds уводит карту в максимальный зум.
    map.setView(centerOf(points, sites), DEFAULT_ZOOM)
    if (hasSize(container)) {
      applyInitialView(map, points, sites)
      viewFittedRef.current = true
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

  // Отложенная подгонка: карта, созданная в скрытой вкладке, о своём размере
  // сама не узнаёт никогда. Все четыре экрана смонтированы с первого рендера
  // приложения, неактивные скрыты через hidden/display:none (App.tsx,
  // styles.css `.view[hidden]`) — значит обычный путь такой: пилот стоит на
  // «Прогнозе», маршрут посчитан, карта создана в контейнере 0×0. Leaflet
  // кэширует размер и после показа вкладки продолжает считать его нулевым
  // (проверено пробником ре-ревью task-12, N8: {"x":0,"y":0} и до, и после
  // показа, правду возвращает только invalidateSize) — тайлы не запрашиваются,
  // пины и трасса лежат в углу, и так до конца сеанса.
  //
  // Зависимостей у эффекта намеренно нет: смена вкладки перерисовывает всё
  // поддерево (`tab` — состояние ShellContent в App.tsx), и проверка размера
  // после каждого рендера — самый дешёвый способ заметить, что контейнер
  // наконец его получил. ResizeObserver сюда не заводится не потому, что его
  // нельзя проверить (подставной globalThis.ResizeObserver с ручным вызовом
  // колбэка — обычный приём и в jsdom работает), а потому что наблюдатель
  // ради ОДНОГО перехода 0 → размер избыточен.
  //
  // Цена этого выбора: путь App → ... → MapView должен перерисовываться при
  // смене вкладки. Сегодня так и есть (memo в проекте не используется нигде),
  // но React.memo на любом звене этого пути — и карта, созданная скрытой,
  // снова останется 0×0 навсегда. Тогда нужен наблюдатель размера, а не этот
  // эффект.
  //
  // Срабатывает эффект ровно один раз: после подгонки viewFittedRef закрывает
  // путь, иначе каждый следующий рендер (открытие карточки точки, новый ответ
  // после чипа вылета, смена вкладки) отменял бы сдвиг и зум, сделанные
  // пилотом — проверено мутацией «убрать страж» (ре-ревью task-12, N13:
  // карта откатывалась с 43.9/45.9 зум 14 обратно к подгонке).
  useEffect(() => {
    const map = mapRef.current
    const container = containerRef.current
    if (!map || !container || viewFittedRef.current || !hasSize(container)) return
    viewFittedRef.current = true
    map.invalidateSize()
    applyInitialView(map, points, sites)
  })

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

    // Своего отрисовщика у линии нет — она рисуется общим для карты (см.
    // опцию renderer в эффекте создания и разбор там же, почему он один).
    const track =
      points.length >= 2
        ? L.polyline(points.map((p) => [p.lat, p.lon] as L.LatLngTuple), {
            className: "pgbot-track", interactive: false,
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

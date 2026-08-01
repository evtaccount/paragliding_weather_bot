// Leaflet в jsdom реально создаёт карту (проверено отдельным прогоном перед
// написанием этого файла): контейнер получает нулевой размер, но это не
// мешает — тайловый слой всё равно создаёт <img> с готовым src, маркеры
// рисуются как div с классом leaflet-marker-icon, а клик по контейнеру
// Leaflet всё равно переводит в LatLng через текущие центр/зум карты, без
// реальной раскладки экрана. Поэтому тесты не мокают leaflet — они проверяют
// поведение обёртки на настоящей библиотеке, только не полагаются на
// конкретные пиксельные координаты (см. task-11-brief: «тесты проверяют не
// отрисовку, а поведение обёртки»).
import { render } from "@testing-library/react"
import { StrictMode } from "react"
import { expect, test, vi } from "vitest"
import L from "leaflet"
import { MapView } from "./MapView"
import type { Site } from "../api/types"
import sitesFixture from "../../test/fixtures/sites.json"

const SITES = sitesFixture as Site[]

// jsdom не раскладывает элементы: clientWidth/clientHeight контейнера всегда
// 0, а Leaflet считает по ним и область просмотра, и положение маркеров.
// Пока размера нет, проверить «видно ли точку» нечем — DOM маркера создаётся
// независимо от того, попадает ли он в видимую область (ре-ревью task-12,
// N1). Подделываем размер на время одного теста, возвращая исходные
// дескрипторы: они объявлены на Element.prototype, и оставить их
// переопределёнными значило бы менять поведение jsdom для всех тестов файла.
function withContainerSize<T>(width: number, height: number, body: () => T): T {
  const saved = (["clientWidth", "clientHeight"] as const).map(
    (name) => [name, Object.getOwnPropertyDescriptor(Element.prototype, name)] as const,
  )
  Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => width })
  Object.defineProperty(Element.prototype, "clientHeight", { configurable: true, get: () => height })
  try {
    return body()
  } finally {
    for (const [name, descriptor] of saved) {
      if (descriptor) Object.defineProperty(Element.prototype, name, descriptor)
      else delete (Element.prototype as unknown as Record<string, unknown>)[name]
    }
  }
}

// Положение маркера в пикселях контейнера (при нулевом смещении панели слоёв
// это прямо координаты видимой области). Leaflet кладёт его либо в
// transform: translate3d(...), либо в left/top — выбор делает DomUtil по
// Browser.any3d, а тот в jsdom ложный (нет ни WebKitCSSMatrix, ни
// MozPerspective), так что читаются оба варианта, а не только один.
function markerXY(icon: Element): { x: number; y: number } {
  const style = (icon as HTMLElement).style
  const transform = /translate3?d?\((-?[\d.]+)px,\s*(-?[\d.]+)px/.exec(style.transform)
  if (transform) return { x: Number(transform[1]), y: Number(transform[2]) }
  if (style.left !== "" && style.top !== "") return { x: parseFloat(style.left), y: parseFloat(style.top) }
  throw new Error(`У маркера нет положения: transform="${style.transform}", left="${style.left}"`)
}

test("тап по карте отдаёт координаты наверх", async () => {
  const onTap = vi.fn()
  const { container } = render(
    <MapView points={[]} sites={[]} onTap={onTap} onDragPoint={() => {}} />,
  )
  const mapEl = container.querySelector(".leaflet-container")
  expect(mapEl).not.toBeNull()
  mapEl!.dispatchEvent(new MouseEvent("click", { clientX: 10, clientY: 10, bubbles: true, cancelable: true }))

  expect(onTap).toHaveBeenCalledTimes(1)
  const point = onTap.mock.calls[0]?.[0] as { lat: number; lon: number }
  expect(typeof point.lat).toBe("number")
  expect(typeof point.lon).toBe("number")
})

test("на карте столько маркеров, сколько точек", () => {
  const points = [
    { lat: 42.47, lon: 44.48 },
    { lat: 42.5, lon: 44.5 },
    { lat: 42.6, lon: 44.6 },
  ]
  const { container } = render(
    <MapView points={points} sites={[]} onTap={() => {}} onDragPoint={() => {}} />,
  )
  expect(container.querySelectorAll(".leaflet-marker-icon").length).toBe(points.length)
})

test("тайлы берутся у своего домена", () => {
  const { container } = render(
    <MapView points={[]} sites={SITES} onTap={() => {}} onDragPoint={() => {}} />,
  )
  const tile = container.querySelector("img.leaflet-tile")
  expect(tile).not.toBeNull()
  expect(tile!.getAttribute("src")).toMatch(/^\/tiles\//)
})

// Ревью task-11: main.tsx оборачивает всё приложение в <StrictMode>
// безусловно (действует при каждом npm run dev, см. те же тесты у
// App.test.tsx/sheets.test.tsx про повторный вызов эффекта). MapView создаёт
// внешний объект (L.map) в эффекте — под <StrictMode> React в деве
// синхронно монтирует-размонтирует-монтирует компонент заново, и это самое
// место для второй карты поверх первой, если эффект очистки не удалит
// прежнюю карту и её слушатели. Живого дефекта на сегодня нет — тест
// закрепляет это, чтобы правка эффекта его не внесла молча.
test("под строгим режимом разработки карта не плодится и клик срабатывает один раз", () => {
  const onTap = vi.fn()
  const points = [{ lat: 42.47, lon: 44.48 }, { lat: 42.5, lon: 44.5 }]
  const { container, unmount } = render(
    <StrictMode>
      <MapView points={points} sites={SITES} onTap={onTap} onDragPoint={() => {}} />
    </StrictMode>,
  )

  expect(container.querySelectorAll(".leaflet-container").length).toBe(1)
  expect(container.querySelectorAll(".leaflet-marker-icon").length).toBe(points.length + SITES.length)

  const mapEl = container.querySelector(".leaflet-container")!
  mapEl.dispatchEvent(new MouseEvent("click", { clientX: 5, clientY: 5, bubbles: true, cancelable: true }))
  expect(onTap).toHaveBeenCalledTimes(1)

  expect(() => unmount()).not.toThrow()
  expect(container.querySelectorAll(".leaflet-container").length).toBe(0)
})

// Те же координаты, что в test/fixtures/route.json: Гудаури и 40 км строго на
// юг пятью точками.
const ROUTE_POINTS = [
  { lat: 42.4776, lon: 44.4787 },
  { lat: 42.3877, lon: 44.4787 },
  { lat: 42.2978, lon: 44.4787 },
  { lat: 42.2079, lon: 44.4787 },
  { lat: 42.118, lon: 44.4787 },
]
const VIEW_W = 360
const VIEW_H = 270

// Маршрут должен не просто ПОМЕЩАТЬСЯ в кадр, но и ЗАНИМАТЬ его: «все пины
// внутри» одинаково верно и для настоящей подгонки, и для карты на
// пол-Европы, где маршрут — несколько пикселей в середине (ре-ревью task-12,
// N9: мутации «подмешать в границы точку [0,0]» и «setView(center, 3)» такую
// проверку проходили). На настоящей подгонке пины занимают 46…223 из 270 —
// порог в половину кадра оставляет запас на дискретность зума Leaflet.
function expectRouteFillsFrame(container: Element): void {
  const icons = [...container.querySelectorAll(".leaflet-marker-icon")]
  expect(icons).toHaveLength(ROUTE_POINTS.length)
  const xy = icons.map(markerXY)

  // Допуск — половина пина (iconAnchor в pins.ts сдвигает элемент на 8 px):
  // проверяется, что точка попала в кадр, а не пиксельная раскладка.
  const slack = 8
  for (const { x, y } of xy) {
    expect(x).toBeGreaterThanOrEqual(-slack)
    expect(x).toBeLessThanOrEqual(VIEW_W + slack)
    expect(y).toBeGreaterThanOrEqual(-slack)
    expect(y).toBeLessThanOrEqual(VIEW_H + slack)
  }

  const spanX = Math.max(...xy.map((p) => p.x)) - Math.min(...xy.map((p) => p.x))
  const spanY = Math.max(...xy.map((p) => p.y)) - Math.min(...xy.map((p) => p.y))
  expect(Math.max(spanX / VIEW_W, spanY / VIEW_H)).toBeGreaterThan(0.5)
}

// Ре-ревью task-12 (N1): карта наводилась на ПЕРВУЮ точку с постоянным зумом
// 12, а подгонки под маршрут не было нигде. На маршруте из route.json (40 км
// на юг) это 28 м/пиксель: в рамке 4/3 шириной 360 px видно ~10 × 7,6 км, и
// пины 10/20/30/40 км лежат за нижним краем на 6/16/26/36 км — пилот видит
// один пин из пяти. Счёт маркеров такой дефект не ловит (DOM маркера
// создаётся независимо от области просмотра), поэтому тест смотрит на их
// ПОЛОЖЕНИЕ в пикселях контейнера.
test("карта охватывает весь маршрут, а не окрестности первой точки", () => {
  withContainerSize(VIEW_W, VIEW_H, () => {
    const { container } = render(
      <MapView points={ROUTE_POINTS} sites={[]} onTap={() => {}} onDragPoint={() => {}} />,
    )
    expectRouteFillsFrame(container)
    // Трасса — здесь же, в тестах самой карты: раньше её проверял только
    // тест экрана, и мутация «трасса не рисуется» оставляла map.test.tsx
    // целиком зелёным (ре-ревью task-12, N12).
    expect(container.querySelector("path.pgbot-track")).not.toBeNull()
  })
})

// Ре-ревью task-12 (N8): все четыре экрана приложения смонтированы с первого
// рендера, а неактивные скрыты через hidden/display:none (App.tsx,
// styles.css `.view[hidden]`). Обычный путь поэтому такой: пилот стоит на
// «Прогнозе», маршрут уже посчитан, и карта создаётся в контейнере 0×0.
// Leaflet кэширует размер и при показе вкладки о нём не узнаёт сам — без
// отложенной подгонки пилот до конца сеанса видит пустую рамку.
test("карта, созданная в скрытой вкладке, подгоняется при её показе", () => {
  // Размер по умолчанию в jsdom — 0×0, как у скрытой вкладки.
  const { container, rerender } = render(<MapView points={ROUTE_POINTS} sites={[]} />)
  expect(container.querySelector(".leaflet-container")).not.toBeNull()

  // Вкладку показали: контейнер получил размер, дерево перерисовалось.
  withContainerSize(VIEW_W, VIEW_H, () => {
    rerender(<MapView points={ROUTE_POINTS} sites={[]} />)
    expectRouteFillsFrame(container)
  })
})

// Ре-ревью task-12 (N13): подгонка обязана быть ОДНОРАЗОВОЙ. Эффект
// отложенной подгонки выполняется после каждого рендера, а рендеров у экрана
// маршрута много (открытие карточки точки, новый ответ после чипа вылета,
// смена вкладки) — без стража viewFittedRef каждый из них возвращал бы карту
// к подгонке, и пилот, приблизивший её к узкому месту, терял бы вид от любого
// касания таблицы. Проверено пробником ре-ревьюера: с убранным стражем
// карта после жеста (43.9/45.9, зум 14) откатывалась к 42.298/44.479, зум 9.
//
// Чтобы «сделать жест», нужен сам объект карты — единственный способ до него
// добраться снаружи — перехватить L.map (Leaflet нигде не публикует
// созданную карту). Это тот же приём, которым дефект и воспроизведён; вся
// остальная работа идёт на настоящем Leaflet, как и в прочих тестах файла.
test("подгонка одноразовая: жест пилота не отменяется перерисовкой", () => {
  const createMap = L.map
  let map: L.Map | null = null
  const spy = vi.spyOn(L, "map").mockImplementation(((el: HTMLElement | string, options?: L.MapOptions) => {
    map = createMap(el as HTMLElement, options)
    return map
  }) as typeof L.map)

  try {
    withContainerSize(VIEW_W, VIEW_H, () => {
      const { rerender } = render(<MapView points={ROUTE_POINTS} sites={[]} />)
      expect(map).not.toBeNull()

      // Пилот приблизил карту к своему узкому месту.
      map!.setView([43.9, 45.9], 14)
      const center = map!.getCenter()
      const zoom = map!.getZoom()

      // Экран перерисовался дважды — с новой ссылкой на точки, как после
      // каждого пересчёта маршрута.
      rerender(<MapView points={[...ROUTE_POINTS]} sites={[]} />)
      rerender(<MapView points={[...ROUTE_POINTS]} sites={[]} />)

      expect(map!.getZoom()).toBe(zoom)
      expect(map!.getCenter().lat).toBeCloseTo(center.lat, 6)
      expect(map!.getCenter().lng).toBeCloseTo(center.lng, 6)
    })
  } finally {
    spy.mockRestore()
  }
})

// Ре-ревью task-12 (N10): свой L.SVG() у каждой трассы копился в DOM —
// Leaflet добавляет отрисовщик слоем, а снятие пути его не снимает (пробник:
// пять смен точек → шесть <svg> при одном <path>). На экране маршрута новая
// ссылка на точки приходит с каждым перебором времени вылета, в задаче 13 —
// с каждым перетаскиванием точки.
test("смена точек не плодит отрисовщики в слое карты", () => {
  const { container, rerender } = render(<MapView points={ROUTE_POINTS} sites={[]} />)
  for (let i = 0; i < 3; i += 1) {
    // Новая ССЫЛКА на тот же набор — именно так приходит result.points после
    // каждого пересчёта маршрута.
    rerender(<MapView points={[...ROUTE_POINTS]} sites={[]} />)
  }

  expect(container.querySelectorAll(".leaflet-overlay-pane svg")).toHaveLength(1)
  expect(container.querySelectorAll("path.pgbot-track")).toHaveLength(1)
})

// Ре-ревью task-12 (N6): необязательный onDragPoint (правка круга 1) ничем не
// закреплён — возврат безусловного `draggable: true` оставлял весь прогон
// зелёным. Сценарий отказа: на экране маршрута пилот тащит пин, пин уезжает и
// остаётся на новом месте, а маршрут, таблица, разрез и разбор посчитаны по
// старым координатам.
test("без обработчика перетаскивания пин не перетаскивается", () => {
  const point = { lat: 42.47, lon: 44.48 }
  const { container } = render(<MapView points={[point]} sites={[]} />)

  const icon = container.querySelector(".leaflet-marker-icon") as HTMLElement
  expect(icon).not.toBeNull()
  expect(icon.className).not.toContain("leaflet-marker-draggable")

  // Та же последовательность, что двигает пин в тесте ниже (с `which: 1`), —
  // положение маркера от неё не меняется.
  const before = icon.style.transform
  const opts = (x: number, y: number): MouseEventInit =>
    ({ bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, which: 1 }) as MouseEventInit
  icon.dispatchEvent(new MouseEvent("mousedown", opts(0, 0)))
  document.body.dispatchEvent(new MouseEvent("mousemove", opts(40, 20)))
  document.body.dispatchEvent(new MouseEvent("mouseup", opts(40, 20)))

  expect(icon.style.transform).toBe(before)
})

// Ревью task-11 (повторное): перетаскивание точки маршрута — единственный
// непроверенный путь интерфейса карты, и именно на нём построены задачи 12
// и 13 (там точки маршрута двигают пальцем). Первая попытка (только
// mousedown/mousemove/mouseup с button:0) молчала — dragend не наступал.
// Причина: Leaflet (Draggable._onDown) отсеивает нажатие по условию
// `(e.which !== 1) && (e.button !== 1) && !e.touches`, а конструктор
// MouseEvent в jsdom не заполняет устаревшее свойство `which` из `button`.
// Рецепт (найден ре-ревьюером, проверен дважды): добавить `which: 1` к
// каждому событию нажатия/движения/отпускания и слать движение с
// отпусканием на document.body, а не на голый document (иначе jsdom падает
// внутри DomUtil.getClass — цель события не должна быть самим документом).
// Ни компонент, ни внутренности Leaflet при этом не трогаются.
test("перетаскивание точки отдаёт координаты наверх", () => {
  const onDragPoint = vi.fn()
  const point = { lat: 42.47, lon: 44.48 }
  const { container } = render(
    <MapView points={[point]} sites={[]} onTap={() => {}} onDragPoint={onDragPoint} />,
  )

  const icon = container.querySelector(".leaflet-marker-icon") as HTMLElement
  expect(icon).not.toBeNull()

  const opts = (x: number, y: number): MouseEventInit =>
    ({ bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, which: 1 }) as MouseEventInit
  icon.dispatchEvent(new MouseEvent("mousedown", opts(0, 0)))
  document.body.dispatchEvent(new MouseEvent("mousemove", opts(40, 20)))
  document.body.dispatchEvent(new MouseEvent("mouseup", opts(40, 20)))

  expect(onDragPoint).toHaveBeenCalledTimes(1)
  const [index, dragged] = onDragPoint.mock.calls[0] as [number, { lat: number; lon: number }]
  expect(index).toBe(0)
  expect(typeof dragged.lat).toBe("number")
  expect(typeof dragged.lon).toBe("number")
  // Не просто вызван — реально сдвинут: координата после перетаскивания
  // отличается от исходной точки, а не эхо того же значения.
  expect(dragged).not.toEqual(point)
})

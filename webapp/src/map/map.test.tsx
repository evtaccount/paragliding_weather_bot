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
import { MapView } from "./MapView"
import type { Site } from "../api/types"
import sitesFixture from "../../test/fixtures/sites.json"

const SITES = sitesFixture as Site[]

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

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

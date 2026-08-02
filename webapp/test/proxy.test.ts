// Прокси разработки исполняется, а не читается глазами: rewrite — обычная
// функция, и её ответ на настоящий адрес тайла виден прямо здесь.
//
// Проверяется ЭТОТ набор, а не конфигурация, которую читают серверы Vite: то,
// что vite.config.ts берёт набор отсюда, а не держит свой литерал, сторожит
// tests/test_deploy_config.py (разбор — там же, в
// test_vite_config_takes_the_dev_proxy_from_one_place).
import { describe, expect, it } from "vitest"

import { API_PROXY } from "../dev-proxy"

// Шаблон адреса тайла живёт в webapp/src/map/MapView.tsx (TILE_URL) — импортом
// его сюда не затащить: MapView тянет Leaflet и React, то есть половину
// приложения ради одной строки. Совпадение этой копии с настоящим шаблоном (и
// с регулярным выражением в Caddyfile) сторожит tests/test_deploy_config.py.
const TILE_URL = "/tiles/{z}/{x}/{y}.png"

const tiles = API_PROXY["/tiles"]

describe("прокси тайлов в разработке", () => {
  it("срезает префикс /tiles, как это делает Caddy в проде", () => {
    const url = TILE_URL.replace("{z}", "10").replace("{x}", "637").replace("{y}", "380")
    expect(tiles.rewrite(url)).toBe("/10/637/380.png")
  })

  it("ведёт на тайловый сервер, а не на свой бэкенд", () => {
    // Здесь стоял адрес бэкенда (127.0.0.1:8080), у которого такого маршрута
    // нет вовсе: проба против настоящего api.app дала 404 на каждый тайл, то
    // есть карта и в `npm run dev`, и в `vite preview` (на нём стоят все
    // восемь сквозных сценариев) рисовалась без подложки. Сценарии этого не
    // видели: webapp/e2e/fixtures.ts подменяет тайлы пикселем.
    expect(tiles.target).not.toContain("127.0.0.1")
    expect(tiles.target).toContain("tile.openstreetmap.org")
  })

  it("называет себя в User-Agent, как требуют правила OpenStreetMap", () => {
    expect(tiles.headers["User-Agent"]).toMatch(/paragliding-bot-miniapp/)
  })

  it("оставляет /api на своём бэкенде", () => {
    expect(API_PROXY["/api"]).toBe("http://127.0.0.1:8080")
  })
})

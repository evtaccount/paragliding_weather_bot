import prefs from "../../test/fixtures/prefs.json"
import sites from "../../test/fixtures/sites.json"
import facts from "../../test/fixtures/facts_1d.json"
import grid from "../../test/fixtures/wind_grid.json"
import overview from "../../test/fixtures/overview_3d.json"
import scan from "../../test/fixtures/scan.json"
import routes from "../../test/fixtures/routes.json"
import type { Prefs, Site, Facts, WindGrid, OverviewRow, Scan, SavedRoute } from "./types"

/* Проверка на этапе компиляции: `tsc --noEmit` в npm run build упадёт, если тип
   разошёлся с настоящим ответом. Тело теста нужно, чтобы файл считался тестом. */
test("фикстуры описываются типами", () => {
  const p: Prefs = prefs
  const s: Site[] = sites as Site[]
  const f: Facts = facts as unknown as Facts
  const g: WindGrid = grid as unknown as WindGrid
  const o: OverviewRow[] = overview as unknown as OverviewRow[]
  const c: Scan = scan as unknown as Scan
  const r: SavedRoute[] = routes
  expect([p, s, f, g, o, c, r].every(Boolean)).toBe(true)
})

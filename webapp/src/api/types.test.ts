import prefs from "../../test/fixtures/prefs.json"
import sites from "../../test/fixtures/sites.json"
import facts from "../../test/fixtures/facts_1d.json"
import grid from "../../test/fixtures/wind_grid.json"
import overview from "../../test/fixtures/overview_3d.json"
import scan from "../../test/fixtures/scan.json"
import routes from "../../test/fixtures/routes.json"
import type { Prefs, Site, Facts, WindGrid, OverviewRow, Scan, SavedRoute } from "./types"

/* Проверка на этапе компиляции: `tsc --noEmit` в npm run build упадёт, если тип
   разошёлся с настоящим ответом. Тело теста нужно, чтобы файл считался тестом.
   Приведений типа здесь нет: присваивание идёт напрямую, чтобы структурная
   проверка TypeScript реально отрабатывала для каждого поля. */
test("фикстуры описываются типами", () => {
  const p: Prefs = prefs
  const s: Site[] = sites
  const f: Facts = facts
  const g: WindGrid = grid
  const o: OverviewRow[] = overview
  const c: Scan = scan
  const r: SavedRoute[] = routes
  expect([p, s, f, g, o, c, r].every(Boolean)).toBe(true)
})

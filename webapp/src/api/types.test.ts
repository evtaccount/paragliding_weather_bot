import prefs from "../../test/fixtures/prefs.json"
import sites from "../../test/fixtures/sites.json"
import facts from "../../test/fixtures/facts_1d.json"
import factsWindy from "../../test/fixtures/facts_1d_windy.json"
import factsNoCeiling from "../../test/fixtures/facts_1d_no_ceiling.json"
import factsNoWindow from "../../test/fixtures/facts_1d_no_window.json"
import grid from "../../test/fixtures/wind_grid.json"
import overview from "../../test/fixtures/overview_3d.json"
import scan from "../../test/fixtures/scan.json"
import scanMixed from "../../test/fixtures/scan_mixed.json"
import routes from "../../test/fixtures/routes.json"
import forecast3d from "../../test/fixtures/forecast_3d.json"
import type { Prefs, Site, Facts, WindGrid, OverviewRow, Scan, SavedRoute, ForecastOverview } from "./types"

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

/* Пустой массив в JSON выводится как never[], который структурно совместим с
   ЛЮБЫМ типом элемента — сломай Assessment.warnings на number[], и facts.json
   выше всё равно пройдёт tsc молча. Эти фикстуры не пустые именно в тех
   массивах, так что поломка типа элемента здесь действительно обвалит сборку:
   facts_1d_windy.json — assessment.warnings/vetoes_in_window/unchecked_vetoes
   и hourly_daytime[].veto непусты; scan_mixed.json — Scan.empty/failed непусты. */
test("непустые массивы фикстур реально проверяют тип элемента", () => {
  const fw: Facts = factsWindy
  const fn: Facts = factsNoCeiling
  const cm: Scan = scanMixed
  expect([fw, fn, cm].every(Boolean)).toBe(true)
})

/* thermal_window уходит в null не только гипотетически: на настоящих
   координатах Гудаури с северной экспозицией в декабре солнце не набирает
   термического окна вовсе (engine.py:sun_hours). facts_1d_no_window.json —
   реальный такой ответ, а не выдуманный edge case. */
test("Facts.thermal_window допускает null по-настоящему", () => {
  const fn: Facts = factsNoWindow
  expect(fn.thermal_window).toBeNull()
})

/* GET /api/forecast?range=3d|week|2weeks отдаёт engine.facts_overview — форму,
   которую Facts (range=1d) не описывает. forecast_3d.json — реальный такой
   ответ (range="3d" на недельных данных, как и у overview_3d.json). */
test("диапазонный /api/forecast описывается ForecastOverview", () => {
  const fo: ForecastOverview = forecast3d
  expect(fo).toBeTruthy()
})

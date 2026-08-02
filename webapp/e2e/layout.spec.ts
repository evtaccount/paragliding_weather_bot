// Три проверки раскладки, которые нельзя сделать в jsdom: там
// getBoundingClientRect всегда нулевой, переносов и ширин не существует, а
// размер контейнера карты приходилось подделывать полями clientWidth/
// clientHeight. Здесь их меряет настоящий движок.
//
// В отличие от app.spec.ts, эти сценарии идут на ФИКСИРОВАННЫХ ответах API
// (см. stubApi в fixtures.ts) и живого бэкенда не требуют вовсе: раскладку
// определяет длина текста и геометрия маршрута, а живой прогноз даёт каждый
// день разные — сценарий то ловил бы дефект, то нет.
import { expect, stubApi, test } from "./fixtures"
import type { Locator, Page } from "@playwright/test"

// Насколько элементы вылезают за рамку своего контейнера, в пикселях (0 —
// все внутри). Считается в браузере одним заходом: перебор боксов по одному
// через локаторы дал бы столько же чисел, но измеренных в разные моменты.
async function overflowOutside(frame: Locator, items: Locator): Promise<number> {
  const frameHandle = await frame.elementHandle()
  const itemHandles = await items.elementHandles()
  return frame.page().evaluate(
    ([box, elements]) => {
      const outer = (box as Element).getBoundingClientRect()
      let worst = 0
      for (const el of elements as Element[]) {
        const r = el.getBoundingClientRect()
        worst = Math.max(worst, outer.left - r.left, r.right - outer.right,
                         outer.top - r.top, r.bottom - outer.bottom)
      }
      return Math.round(worst)
    },
    [frameHandle, itemHandles] as const,
  )
}

// Кладёт на вкладку «Маршрут» посчитанный маршрут, выбрав его в шторке
// «Сохранённые». Точки сохранённого маршрута и точки ответа расчёта — одни и
// те же (см. stubApi), поэтому карта показывает ровно тот маршрут, который
// выбрали.
async function pickSavedRoute(page: Page): Promise<void> {
  // День выбирается первым: приложение ничего не подставляет за пилота
  // (бриф explicit-site-and-day), и без явного дня «Маршрут» показывает
  // «Выберите день» вместо расчёта — раскладку тогда мерить не на чем.
  await page.getByRole("banner").getByRole("button", { name: "День не выбран" }).click()
  await page.getByRole("dialog").getByRole("button", { name: /сегодня/ }).click()
  await page.getByRole("tab", { name: "Маршрут" }).click()
  await page.getByRole("button", { name: "Сохранённые" }).click()
  await page.getByRole("dialog").getByRole("button", { name: "Гудаури — юг" }).click()
}

test("переключил вкладку — на карте виден весь маршрут", async ({ page }) => {
  // Ответ расчёта придерживается, чтобы маршрут досчитался, ПОКА вкладка
  // «Маршрут» скрыта. Это и есть проверяемое условие: все четыре экрана
  // смонтированы разом, неактивные скрыты через hidden/display:none (App.tsx,
  // styles.css `.view[hidden]`), поэтому карта создаётся в контейнере 0×0,
  // Leaflet кэширует нулевой размер и сам о новом не узнаёт никогда
  // (map/MapView.tsx — эффект отложенной подгонки). Успей ответ прийти на
  // видимой вкладке — контейнер был бы уже с размером, и проверять было бы
  // нечего.
  const api = await stubApi(page, { holdRoute: true })
  await page.goto("/")

  await pickSavedRoute(page)
  const routeScreen = page.locator('section[aria-label="Маршрут"]')
  await expect(routeScreen.locator(".spinner")).toBeVisible()

  await page.getByRole("tab", { name: "Прогноз" }).click()
  await expect(routeScreen).toBeHidden()

  api.releaseRoute()
  // Карта появилась в скрытой вкладке — дальше её показываем. Ожидание
  // привязано к появлению самой карты, а не к паузе после releaseRoute().
  const map = routeScreen.locator(".map .leaflet-container")
  await expect(map).toBeAttached()

  await page.getByRole("tab", { name: "Маршрут" }).click()
  await expect(map).toBeVisible()

  // Пять точек route.json — 40 км строго на юг. Без подгонки после показа
  // вкладки Leaflet остаётся на временной наводке зумом 12 (≈28 м/пиксель):
  // маршрут длиной 40 км занял бы ≈1430 пикселей при рамке 4/3 от ширины
  // экрана — четыре пина из пяти оказались бы за краем.
  const pins = routeScreen.locator(".leaflet-marker-icon")
  await expect(pins).toHaveCount(5)
  await expect.poll(() => overflowOutside(map, pins)).toBe(0)
})

test.describe("узкий экран", () => {
  // 320 px — самый узкий экран, на котором открывают Telegram (iPhone SE
  // первого поколения). Именно на нём мерили чип времени вылета, когда
  // заводили .chip--dep (styles.css).
  test.use({ viewport: { width: 320, height: 900 } })

  test("чипы времени вылета не вылезают за рамку", async ({ page }) => {
    await stubApi(page)
    await page.goto("/")
    await pickSavedRoute(page)

    const chips = page.locator('section[aria-label="Маршрут"] .chip--dep')
    await expect(chips.first()).toBeVisible()
    // Проверка не должна остаться пустой формальностью: короткие чипы
    // «07:00 → 70,5» не вылезают ни при какой вёрстке. Дефект видит только
    // непроходимый вариант, у которого в тексте целая фраза (Route.tsx:
    // warning по route.py:FEASIBILITY_RU) — без него сценарий зеленел бы и с
    // `flex: none`, то есть проверял бы ничего.
    await expect(chips.filter({ hasText: "не успеваешь до закрытия окна" }).first()).toBeVisible()

    // Рамка — контейнер самих чипов: он занимает всю ширину внутренностей
    // панели, и «вылез за него» ровно означает «вылез за панель».
    const frame = page.getByRole("group", { name: "Время вылета" })
    expect(await overflowOutside(frame, chips)).toBe(0)
  })
})

test("шторка «Новый маршрут»: поля по ширине, карта ненулевая", async ({ page }) => {
  await stubApi(page)
  await page.goto("/")

  await page.getByRole("tab", { name: "Маршрут" }).click()
  await page.getByRole("button", { name: "Новый маршрут" }).click()
  const sheet = page.getByRole("dialog")
  await expect(sheet).toBeVisible()

  // Тело шторки не прокручивается вбок. Поля объявлены на всю ширину
  // (styles.css: .field input/textarea — width: 100%), и их собственные поля
  // и рамка помещаются внутрь только потому, что сброс задаёт
  // box-sizing: border-box; без него каждое поле шире контейнера на padding
  // с бордюром, и шторка едет горизонтально.
  const body = sheet.locator(".sheet__b")
  const sideways = await body.evaluate((el) => el.scrollWidth - el.clientWidth)
  expect(sideways).toBe(0)
  expect(await overflowOutside(body, sheet.locator(".field input, .field textarea"))).toBe(0)

  // Карта в шторке обязана получить настоящий размер. Меряется ровно то,
  // что читает сам Leaflet и что проверяет map/MapView.tsx:hasSize —
  // clientWidth/clientHeight контейнера: высоту ему даёт только
  // `aspect-ratio` рамки (styles.css: .map), своей у него нет.
  const size = await sheet.locator(".map .pgbot-map").evaluate(
    (el) => ({ width: el.clientWidth, height: el.clientHeight }),
  )
  expect(size.width).toBeGreaterThan(0)
  expect(size.height).toBeGreaterThan(0)

  // И карта нарисована на всю рамку, а не полоской по краю. Одного «плитки
  // есть» мало: на рамке нулевой высоты Leaflet всё равно создаёт ряд плиток
  // (проверено пробником — контейнер 418×0, плиток 2), так что признаком
  // живой карты может быть только покрытие.
  const covered = await sheet.locator(".map").evaluate((frame) => {
    const inner = frame.querySelector(".pgbot-map")!.getBoundingClientRect()
    const tiles = [...frame.querySelectorAll(".leaflet-tile")].map((t) => t.getBoundingClientRect())
    if (tiles.length === 0) return false
    return Math.min(...tiles.map((t) => t.left)) <= inner.left + 1
      && Math.max(...tiles.map((t) => t.right)) >= inner.right - 1
      && Math.min(...tiles.map((t) => t.top)) <= inner.top + 1
      && Math.max(...tiles.map((t) => t.bottom)) >= inner.bottom - 1
  })
  expect(covered).toBe(true)
})

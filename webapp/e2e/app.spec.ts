// Пять сквозных сценариев против НАСТОЯЩЕГО бэкенда: приложение открывается
// из поддельного Telegram с настоящей подписью, ходит в локальный app.py, а
// тот — в open-meteo. Ничего не подставляется: если сломается подпись, прокси
// или разбор ответа, здесь это видно, а в jsdom — нет (там fetch подделан).
//
// Данные приходят живые, поэтому ожидания привязаны к СМЫСЛУ («в вердикте
// стоит балл», «в шторке есть строки высот»), а не к конкретным числам: балл
// сегодняшнего дня в Лалискури не постоянная величина. Числа проверяют
// юнит-тесты экранов на фикстурах (src/screens/*.test.tsx).
import { expect, test } from "./fixtures"

// Адрес SDK Telegram целиком, как он стоит в webapp/index.html. Проверяется
// ВЕСЬ адрес, а не хвост имени файла: опечатка в хосте
// (`https://telegramm.invalid/js/telegram-web-app.js`) даёт файл с тем же
// именем, скрипт не загрузится никогда, каждый пилот получит «Не Telegram» —
// а проверка по хвосту прошла бы зелёной, то есть пропустила бы ровно тот
// дефект, ради которого заведена.
//
// `(\?…)?` — необязательная строка запроса: документация Telegram предлагает
// закреплять версию Bot API как `…/telegram-web-app.js?57`, и такой адрес
// обязан считаться тем же самым. Тот же хвост есть в шаблоне перехвата
// (fixtures.ts:blockTelegramSdk) — это две половины одного правила, чинить их
// надо парой: без хвоста в ШАБЛОНЕ настоящий скрипт грузится и затирает
// подставленный window.Telegram, и падают 7 сценариев из 8.
// Адрес записан здесь литералом и НЕ должен браться из той же переменной
// сборки, что и тег в index.html: тогда проверка начнёт сверять приложение
// само с собой и перестанет ловить опечатку в адресе (ревью task-15, N2 —
// с проверкой по одному хвосту имени файла хост telegramm.invalid проходил
// все восемь сценариев, а в настоящем Telegram SDK не загрузился бы никогда).
const TELEGRAM_SDK_URL = /^https:\/\/telegram\.org\/js\/telegram-web-app\.js(\?.*)?$/

test("приложение открывается и показывает вкладки", async ({ page }) => {
  // Страница обязана ЗАПРОСИТЬ SDK Telegram. Сам ответ сценарии глушат
  // (fixtures.ts: blockTelegramSdk — иначе настоящий скрипт затирает
  // подставленный window.Telegram), но глушение не должно прикрывать пропажу
  // самого тега <script> из index.html: сквозной прогон — единственное место
  // в проекте, где index.html грузится целиком, в jsdom его нет вовсе.
  // Убери тег — в настоящем Telegram window.Telegram не создаст никто, и
  // КАЖДЫЙ пилот получит «Не Telegram» на всех экранах, а весь набор при
  // этом остался бы зелёным.
  //
  // Проверка стоит ЗДЕСЬ, а не в разборке фикстуры, потому что в разборке она
  // попала бы и в сценарий «вне Telegram», где window.Telegram не подставляется
  // намеренно, — и смешала бы два разных утверждения: «страница зовёт SDK» и
  // «без подписи приложение просит открыть из Telegram».
  const sdkRequested = page.waitForRequest(TELEGRAM_SDK_URL, { timeout: 15_000 })
  await page.goto("/")
  await sdkRequested

  const tabs = page.getByRole("tab")
  await expect(tabs).toHaveText(["Прогноз", "Обзор", "Маршрут", "Настройки"])
  await expect(page.getByRole("tab", { name: "Прогноз" })).toHaveAttribute("aria-selected", "true")

  // Одних вкладок мало: они рисуются и при отвергнутой подписи — оболочка
  // показывает их до любого ответа сервера. Поэтому сценарий требует ещё и
  // того, что приходит ТОЛЬКО по успешному подписанному запросу: подпись
  // модели из /api/prefs и список стартов из /api/sites. Отвергни сервер
  // подпись — чип модели останется пустым (App.tsx: modelLabel(prefs.data, …)
  // ?? <Spinner/>), а в шторке выбора старта будет «Нет стартов».
  //
  // Само имя старта в шапке признаком этого больше не служит: пока пилот не
  // выбрал, там стоит «Старт не выбран» независимо от ответа сервера (бриф
  // explicit-site-and-day) — поэтому список проверяется там, где он живёт.
  await expect(page.locator(".ctx .chip--live")).toHaveText(/\S/)

  await page.getByRole("button", { name: "Старт не выбран" }).click()
  const sheet = page.getByRole("dialog")
  await expect(sheet.getByText("Нет стартов")).toHaveCount(0)
  await expect(sheet.locator(".pick button").first()).toHaveText(/\S/)
  await sheet.getByRole("button", { name: "Закрыть" }).click()
})

// Приложение ничего не выбирает за пилота: пока старт и день не названы,
// «Прогноз» показывает, чего не хватает, и в сеть не ходит вовсе (бриф
// explicit-site-and-day). Сценарии, которым нужен посчитанный прогноз,
// проходят тот же путь, что и пилот: две кнопки в шапке, две шторки.
//
// Старт берётся первый из живой библиотеки (какой именно — сценарию всё
// равно, данные настоящие), день — сегодняшний: он всегда есть в списке.
async function chooseSiteAndToday(page: import("@playwright/test").Page) {
  await page.getByRole("button", { name: "Старт не выбран" }).click()
  await page.getByRole("dialog").locator(".pick button").first().click()

  await page.getByRole("button", { name: "День не выбран" }).click()
  await page.getByRole("dialog").getByRole("button", { name: /^сегодня, / }).click()
}

// Экран «Прогноз» — не единственный, кто рисует вердикт: «Обзор» показывает
// такую же категорию своим днём, и все четыре экрана смонтированы разом
// (App.tsx). Поэтому проверки адресуются его секции по доступному имени, а не
// голым классам, — иначе локатор ловит два элемента и падает на строгости.
function dayScreen(page: import("@playwright/test").Page) {
  return page.locator('section[aria-label="Прогноз на день"]')
}

test("прогноз загружается и показывает вердикт", async ({ page }) => {
  await page.goto("/")
  await chooseSiteAndToday(page)
  const day = dayScreen(page)

  // Балл дня — число или прочерк (Forecast.tsx: assessment.score ?? "—"),
  // рядом с ним словесная категория, а слева — лётное окно. Все три рисуются
  // только из ответа /api/forecast: до него на экране стоит спиннер, а на
  // отказе — ErrorBox.
  await expect(day.locator(".verdict__num")).toHaveText(/^(\d+|—)$/)
  await expect(day.locator(".verdict__cat")).toHaveText(/\S/)
  await expect(day.locator(".verdict__win")).toHaveText(/(\d{1,2}:\d{2} – \d{1,2}:\d{2}|окно не определено)/)
  // Полоса часов — SVG, который рисуется по hourly_daytime того же ответа:
  // без неё «вердикт» мог бы оказаться заглушкой без данных.
  await expect(day.locator(".strip svg")).toBeVisible()
})

test("шторка ветра по высотам открывается и закрывается", async ({ page }) => {
  await page.goto("/")
  await chooseSiteAndToday(page)

  // Кнопка живёт под вердиктом и появляется вместе с ним — ждём именно её,
  // а не «сколько-нибудь времени».
  await dayScreen(page).getByRole("button", { name: "Ветер по высотам" }).click()

  const sheet = page.getByRole("dialog")
  await expect(sheet).toBeVisible()
  await expect(sheet.getByText("Ветер по высотам")).toBeVisible()
  // Содержимое, а не только заголовок: строка старта (level.is_launch)
  // приходит из /api/forecast/wind-grid — отдельного запроса, который делает
  // сама шторка. Пустая шторка со шторочным заголовком прошла бы проверку
  // «открылась», ничего при этом не показав.
  await expect(sheet.locator('tr[data-launch="true"]')).toHaveCount(1)

  await sheet.getByRole("button", { name: "Закрыть" }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
})

test("настройки открываются и показывают список моделей", async ({ page }) => {
  await page.goto("/")

  await page.getByRole("tab", { name: "Настройки" }).click()
  await page.getByRole("button", { name: /Постоянная модель/ }).click()

  const sheet = page.getByRole("dialog")
  await expect(sheet).toBeVisible()
  // Список моделей приходит с сервера вместе с настройками (api.py:
  // _prefs_payload по engine.MODELS) — своего перечня у приложения нет.
  // Проверяются обе группы: разовая и постоянная, — их две именно потому,
  // что разовый выбор и настройка это разные вещи (ModelPickerSheet.tsx).
  const once = sheet.getByRole("group", { name: "Разово — только для этого прогноза" })
  const permanent = sheet.getByRole("group", { name: "Постоянная — для всех следующих запросов" })
  // GFS назван поимённо: этот ключ engine.MODELS отдаёт высоту слоя
  // перемешивания, на нём держится потолок термички, и исчезнуть из списка
  // он не может незаметно.
  await expect(once.getByRole("button", { name: "GFS" })).toBeVisible()
  await expect(permanent.getByRole("button", { name: "GFS" })).toBeVisible()
  // Список не из одного пункта: выбиралка с единственной моделью означала бы,
  // что до приложения доехала не вся engine.MODELS.
  expect(await once.getByRole("button").count()).toBeGreaterThan(1)
})

test.describe("вне Telegram", () => {
  // Объект window.Telegram не подставляется вовсе — ровно то, что видит
  // приложение, открытое ссылкой в обычном браузере.
  test.use({ telegram: "none" })

  test("без подписи приложение просит открыть из Telegram", async ({ page }) => {
    await page.goto("/")

    await expect(page.getByText("Не Telegram")).toBeVisible()
    await expect(
      page.getByText("Откройте приложение из Telegram — вне него нельзя подтвердить, кто вы."),
    ).toBeVisible()
    // Оболочки нет вовсе: без подписи ни один запрос отправлять нельзя, и
    // приложение обязано остановиться до вкладок, а не показать пустой каркас.
    await expect(page.getByRole("tab")).toHaveCount(0)
  })
})

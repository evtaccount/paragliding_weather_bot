// Два выбора пилота в шапке приложения — старт и день — как действия, а не
// как подставленное состояние: с брифа explicit-site-and-day приложение не
// выбирает за него ничего, и тесты, которым нужен посчитанный прогноз,
// проходят тот же путь (кнопка в шапке → шторка → строка списка).
//
// Общий модуль, а не копия в каждом файле: этот путь нужен тестам оболочки
// (src/App.test.tsx) и тестам настроек (src/screens/Settings.test.tsx), а
// дальше понадобится и другим — две копии одного жеста расходятся так же,
// как копии знания в продукте.
import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { fmtDate } from "../src/format"
import { isoInDays } from "./days"

// Старт выбирается с ПЛАШКИ на экране, а не из шапки: пока выбора нет, в шапке
// стоит заголовок «Старт не выбран», и он больше не нажимается (просьба
// владельца — выбор живёт там, куда пилот смотрит). Регулярное выражение
// покрывает обе надписи плашки: «Выберите старт» и «Выберите старт и день».
//
// Поиск по всему документу, а не внутри одного экрана: плашка стоит на том,
// который открыт, а открыт при запуске «Прогноз». Скрытые вкладки в поиск не
// попадают — у них атрибут hidden, и getByRole их не видит.
export async function pickSite(name: string): Promise<void> {
  await userEvent.click(await screen.findByRole("button", { name: /Выберите старт/ }))
  // findBy, а не getBy: до ответа /api/sites в шторке крутится индикатор, и
  // строки старта в ней ещё нет.
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(name) }))
}

// offset — на сколько дней вперёд от сегодняшнего; возвращает выбранную дату
// в том виде, в каком она уйдёт в запрос (`date=`).
export async function pickDay(offset: number): Promise<string> {
  const header = screen.getByRole("banner")
  await userEvent.click(within(header).getByRole("button", { name: "День не выбран" }))
  const picked = isoInDays(offset)
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(fmtDate(picked)) }))
  return picked
}

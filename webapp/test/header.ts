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

export async function pickSite(name: string): Promise<void> {
  const header = screen.getByRole("banner")
  // findBy, а не getBy: до ответа /api/sites в шторке крутится индикатор, и
  // строки старта в ней ещё нет.
  await userEvent.click(await within(header).findByRole("button", { name: "Старт не выбран" }))
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

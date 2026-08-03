// Окно дней, на которое домен вообще считает прогноз. Само число
// (RANGE_DAYS_2WEEKS) сверяет питоновский тест tests/test_webapp_sync.py — он
// читает domain.ts и сравнивает с engine.RANGE_DAYS["2weeks"]. Здесь
// проверяется не число, а список, который из него получается, и шаг по нему:
// список рисует выбиралка дня, а по шагу ходят шевроны в шапке, — то есть от
// них зависит, до какого дня пилот вообще может добраться.
//
// Даты берутся из test/days.ts — СВОЕЙ арифметикой, независимой от продуктовой
// (см. комментарий там): возьми их у продукта, и сдвиг на день уехал бы в обе
// стороны сразу.
import { expect, test } from "vitest"
import { RANGE_DAYS_2WEEKS } from "./domain"
import { dayInWindow, forecastDays } from "./days"
import { isoInDays } from "../test/days"

test("окно прогноза начинается с сегодняшнего дня", () => {
  expect(forecastDays()[0]).toBe(isoInDays(0))
})

test("окно прогноза длиной ровно в самый дальний диапазон домена", () => {
  const days = forecastDays()
  expect(days).toHaveLength(RANGE_DAYS_2WEEKS)
  // Именно последний день, а не только длина: список правильной длины,
  // начатый не с того дня, проверку на длину прошёл бы.
  expect(days[RANGE_DAYS_2WEEKS - 1]).toBe(isoInDays(RANGE_DAYS_2WEEKS - 1))
})

test("дни окна идут подряд и без повторов", () => {
  const days = forecastDays()
  expect(new Set(days).size).toBe(days.length)
  // Переход через конец месяца и переводы часов — на совести сдвига по
  // календарю, а не арифметики по миллисекундам: список обязан совпасть с
  // независимым счётом день в день на всей длине.
  expect(days).toEqual(Array.from({ length: RANGE_DAYS_2WEEKS }, (_, i) => isoInDays(i)))
})

test("шаг по окну даёт соседний день", () => {
  expect(dayInWindow(isoInDays(3), 1)).toBe(isoInDays(4))
  expect(dayInWindow(isoInDays(3), -1)).toBe(isoInDays(2))
})

// Края окна — то, ради чего шаг вообще отдельная функция: за ними прогноза не
// существует (engine.build_url просит ровно forecast_days=RANGE_DAYS[rng]), и
// шеврону там нечего показывать.
test("с сегодняшнего дня назад шагнуть некуда", () => {
  expect(dayInWindow(isoInDays(0), -1)).toBeNull()
})

test("с последнего дня окна вперёд шагнуть некуда", () => {
  expect(dayInWindow(isoInDays(RANGE_DAYS_2WEEKS - 1), 1)).toBeNull()
})

// Приложение осталось открытым за полночь: выбранный вчера «сегодняшний» день
// теперь позади окна. Шагать внутри окна, в котором не стоишь, нельзя ни в
// какую сторону — иначе шеврон увёл бы пилота на день, соседний со вчерашним,
// то есть снова наружу.
test("из дня вне окна шагнуть некуда ни в одну сторону", () => {
  expect(dayInWindow(isoInDays(-1), 1)).toBeNull()
  expect(dayInWindow(isoInDays(-1), -1)).toBeNull()
  expect(dayInWindow(isoInDays(RANGE_DAYS_2WEEKS), -1)).toBeNull()
})

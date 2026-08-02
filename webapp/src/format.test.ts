import { afterAll, beforeAll, expect, test, vi } from "vitest"
import { compass, fmtDate, fmtHour, fmtNum, fmtPoints, fmtSavedDate } from "./format"

test("дробная часть отделяется запятой, как в боте", () => {
  expect(fmtNum(3.14, 1)).toBe("3,1")
  expect(fmtNum(7)).toBe("7")
})

test("направление ветра переводится в румб", () => {
  expect(compass(0)).toBe("С")
  expect(compass(180)).toBe("Ю")
  expect(compass(359)).toBe("С")
  expect(compass(-1)).toBe("С")     // отрицательные градусы нормализуются
})

test("дата показывается коротко и с днём недели", () => {
  expect(fmtDate("2026-07-25")).toBe("сб, 25 июля")
})

// Пояс закреплён на время этих двух тестов ровно по той же причине, по
// которой он закреплён в tests/conftest.py:30 для питоновской половины: без
// этого проверялся бы пояс машины, на которой запустили прогон, и на машине
// в UTC «перевод в местное время» выглядел бы работающим при любой
// реализации — даже при срезе строки до "T".
beforeAll(() => { vi.stubEnv("TZ", "Asia/Tbilisi") })
afterAll(() => { vi.unstubAllEnvs() })

// SavedRoute.saved — полный ISO-таймстамп в UTC (store.py:88-89), а не дата.
// Тот же перевод, что делает чат (bot.py:1058 _local_date): store пишет UTC,
// а пилот живёт в своём поясе, и сохранённый вечером маршрут иначе значился
// бы сохранённым «вчера».
test("дата сохранения маршрута переводится в местный пояс", () => {
  expect(fmtSavedDate("2026-07-25T22:00:00+00:00")).toBe("2026-07-26")
  expect(fmtSavedDate("2026-07-25T06:33:49+00:00")).toBe("2026-07-25")
})

test("неразобранная дата сохранения показывается как есть, а не «Invalid Date»", () => {
  expect(fmtSavedDate("25.07.2026")).toBe("25.07.2026")
})

test("час дополняется нулём", () => {
  expect(fmtHour(9)).toBe("09:00")
  expect(fmtHour(14)).toBe("14:00")
})

// Ревью задачи 13 (N10): кнопка «Показать маршрут» подписывалась «· 1 точек».
// Проверяются все три окончания и обе ловушки русского счёта — второй десяток
// (11-14 всегда «точек») и число, оканчивающееся на единицу за его пределами.
test("число точек склоняется по-русски", () => {
  expect(fmtPoints(0)).toBe("0 точек")
  expect(fmtPoints(1)).toBe("1 точка")
  expect(fmtPoints(2)).toBe("2 точки")
  expect(fmtPoints(4)).toBe("4 точки")
  expect(fmtPoints(5)).toBe("5 точек")
  expect(fmtPoints(11)).toBe("11 точек")
  expect(fmtPoints(12)).toBe("12 точек")
  expect(fmtPoints(21)).toBe("21 точка")
  expect(fmtPoints(22)).toBe("22 точки")
  expect(fmtPoints(50)).toBe("50 точек")
})

import { expect, test } from "vitest"
import { compass, fmtDate, fmtHour, fmtNum } from "./format"

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

test("час дополняется нулём", () => {
  expect(fmtHour(9)).toBe("09:00")
  expect(fmtHour(14)).toBe("14:00")
})

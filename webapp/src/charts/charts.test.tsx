import { render, screen } from "@testing-library/react"
import { expect, test } from "vitest"
import { HourStrip } from "./HourStrip"
import { AirColumn } from "./AirColumn"
import facts from "../../test/fixtures/facts_1d.json"
import type { Facts } from "../api/types"

const F = facts as unknown as Facts

test("в полосе часов столбик на каждый светлый час", () => {
  const { container } = render(<HourStrip hours={F.hourly_daytime} window={F.assessment.fly_window} />)
  expect(container.querySelectorAll("[data-hour]")).toHaveLength(F.hourly_daytime.length)
})

test("часы вне лётного окна помечены", () => {
  const { container } = render(<HourStrip hours={F.hourly_daytime} window={[11, 16]} />)
  const inside = container.querySelectorAll('[data-in-window="true"]')
  expect(inside.length).toBeGreaterThan(0)
  expect(inside.length).toBeLessThan(F.hourly_daytime.length)
})

test("столб воздуха подписывает старт и потолок", () => {
  render(<AirColumn facts={F} />)
  expect(screen.getByText(/старт/i)).toBeInTheDocument()
  expect(screen.getByText(/потолок/i)).toBeInTheDocument()
})

test("без данных о потолке столб не выдумывает высоту", () => {
  const noCeiling = { ...F, thermal_ceiling_m_agl: null, thermal_ceiling_m_msl: null }
  render(<AirColumn facts={noCeiling} />)
  expect(screen.getByText(/потолок неизвестен/i)).toBeInTheDocument()
})

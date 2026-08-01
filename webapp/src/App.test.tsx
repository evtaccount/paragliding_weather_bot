import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import { App } from "./App"

beforeEach(() => {
  const back = { show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() }
  // Подсказка типов здесь не нужна, в отличие от telegram.test.ts (там
  // объект идёт через отдельную функцию fakeWebApp(), и её возвращаемый
  // тип выводится независимо от Window.Telegram, из-за чего colorScheme
  // сужается до string и падает настоящая ошибка типов): здесь литерал
  // объекта стоит прямо в присваивании, TypeScript типизирует его
  // контекстно по Window.Telegram, "dark" сужается до "light"|"dark" сам,
  // и ошибки нет. Директива-подсказка тут оказалась бы "неиспользуемой"
  // (TS2578) и уронила бы tsc --noEmit — расходится с дословным текстом
  // брифа, см. task-6-report.md.
  window.Telegram = { WebApp: {
    initData: "auth_date=1&hash=abc", colorScheme: "dark",
    themeParams: { bg_color: "#101418" }, ready: vi.fn(), expand: vi.fn(),
    BackButton: back, HapticFeedback: { impactOccurred: vi.fn(), notificationOccurred: vi.fn() },
  } }
  vi.stubGlobal("fetch", () => Promise.resolve(new Response("{}", {
    status: 200, headers: { "content-type": "application/json" } })))
})

test("видны четыре вкладки", () => {
  render(<App />)
  for (const name of ["Прогноз", "Обзор", "Маршрут", "Настройки"]) {
    expect(screen.getByRole("tab", { name })).toBeInTheDocument()
  }
})

test("нажатие вкладки меняет активную", async () => {
  render(<App />)
  await userEvent.click(screen.getByRole("tab", { name: "Настройки" }))
  expect(screen.getByRole("tab", { name: "Настройки" })).toHaveAttribute("aria-selected", "true")
  expect(screen.getByRole("tab", { name: "Прогноз" })).toHaveAttribute("aria-selected", "false")
})

test("без Telegram приложение объясняет, что делать, а не показывает пустоту", () => {
  // @ts-expect-error — Telegram отсутствует
  delete window.Telegram
  render(<App />)
  expect(screen.getByText(/Откройте приложение из Telegram/)).toBeInTheDocument()
})

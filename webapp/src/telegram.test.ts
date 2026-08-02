import { beforeEach, expect, test, vi } from "vitest"
import * as tg from "./telegram"

type BackButton = { show: () => void; hide: () => void; onClick: (f: () => void) => void; offClick: (f: () => void) => void }

function fakeWebApp(over: Record<string, unknown> = {}) {
  const back: BackButton = { show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() }
  return {
    initData: "auth_date=1&hash=deadbeef",
    colorScheme: "dark",
    themeParams: { bg_color: "#101418", text_color: "#ffffff" },
    ready: vi.fn(),
    expand: vi.fn(),
    BackButton: back,
    HapticFeedback: { impactOccurred: vi.fn(), notificationOccurred: vi.fn() },
    ...over,
  }
}

beforeEach(() => {
  // @ts-expect-error — в тестах окно подделывается целиком
  delete window.Telegram
})

test("подпись берётся у Telegram", () => {
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: fakeWebApp() }
  expect(tg.initData()).toBe("auth_date=1&hash=deadbeef")
})

test("без Telegram подпись пустая, а не исключение", () => {
  expect(tg.initData()).toBe("")
})

test("тема раскладывается в css-переменные", () => {
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: fakeWebApp() }
  expect(tg.themeVars()).toEqual({ "--tg-bg-color": "#101418", "--tg-text-color": "#ffffff" })
})

test("без Telegram схема светлая", () => {
  expect(tg.colorScheme()).toBe("light")
})

test("обработчик назад вешается и кнопка показывается", () => {
  const app = fakeWebApp()
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: app }
  const h = () => {}
  tg.onBack(h)
  expect(app.BackButton.onClick).toHaveBeenCalledWith(h)
  expect(app.BackButton.show).toHaveBeenCalled()
})

test("null снимает обработчик и прячет кнопку", () => {
  const app = fakeWebApp()
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: app }
  const h = () => {}
  tg.onBack(h)
  tg.onBack(null)
  expect(app.BackButton.offClick).toHaveBeenCalledWith(h)
  expect(app.BackButton.hide).toHaveBeenCalled()
})

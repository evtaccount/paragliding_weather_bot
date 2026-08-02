import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, test, vi } from "vitest"
import { Sheet } from "./Sheet"
import { ErrorBox } from "./ErrorBox"
import { ApiError } from "../api/client"

test("шторка показывает заголовок и содержимое", () => {
  render(<Sheet title="Ветер по высотам" onClose={() => {}}><p>тело</p></Sheet>)
  expect(screen.getByText("Ветер по высотам")).toBeInTheDocument()
  expect(screen.getByText("тело")).toBeInTheDocument()
})

test("крестик закрывает шторку", async () => {
  const onClose = vi.fn()
  render(<Sheet title="Заголовок" onClose={onClose}><p>тело</p></Sheet>)
  await userEvent.click(screen.getByRole("button", { name: "Закрыть" }))
  expect(onClose).toHaveBeenCalled()
})

test("ошибка показывает понятный текст и кнопку повтора", async () => {
  const onRetry = vi.fn()
  render(<ErrorBox error={new ApiError(502, "open-meteo сейчас недоступна. Попробуйте ещё раз.")} onRetry={onRetry} />)
  expect(screen.getByText(/open-meteo сейчас недоступна/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Повторить" }))
  expect(onRetry).toHaveBeenCalled()
})

test("при 401 повтора нет — повторять нечего, надо открыть из Telegram", () => {
  render(<ErrorBox error={new ApiError(401, "Откройте приложение из Telegram.")} onRetry={() => {}} />)
  expect(screen.queryByRole("button", { name: "Повторить" })).not.toBeInTheDocument()
})

// Финальное ревью ветки, Minor 7. «Повторить» у детерминированного отказа
// повторяет значение, которого на экране уже нет: пилот жмёт «+» на
// маршрутной скорости 45 (потолок store.SPEED_MAX), число дёргается на 46 и
// возвращается к 45, а кнопка отправляет ровно 46 — и так столько раз,
// сколько он нажмёт. 400 — «сервер не принял», и без правки ввода тот же
// запрос даст тот же ответ.
test("у отказа разбора (400) повтора нет — тот же запрос даст тот же ответ", () => {
  render(<ErrorBox error={new ApiError(400, "средняя маршрутная скорость должна быть от 10 до 45 км/ч.")}
                   onRetry={() => {}} />)
  expect(screen.getByText(/от 10 до 45/)).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Повторить" })).not.toBeInTheDocument()
})

// Обратная половина того же правила: 429 — единственный 4xx, который значит
// «сервер СЕЙЧАС занят» (api.py:one_at_a_time), а не «не принял». Тот же
// запрос пройдёт, как только сервер досчитает предыдущий, — кнопка нужна.
test("при 429 повтор остаётся: слот освободится сам", () => {
  render(<ErrorBox error={new ApiError(429, "Уже считаю — дождись ответа.")} onRetry={() => {}} />)
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument()
})

// Отказ БЕЗ кода — сеть пропала, и fetch отклонился, не дойдя до ответа
// (client.ts строит ApiError только по ответу сервера). Повтор здесь —
// единственное осмысленное действие.
test("у отказа без кода повтор остаётся", () => {
  const noStatus = new ApiError(undefined as unknown as number, "Сеть недоступна.")
  render(<ErrorBox error={noStatus} onRetry={() => {}} />)
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument()
})

// Вибро на отказе — то самое, ради чего в обёртке telegram.ts живёт haptic()
// (раздел 1 спеки называет вибро одной из четырёх причин её существования).
// Место одно на всё приложение: ErrorBox показывает ЛЮБОЙ отказ сервера.
test("отказ отзывается вибро", () => {
  const notificationOccurred = vi.fn()
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: { initData: "auth_date=1&hash=abc", HapticFeedback: { notificationOccurred } } }
  render(<ErrorBox error={new ApiError(502, "open-meteo сейчас недоступна.")} onRetry={() => {}} />)
  expect(notificationOccurred).toHaveBeenCalledWith("error")
})

// Вторая половина: клиент старше Bot API 6.1 объекта HapticFeedback не имеет
// вовсе, и обёртка обязана деградировать молча — иначе вибро роняет весь
// экран ошибки (проверено: первое применение haptic() уронило шесть тестов
// ровно этим).
test("без HapticFeedback экран ошибки всё равно рисуется", () => {
  // @ts-expect-error — подделка глобального объекта: клиент без вибро
  window.Telegram = { WebApp: { initData: "auth_date=1&hash=abc" } }
  render(<ErrorBox error={new ApiError(502, "open-meteo сейчас недоступна.")} onRetry={() => {}} />)
  expect(screen.getByText(/open-meteo сейчас недоступна/)).toBeInTheDocument()
})

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

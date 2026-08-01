import { render, screen } from "@testing-library/react"
import { App } from "./App"

test("приложение показывает название", () => {
  render(<App />)
  expect(screen.getByText("Прогноз")).toBeInTheDocument()
})

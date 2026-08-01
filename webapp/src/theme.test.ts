import { expect, test } from "vitest"
import { resolveThemeVars } from "./theme"

// Регрессия на ревью task-6: Telegram не гарантирует полный themeParams.
// Тот же частичный набор (только фон), что в App.test.tsx и в тексте
// брифа — colorScheme: "dark", themeParams: { bg_color: "#101418" }.
test("частичный themeParams достраивается тёмным набором, а не светлым", () => {
  const vars = resolveThemeVars("dark", { "--tg-bg-color": "#101418" })
  expect(vars["--surface"]).toBe("#101418")   // пришло от Telegram
  expect(vars["--ink"]).toBe("#E9E7E1")       // из тёмного набора, а не светлый "#1C1C1A"
})

test("без Telegram (пустой themeParams) — целый согласованный набор своей схемы", () => {
  expect(resolveThemeVars("light", {})).toEqual({
    "--surface": "#FCFCFB",
    "--panel": "#FFFFFF",
    "--sunk": "#F3F1EB",
    "--ink": "#1C1C1A",
    "--muted": "#6A6A63",
    "--faint": "#9E9E94",
    "--rule": "#E6E4DD",
    "--air": "#6EAAD2",
    "--air-deep": "#2F6F8F",
    "--air-wash": "rgba(110, 170, 210, .14)",
  })
})

test("полный themeParams перекрывает весь набор своими значениями", () => {
  const vars = resolveThemeVars("dark", {
    "--tg-bg-color": "#000000",
    "--tg-section-bg-color": "#111111",
    "--tg-secondary-bg-color": "#222222",
    "--tg-text-color": "#ffffff",
    "--tg-hint-color": "#cccccc",
    "--tg-subtitle-text-color": "#aaaaaa",
    "--tg-section-separator-color": "#333333",
    "--tg-link-color": "#3390ec",
    "--tg-button-color": "#2ea6ff",
  })
  expect(vars["--surface"]).toBe("#000000")
  expect(vars["--ink"]).toBe("#ffffff")
  expect(vars["--air-deep"]).toBe("#2ea6ff")
  // --air-wash соответствия в Telegram не имеет — всегда из палитры схемы.
  expect(vars["--air-wash"]).toBe("rgba(127, 184, 224, .13)")
})

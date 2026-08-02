import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import { configDefaults } from "vitest/config"

// Куда уходят запросы приложения, не адресованные статике. Один и тот же
// набор нужен обоим серверам Vite (dev и preview), поэтому он вынесен в
// константу: разъехавшись, они дали бы `vite dev` работающим, а `vite preview`
// (на нём стоят сквозные сценарии, см. webapp/playwright.config.ts) —
// возвращающим index.html вместо JSON на каждый /api/*.
const API_PROXY = { "/api": "http://127.0.0.1:8080", "/tiles": "http://127.0.0.1:8080" }

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    // Разработка идёт против настоящего API: подпись выпускается скриптом,
    // сервер не знает, что запрос пришёл не из Telegram, и не должен знать.
    proxy: API_PROXY,
  },
  // `vite preview` отдаёт уже собранный dist — ровно то, что попадёт в образ.
  // Свой прокси ему нужен потому, что настройки `server` он не читает вовсе
  // (это отдельный сервер со своей секцией конфигурации).
  preview: { proxy: API_PROXY },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./test/setup.ts"],
    css: false,
    // Из умолчания vitest вычитается ровно один каталог — e2e/. Его сценарии
    // написаны на Playwright, и в vitest их test() падает («Playwright Test
    // did not expect test() to be called here»): `make test` краснел бы
    // двумя файлами при 148 зелёных тестах. Запускает их `make e2e` — им
    // нужны браузер и сеть.
    //
    // Именно ВЫЧИТАНИЕ, а не суженный include ("src/**/*.test.{ts,tsx}"):
    // тот сужал набор и по каталогу, и по суффиксу, и новый тест в test/ или
    // с именем *.spec.ts просто не запускался бы — прогон отчитывался бы
    // «148 passed», exit 0, ни слова о пропуске. Проверено двумя заведомо
    // падающими пробниками (test/…test.ts и src/api/…spec.ts): при суженном
    // include оба молча не поднялись, при вычитании — оба покраснели.
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
})

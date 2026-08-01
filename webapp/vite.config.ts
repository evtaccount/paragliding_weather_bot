import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    // Разработка идёт против настоящего API: подпись выпускается скриптом,
    // сервер не знает, что запрос пришёл не из Telegram, и не должен знать.
    proxy: { "/api": "http://127.0.0.1:8080", "/tiles": "http://127.0.0.1:8080" },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./test/setup.ts"],
    css: false,
  },
})

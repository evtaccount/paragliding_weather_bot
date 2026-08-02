// Куда серверы разработки шлют запросы приложения, не адресованные статике.
//
// Один и тот же набор нужен обоим серверам Vite (dev и preview), поэтому он
// вынесен в константу: разъехавшись, они дали бы `vite dev` работающим, а
// `vite preview` (на нём стоят сквозные сценарии, см.
// webapp/playwright.config.ts) — возвращающим index.html вместо JSON на
// каждый /api/*.
//
// Отдельным файлом, а не строкой в vite.config.ts, — чтобы правило
// проверялось ИСПОЛНЕНИЕМ (test/proxy.test.ts зовёт rewrite и смотрит ответ).
// Импортировать сам vite.config в тест не выходит: в окружении jsdom на нём
// падает esbuild («your JavaScript environment is broken»), а в окружении
// node — общий setupFiles, который тянет App → Leaflet → window. Проверены
// оба варианта.
export const API_PROXY = {
  // Свой бэкенд: app.py поднимает uvicorn на 127.0.0.1:8080.
  "/api": "http://127.0.0.1:8080",
  // Тайлы, в отличие от /api, уходят НЕ на свой бэкенд — ровно как в проде
  // (Caddyfile, блок handle /tiles/*). У OpenStreetMap тайлы лежат по
  // /{z}/{x}/{y}.png, без префикса /tiles, поэтому префикс срезается: у Caddy
  // это `uri strip_prefix /tiles`, здесь — rewrite.
  //
  // Здесь стоял адрес своего же бэкенда, у которого такого маршрута нет
  // вовсе: проба против настоящего api.app дала /tiles/10/637/380.png → 404,
  // то есть карта и в `npm run dev`, и в `vite preview` рисовалась без
  // подложки. Сквозные сценарии этого не видели — webapp/e2e/fixtures.ts
  // подменяет тайлы пикселем, а живые сценарии карту не открывают.
  "/tiles": {
    target: "https://tile.openstreetmap.org",
    // Host переписывается на тайловый сервер — иначе он получит localhost.
    // У Caddy то же самое делает `header_up Host tile.openstreetmap.org`.
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/tiles/, ""),
    // Правила OpenStreetMap требуют, чтобы клиент себя называл; безымянный
    // поток запросов там блокируют. Имя отличается от боевого (Caddyfile)
    // намеренно: бан за трафик разработки не должен гасить карту у пилота.
    headers: { "User-Agent": "paragliding-bot-miniapp/1.0 (dev)" },
  },
}

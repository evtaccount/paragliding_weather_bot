import "@testing-library/jest-dom/vitest"
import { beforeEach } from "vitest"
import { resetQueueForTests } from "../src/api/queue"
import { resetAppQueryClientForTests } from "../src/App"

// Очередь тяжёлых запросов (api/queue.ts) — процессный синглтон, который
// сам себя не чистит: тест, чей fetch зависает и не слушает AbortSignal,
// оставляет её занятой навсегда и запирает heavy() во всех последующих
// тестах, а не только в своих собственных (см. комментарий у
// resetQueueForTests и разбор в task-8-report.md). Сброс здесь, а не только
// в queue.test.ts, — потому что течь бьёт по ЛЮБОМУ тесту, который дёргает
// heavy() косвенно, через хуки (useForecast/useWindGrid/useScan и т.п.), а
// таких тестов с задачи 9 будет всё больше.
beforeEach(() => {
  resetQueueForTests()
  // Тот же класс проблемы, что и очередь выше, но для кэша TanStack Query:
  // App.tsx держит один QueryClient на весь процесс (см. комментарий у
  // resetAppQueryClientForTests) — без сброса второй render(<App />) в
  // одном файле тестов читает данные из кэша ПЕРВОГО теста, а не из
  // собственного vi.stubGlobal("fetch", ...). Найдено на регрессионном
  // тесте про <StrictMode> (task-9 review, App.test.tsx).
  resetAppQueryClientForTests()
})

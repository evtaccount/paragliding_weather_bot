import "@testing-library/jest-dom/vitest"
import { beforeEach } from "vitest"
import { resetQueueForTests } from "../src/api/queue"

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
})

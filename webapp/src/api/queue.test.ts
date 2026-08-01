import { expect, test } from "vitest"
import { heavy } from "./queue"

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

test("второй запрос ждёт первого, а не уходит параллельно", async () => {
  const first = deferred<string>()
  const started: string[] = []

  const a = heavy(() => { started.push("a"); return first.promise })
  const b = heavy(() => { started.push("b"); return Promise.resolve("b") })

  expect(started).toEqual(["a"])   // b ещё не начинался
  first.resolve("a")
  await expect(a).resolves.toBe("a")
  await expect(b).resolves.toBe("b")
  expect(started).toEqual(["a", "b"])
})

test("падение задачи не запирает очередь навсегда", async () => {
  const boom = heavy(() => Promise.reject(new Error("сеть")))
  await expect(boom).rejects.toThrow("сеть")
  await expect(heavy(() => Promise.resolve(7))).resolves.toBe(7)
})

test("порядок сохраняется", async () => {
  const done: number[] = []
  await Promise.all([1, 2, 3].map((n) => heavy(async () => { done.push(n) })))
  expect(done).toEqual([1, 2, 3])
})

// Ревью 1fa2e09..: task() может бросить СИНХРОННО, не вернув промис вовсе
// (например, ошибка в коде, собирающем query-параметры, до первого await).
// Это не то же самое, что отклонённый промис — .then(onFulfilled, onRejected)
// синхронный throw не ловит.
test("синхронный throw головой очереди не запирает очередь навсегда", async () => {
  const boom = heavy(() => { throw new Error("сеть") })
  await expect(boom).rejects.toThrow("сеть")
  await expect(heavy(() => Promise.resolve(7))).resolves.toBe(7)
})

test("синхронный throw не первой задачей не запирает очередь навсегда", async () => {
  const first = deferred<string>()
  const a = heavy(() => first.promise)
  const boom = heavy(() => { throw new Error("сеть") })
  first.resolve("a")
  await expect(a).resolves.toBe("a")
  await expect(boom).rejects.toThrow("сеть")
  await expect(heavy(() => Promise.resolve(7))).resolves.toBe(7)
})

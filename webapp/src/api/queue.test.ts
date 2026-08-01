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

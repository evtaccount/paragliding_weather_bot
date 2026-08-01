import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook, waitFor } from "@testing-library/react"
import { expect, test, vi, beforeEach } from "vitest"
import type { ReactNode } from "react"
import { usePrefs, useForecast } from "./queries"
import { heavy } from "./queue"
import prefsFixture from "../../test/fixtures/prefs.json"

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

beforeEach(() => {
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: { initData: "auth_date=1&hash=abc" } }
})

test("настройки приходят и отдаются как есть", async () => {
  vi.stubGlobal("fetch", () => Promise.resolve(new Response(JSON.stringify(prefsFixture),
    { status: 200, headers: { "content-type": "application/json" } })))
  const { result } = renderHook(() => usePrefs(), { wrapper })
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  expect(result.current.data?.model_key).toBe("ecmwf")
})

test("прогноз не запрашивается, пока старт не выбран", () => {
  const fetchMock = vi.fn()
  vi.stubGlobal("fetch", fetchMock)
  renderHook(() => useForecast(null, "1d", null, null), { wrapper })
  expect(fetchMock).not.toHaveBeenCalled()
})

test("ошибка не повторяется автоматически", async () => {
  const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail: "нет" }),
    { status: 500, headers: { "content-type": "application/json" } })))
  vi.stubGlobal("fetch", fetchMock)
  const { result } = renderHook(() => usePrefs(), { wrapper })
  await waitFor(() => expect(result.current.isError).toBe(true))
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

// Ревью: тяжёлый запрос, брошенный пилотом на середине (быстрая навигация
// между экранами), доезжал до конца и всё это время держал единственный
// слот пилота — и в клиентской очереди (busy), и на сервере
// (guards.INFLIGHT), задерживая следующий, уже нужный запрос. queryFn
// обязан принимать `signal` из контекста TanStack Query и передавать его в
// apiGet → fetch, чтобы отмена долетала до сети, а не только до реакта.
test("тяжёлый запрос передаёт AbortSignal, и отмена освобождает очередь", async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function localWrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  }
  const fetchMock = vi.fn<typeof fetch>((_url, init) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("отменено", "AbortError")))
  }))
  vi.stubGlobal("fetch", fetchMock)

  renderHook(() => useForecast("Гудаури", "1d", null, null), { wrapper: localWrapper })
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  const [, init] = fetchMock.mock.calls[0]!
  expect((init as RequestInit).signal).toBeInstanceOf(AbortSignal)

  await qc.cancelQueries({ queryKey: ["forecast", "Гудаури", "1d", null, null] })

  // Очередь не должна остаться занятой отменённым запросом навсегда — иначе
  // следующий тяжёлый запрос пилота встанет за уже никому не нужным.
  await expect(heavy(() => Promise.resolve("свободна"))).resolves.toBe("свободна")
})

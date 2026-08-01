import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook, waitFor } from "@testing-library/react"
import { expect, test, vi, beforeEach } from "vitest"
import type { ReactNode } from "react"
import { usePrefs, useForecast } from "./queries"
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

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook, waitFor } from "@testing-library/react"
import { expect, test, vi, beforeEach } from "vitest"
import type { ReactNode } from "react"
import { usePrefs, useForecast, useScan, useCreateSite, useDeleteSite } from "./queries"
import prefsFixture from "../../test/fixtures/prefs.json"

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

// Обёртка с ОДНИМ клиентом на весь тест — нужна там, где есть повторный
// рендер или мутация: `wrapper` выше заводит новый QueryClient на каждый
// рендер, и кэш (а с ним и вся инвалидация) не переживает даже rerender.
function stableWrapper(): ({ children }: { children: ReactNode }) => ReactNode {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } })
}

// Дать очереди и TanStack Query доработать всё, что они могли бы сделать
// сами: без этой паузы «второй запрос не ушёл» подтвердилось бы просто
// потому, что до него ещё не дошли руки.
function settled(): Promise<void> {
  return new Promise((resolve) => { setTimeout(resolve, 20) })
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

// Финальное ревью ветки, C2. Пилот открывает приложение, видит в шапке не тот
// старт и, не дожидаясь прогноза, выбирает свой. Брошенный запрос ДЕРЖИТ
// серверный слот до конца расчёта: guards.INFLIGHT отпускается только в
// `finally` обработчика, а request.is_disconnected() в api.py не вызывается
// нигде (api.py:80-96). Значит и клиентская очередь обязана держать busy до
// конца — иначе следующий запрос уходит ровно в занятый слот и получает 429
// («Уже получилось… Уже считаю — дождись ответа») на обоих экранах сразу.
//
// Подделка fetch отвечает по команде и отклоняется по AbortSignal — ровно как
// настоящий fetch: если бы signal снова уехал в fetch, отмена оборвала бы
// запрос, очередь отпустила бы busy и второй запрос ушёл бы немедленно.
test("смена старта не отправляет второй запрос, пока сервер не досчитал первый", async () => {
  const settle: (() => void)[] = []
  const fetchMock = vi.fn<typeof fetch>((_url, init) => new Promise((resolve, reject) => {
    settle.push(() => { resolve(jsonResponse({})) })
    init?.signal?.addEventListener("abort", () => { reject(new DOMException("отменено", "AbortError")) })
  }))
  vi.stubGlobal("fetch", fetchMock)

  const { rerender } = renderHook(
    ({ site }) => useForecast(site, "1d", null, "ecmwf"),
    { wrapper: stableWrapper(), initialProps: { site: "Лалискури" } },
  )
  await waitFor(() => { expect(fetchMock).toHaveBeenCalledTimes(1) })

  rerender({ site: "Казбеги" })
  await settled()
  expect(fetchMock).toHaveBeenCalledTimes(1)

  // Сервер досчитал брошенный запрос и освободил слот — только теперь уходит
  // запрос по выбранному старту.
  settle[0]!()
  await waitFor(() => { expect(fetchMock).toHaveBeenCalledTimes(2) })
  expect(decodeURIComponent(String(fetchMock.mock.calls[1]![0]))).toContain("site=Казбеги")
})

// Финальное ревью ветки, C3. /api/scan ходит по ВСЕЙ библиотеке стартов
// (forecast.py:scan_week → store.load_sites()), а его ключ ["scan", model] про
// состав библиотеки ничего не знает: без сброса заведённый старт не появлялся
// во «Все старты» вовсе — запроса /api/scan после POST /api/sites не было ни
// одного.
test("заведение старта пересчитывает «Все старты»", async () => {
  const urls: string[] = []
  vi.stubGlobal("fetch", vi.fn<typeof fetch>((url, init) => {
    urls.push(`${init?.method ?? "GET"} ${String(url).split("?")[0]}`)
    return Promise.resolve(jsonResponse(init?.method === "POST" ? { name: "Казбеги" } : { sites: [], empty: [], failed: [] }))
  }))

  const { result } = renderHook(() => ({ scan: useScan("ecmwf"), create: useCreateSite() }),
                                { wrapper: stableWrapper() })
  await waitFor(() => { expect(result.current.scan.isSuccess).toBe(true) })
  expect(urls.filter((u) => u.endsWith("/api/scan"))).toHaveLength(1)

  await act(async () => {
    await result.current.create.mutateAsync({ name: "Казбеги", lat: 42.66, lon: 44.64, elevation_m: 1750 })
  })

  await waitFor(() => { expect(urls.filter((u) => u.endsWith("/api/scan"))).toHaveLength(2) })
})

// Вторая половина C3: удалённый старт оставался в «Все старты» живым и
// кликабельным (и открывал прогноз ЧУЖОГО старта на свою дату), а его
// собственный прогноз оставался в кэше под тем же именем. Имя старта
// переиспользуемо: правки старта нет, поправить координаты можно только
// «удалить и завести заново под тем же именем» — кэш по старому имени описывал
// бы уже другую точку.
test("удаление старта сбрасывает «Все старты» и прогноз этого старта, не трогая чужой", async () => {
  const urls: string[] = []
  vi.stubGlobal("fetch", vi.fn<typeof fetch>((url, init) => {
    urls.push(`${init?.method ?? "GET"} ${decodeURIComponent(String(url))}`)
    if (init?.method === "DELETE") return Promise.resolve(new Response(null, { status: 204 }))
    return Promise.resolve(jsonResponse({ sites: [], empty: [], failed: [] }))
  }))

  const { result } = renderHook(() => ({
    doomed: useForecast("Казбеги", "1d", "2026-07-25", "ecmwf"),
    other: useForecast("Гудаури", "1d", "2026-07-25", "ecmwf"),
    scan: useScan("ecmwf"),
    remove: useDeleteSite(),
  }), { wrapper: stableWrapper() })
  await waitFor(() => { expect(result.current.scan.isSuccess).toBe(true) })
  const before = urls.filter((u) => u.startsWith("GET /api/forecast")).length
  expect(before).toBe(2)

  await act(async () => { await result.current.remove.mutateAsync("Казбеги") })

  await waitFor(() => { expect(urls.filter((u) => u.endsWith("/api/scan?model=ecmwf"))).toHaveLength(2) })
  await waitFor(() => { expect(urls.filter((u) => u.includes("site=Казбеги")).length).toBe(2) })
  expect(urls.filter((u) => u.includes("site=Гудаури"))).toHaveLength(1)
})

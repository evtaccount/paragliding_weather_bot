import { beforeEach, expect, test, vi } from "vitest"
import { ApiError, apiGet, apiSend } from "./client"

function reply(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json" },
  }))
}

beforeEach(() => {
  // @ts-expect-error — подделка глобального объекта
  window.Telegram = { WebApp: { initData: "auth_date=1&hash=abc" } }
})

test("подпись уходит заголовком на каждом запросе", async () => {
  // Явный тип аргумента vi.fn нужен, иначе TS выводит сигнатуру мока из
  // тела лямбды (она игнорирует параметры) и .mock.calls[0] типизируется
  // как пустой кортеж — деструктуризация ниже не пройдёт tsc --noEmit.
  const fetchMock = vi.fn<typeof fetch>(() => reply(200, { ok: true }))
  vi.stubGlobal("fetch", fetchMock)
  await apiGet("/api/prefs")
  const [, init] = fetchMock.mock.calls[0]!
  expect((init as RequestInit).headers).toMatchObject({ Authorization: "tma auth_date=1&hash=abc" })
})

test("параметры со значением undefined в запрос не попадают", async () => {
  const fetchMock = vi.fn<typeof fetch>(() => reply(200, {}))
  vi.stubGlobal("fetch", fetchMock)
  await apiGet("/api/forecast", { site: "Гудаури", range: "1d", model: undefined })
  const [url] = fetchMock.mock.calls[0]!
  expect(String(url)).toBe("/api/forecast?site=%D0%93%D1%83%D0%B4%D0%B0%D1%83%D1%80%D0%B8&range=1d")
})

test("401 переводится в приглашение открыть из Telegram", async () => {
  vi.stubGlobal("fetch", () => reply(401, { detail: "initData не прошла проверку" }))
  await expect(apiGet("/api/prefs")).rejects.toMatchObject({
    status: 401, userMessage: "Откройте приложение из Telegram.",
  })
})

test("403 показывает текст сервера — в нём Telegram ID пилота", async () => {
  vi.stubGlobal("fetch", () => reply(403, { detail: "Это личный бот, доступ по списку. Твой Telegram ID: 7 — пришли его владельцу бота, чтобы тебя добавили." }))
  await expect(apiGet("/api/prefs")).rejects.toMatchObject({
    status: 403,
    userMessage: "Это личный бот, доступ по списку. Твой Telegram ID: 7 — пришли его владельцу бота, чтобы тебя добавили.",
  })
})

test("429 переводится в «уже считаю»", async () => {
  vi.stubGlobal("fetch", () => reply(429, { detail: "Уже считаю — дождись ответа." }))
  await expect(apiGet("/api/scan")).rejects.toMatchObject({
    status: 429, userMessage: "Уже считаю — дождись ответа.",
  })
})

test("502 переводится в сообщение про источник данных", async () => {
  vi.stubGlobal("fetch", () => reply(502, { detail: "источник данных недоступен" }))
  await expect(apiGet("/api/forecast")).rejects.toMatchObject({
    status: 502, userMessage: "open-meteo сейчас недоступна. Попробуйте ещё раз.",
  })
})

test("400 отдаёт текст сервера дословно — он написан для пилота", async () => {
  vi.stubGlobal("fetch", () => reply(400, { detail: "неизвестная модель: марс" }))
  await expect(apiSend("PATCH", "/api/prefs", { model_key: "марс" })).rejects.toMatchObject({
    status: 400, userMessage: "неизвестная модель: марс",
  })
})

test("204 не пытается разобрать пустое тело", async () => {
  vi.stubGlobal("fetch", () => Promise.resolve(new Response(null, { status: 204 })))
  await expect(apiSend("DELETE", "/api/sites/Гудаури")).resolves.toBeNull()
})

test("ответ не в json не роняет разбор", async () => {
  vi.stubGlobal("fetch", () => Promise.resolve(new Response("<html>502</html>", { status: 502 })))
  await expect(apiGet("/api/forecast")).rejects.toBeInstanceOf(ApiError)
})

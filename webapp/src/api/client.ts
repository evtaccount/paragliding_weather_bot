// Тонкий HTTP-клиент к FastAPI-бэкенду мини-приложения.
//
// Каждый запрос несёт заголовок Authorization: tma <initData> — сервер
// проверяет подпись Telegram (см. api.py). Тексты ошибок сервер уже пишет
// по-русски и для пилота (детали см. api.py) — клиент их не переизобретает,
// а переводит только коды, для которых текста либо нет, либо он не для
// пилота (401 — техническая проверка подписи, 502 — сетевая причина).
//
// Автоматических повторов здесь нет и не будет: каждый тяжёлый запрос — это
// поход в open-meteo или Gemini, и повтор по таймеру тихо удвоил бы расход
// квоты.
//
// AbortSignal в fetch отсюда не пробрасывается намеренно, хотя TanStack Query
// и даёт его каждому queryFn. Обрыв соединения НЕ освобождает серверный слот
// пилота: guards.INFLIGHT отпускается только в `finally` обработчика
// (api.py:80-96), а `request.is_disconnected()` в api.py не вызывается нигде.
// Отменённый на клиенте тяжёлый запрос всё равно досчитывается сервером и
// всё это время занимает слот — прерывать его значит лишь выбросить уже
// оплаченный поход в open-meteo и отпустить клиентскую очередь раньше
// сервера, то есть отправить следующий запрос ровно в 429 (финальное ревью
// ветки, C2). Отмена живёт на уровне очереди — она снимает задачи, которые
// ещё не начинались (см. шапку ./queue).

import { initData } from "../telegram"

export class ApiError extends Error {
  status: number
  userMessage: string

  constructor(status: number, userMessage: string) {
    super(userMessage)
    this.status = status
    this.userMessage = userMessage
  }
}

function authHeaders(): Record<string, string> {
  return { Authorization: `tma ${initData()}` }
}

function buildUrl(path: string, params?: Record<string, string | undefined>): string {
  if (!params) return path
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, value)
  }
  const query = search.toString()
  return query ? `${path}?${query}` : path
}

// Тело ошибки FastAPI — {"detail": "текст для пилота"}. Если разобрать как
// json не удалось (сервер ответил не json-ом), detail считается пустым —
// это не повод падать самому разбору.
async function readDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as Record<string, unknown>).detail
      if (typeof detail === "string") return detail
    }
  } catch {
    // тело не json — ниже сработает запасной текст.
  }
  return ""
}

async function toApiError(response: Response): Promise<ApiError> {
  const detail = await readDetail(response)
  const status = response.status

  if (status === 401) {
    return new ApiError(status, "Откройте приложение из Telegram.")
  }
  if (status === 403) {
    // Текст сервера несёт Telegram ID пилота — пересылать владельцу бота,
    // подменять своей формулировкой нельзя.
    return new ApiError(status, detail)
  }
  if (status === 429) {
    return new ApiError(status, detail || "Уже считаю — дождись ответа.")
  }
  if (status === 502) {
    return new ApiError(status, "open-meteo сейчас недоступна. Попробуйте ещё раз.")
  }
  if (status >= 500) {
    return new ApiError(status, "Сервер не ответил. Попробуйте ещё раз.")
  }
  return new ApiError(status, detail || "Запрос не принят.")
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw await toApiError(response)
  }
  // 204 приходит с пустым телом — разбор как json бросил бы исключение на
  // успешном удалении.
  if (response.status === 204) {
    return null as T
  }
  return (await response.json()) as T
}

export async function apiGet<T>(
  path: string,
  params?: Record<string, string | undefined>,
): Promise<T> {
  const response = await fetch(buildUrl(path, params), { headers: authHeaders() })
  return handleResponse<T>(response)
}

export async function apiSend<T>(
  method: "POST" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const headers = authHeaders()
  let requestBody: string | undefined
  if (body !== undefined) {
    headers["Content-Type"] = "application/json"
    requestBody = JSON.stringify(body)
  }
  const response = await fetch(path, { method, headers, body: requestBody })
  return handleResponse<T>(response)
}

// Content-Type для FormData ставить нельзя вручную: браузер сам выставляет
// его вместе с границей раздела (boundary), а без неё сервер не разберёт тело.
export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(path, { method: "POST", headers: authHeaders(), body: form })
  return handleResponse<T>(response)
}

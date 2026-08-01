// Хуки данных для мини-приложения — тонкий слой TanStack Query над
// api/client.ts.
//
// Кэш: `retry: false` у каждого запроса и мутации без исключений — повтор по
// таймеру на тяжёлом запросе тихо удвоил бы расход квоты open-meteo/Gemini
// (см. комментарий в client.ts), а на лёгком запросе автопомтор всё равно
// бесполезен — сервер уже объяснил причину отказа текстом для пилота.
// `staleTime`/`gcTime` — 5 и 30 минут: серверный кэш живёт `CACHE_TTL_MIN`
// (по умолчанию 15 минут, engine.py), а клиентский держится вдвое короче
// «свежего» окна, чтобы не показывать пилоту устаревший ответ дольше, чем
// его будет считать устаревшим сам сервер.
//
// Тяжёлые запросы (эндпоинты с `Depends(one_at_a_time)` в api.py — те, что
// реально ходят в сеть за погодой или к Gemini) идут через `heavy(...)` из
// ./queue: сервер и так разрешает только один такой запрос на пилота
// одновременно и отвечает 429 на второй, а очередь на клиенте нужна, чтобы
// приложение само не создавало этот второй запрос, а не чтобы обойти лимit.
// Лёгкие запросы (настройки, старты, сохранённые маршруты, разбор GPX/KML)
// сети открытых данных не трогают и через очередь не идут.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query"
import { apiGet, apiSend, apiUpload, type ApiError } from "./client"
import { heavy } from "./queue"
import type { Elevation, Facts, ForecastOverview, Prefs, RouteResult, SavedRoute, Scan, Site, WindGrid } from "./types"

const STALE_TIME_MS = 5 * 60_000
const GC_TIME_MS = 30 * 60_000

// ------------------------------------------------------------------ настройки
export function usePrefs(): UseQueryResult<Prefs, ApiError> {
  return useQuery({
    queryKey: ["prefs"] as const,
    queryFn: () => apiGet<Prefs>("/api/prefs"),
    retry: false,
    staleTime: STALE_TIME_MS,
    gcTime: GC_TIME_MS,
  })
}

// Поля необязательные ровно как в api.py:PrefsPatch — приложение меняет один
// тумблер и не обязано присылать остальные.
export type PrefsPatchInput = {
  avg_route_speed_kmh?: number
  wind_correction_enabled?: boolean
  model_key?: string
}

export function useUpdatePrefs(): UseMutationResult<Prefs, ApiError, PrefsPatchInput> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (patch: PrefsPatchInput) => apiSend<Prefs>("PATCH", "/api/prefs", patch),
    retry: false,
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["prefs"] }) },
  })
}

// ------------------------------------------------------------------ старты
export function useSites(): UseQueryResult<Site[], ApiError> {
  return useQuery({
    queryKey: ["sites"] as const,
    queryFn: () => apiGet<Site[]>("/api/sites"),
    retry: false,
    staleTime: STALE_TIME_MS,
    gcTime: GC_TIME_MS,
  })
}

// Поля повторяют api.py:SiteIn.
export type SiteInput = {
  name: string
  lat: number
  lon: number
  elevation_m: number
  aspect?: string | null
  aspect_deg?: number | null
  slope_deg?: number | null
  route_top_m?: number | null
  aliases?: string[]
  notes?: string
}

export function useCreateSite(): UseMutationResult<Site, ApiError, SiteInput> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (site: SiteInput) => apiSend<Site>("POST", "/api/sites", site),
    retry: false,
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["sites"] }) },
  })
}

export function useDeleteSite(): UseMutationResult<null, ApiError, string> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => apiSend<null>("DELETE", `/api/sites/${encodeURIComponent(name)}`),
    retry: false,
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["sites"] }) },
  })
}

// ------------------------------------------------------------------ прогноз
// Диапазоны те же, что engine.RANGE_DAYS (engine.py:79) — единственные,
// которые понимает /api/forecast.
export type ForecastRange = "1d" | "3d" | "week" | "2weeks"

// GET /api/forecast отдаёт РАЗНЫЕ формы в зависимости от range (forecast.py:
// 347-349): Facts при "1d", ForecastOverview при "3d"/"week"/"2weeks".
// Перегрузки привязывают тип ответа к литералу range, который передал
// вызывающий код, — так вызов с range="1d" получает Facts без приведения
// типов, а не Facts | ForecastOverview с ручной проверкой на каждом сайте
// использования.
export function useForecast(
  site: string | null, range: "1d", date: string | null, model: string | null,
): UseQueryResult<Facts, ApiError>
export function useForecast(
  site: string | null, range: Exclude<ForecastRange, "1d">, date: string | null, model: string | null,
): UseQueryResult<ForecastOverview, ApiError>
export function useForecast(
  site: string | null, range: ForecastRange, date: string | null, model: string | null,
): UseQueryResult<Facts | ForecastOverview, ApiError> {
  return useQuery({
    queryKey: ["forecast", site, range, date, model] as const,
    queryFn: () => heavy(() => apiGet<Facts | ForecastOverview>("/api/forecast", {
      site: site ?? undefined, range, date: date ?? undefined, model: model ?? undefined,
    })),
    enabled: site !== null,
    retry: false,
    staleTime: STALE_TIME_MS,
    gcTime: GC_TIME_MS,
  })
}

export function useWindGrid(
  site: string | null, date: string | null, model: string | null,
): UseQueryResult<WindGrid, ApiError> {
  return useQuery({
    queryKey: ["windGrid", site, date, model] as const,
    queryFn: () => heavy(() => apiGet<WindGrid>("/api/forecast/wind-grid", {
      site: site ?? undefined, date: date ?? undefined, model: model ?? undefined,
    })),
    // date у /api/forecast/wind-grid обязателен (api.py: `date: str`, без
    // значения по умолчанию) — запрос без даты сервер бы просто отклонил.
    enabled: site !== null && date !== null,
    retry: false,
    staleTime: STALE_TIME_MS,
    gcTime: GC_TIME_MS,
  })
}

export function useScan(model: string | null): UseQueryResult<Scan, ApiError> {
  return useQuery({
    queryKey: ["scan", model] as const,
    queryFn: () => heavy(() => apiGet<Scan>("/api/scan", { model: model ?? undefined })),
    retry: false,
    staleTime: STALE_TIME_MS,
    gcTime: GC_TIME_MS,
  })
}

// ------------------------------------------------------------ разбор и маршрут
// Поля повторяют api.py:AnalysisIn. У мутации нет фиксированного набора
// аргументов хука (в отличие от useForecast) — тело запроса меняется на
// каждый вызов, поэтому это useMutation, а не useQuery с ключом.
export type AnalysisInput = {
  site: string
  range: string
  date?: string | null
  deep?: boolean
  model?: string | null
}

export function useAnalysis(): UseMutationResult<{ text: string }, ApiError, AnalysisInput> {
  return useMutation({
    mutationFn: (input: AnalysisInput) => heavy(() => apiSend<{ text: string }>("POST", "/api/analysis", input)),
    retry: false,
  })
}

// Поля повторяют api.py:RouteIn. `points` — строки [lat, lon, name?], тот же
// формат, в котором маршруты хранятся в store и приходят из /api/routes.
export type RouteInput = {
  points: (number | string)[][]
  name?: string | null
  date: string
  departure?: string | null
  model?: string | null
}

export function useRoute(): UseMutationResult<RouteResult, ApiError, RouteInput> {
  return useMutation({
    mutationFn: (input: RouteInput) => heavy(() => apiSend<RouteResult>("POST", "/api/route", input)),
    retry: false,
  })
}

export function useRouteAnalysis(): UseMutationResult<{ text: string }, ApiError, RouteInput> {
  return useMutation({
    mutationFn: (input: RouteInput) => heavy(() => apiSend<{ text: string }>("POST", "/api/route/analysis", input)),
    retry: false,
  })
}

// ------------------------------------------------------------ маршруты пилота
// POST /api/route/parse принимает только multipart (api.py:parse_route):
// файл полем `file`, вставленный текст полем `text` — ровно одно из двух на
// вызов.
export type ParseRouteInput = { file: File } | { text: string }

export type ParsedRoute = { points: [number, number, string | null][] }

export function useParseRoute(): UseMutationResult<ParsedRoute, ApiError, ParseRouteInput> {
  return useMutation({
    mutationFn: (input: ParseRouteInput) => {
      const form = new FormData()
      if ("file" in input) {
        form.set("file", input.file)
      } else {
        form.set("text", input.text)
      }
      return apiUpload<ParsedRoute>("/api/route/parse", form)
    },
    retry: false,
  })
}

export function useSavedRoutes(): UseQueryResult<SavedRoute[], ApiError> {
  return useQuery({
    queryKey: ["routes"] as const,
    queryFn: () => apiGet<SavedRoute[]>("/api/routes"),
    retry: false,
    staleTime: STALE_TIME_MS,
    gcTime: GC_TIME_MS,
  })
}

export type RouteSaveInput = { name: string; points: (number | string)[][] }

export function useSaveRoute(): UseMutationResult<{ name: string; overwritten: boolean }, ApiError, RouteSaveInput> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: RouteSaveInput) =>
      apiSend<{ name: string; overwritten: boolean }>("POST", "/api/routes", input),
    retry: false,
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["routes"] }) },
  })
}

export function useDeleteRoute(): UseMutationResult<null, ApiError, string> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => apiSend<null>("DELETE", `/api/routes/${encodeURIComponent(name)}`),
    retry: false,
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["routes"] }) },
  })
}

// ------------------------------------------------------------------ высота
export type Coords = { lat: number; lon: number }

export function useElevation(): UseMutationResult<Elevation, ApiError, Coords> {
  return useMutation({
    mutationFn: (coords: Coords) => heavy(() => apiSend<Elevation>("POST", "/api/elevation", coords)),
    retry: false,
  })
}

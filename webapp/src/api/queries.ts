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
    // Правки настроек идут ПО ОДНОЙ и в порядке нажатий: TanStack держит
    // мутации с одинаковым scope.id в очереди. Без этого два быстрых нажатия
    // степпера дают два одновременных PATCH на один и тот же ключ, порядок
    // их обработки сервером ничем не задан, и «+ потом −» могло оставить в
    // store не то значение, на котором пилот остановился (ревью задачи 13,
    // N9). Очередь на клиенте — единственный способ задать порядок: сервер
    // /api/prefs не сериализует запросы пилота (он не под one_at_a_time,
    // api.py:update_prefs).
    scope: { id: "prefs" },
    // Ответ PATCH — это уже свежие настройки целиком (api.py:update_prefs
    // возвращает _prefs_payload(user.id) после записи), поэтому он кладётся
    // в кэш как есть, без инвалидации и повторного GET. Инвалидация оставляла
    // окно между ответом PATCH и приходом GET: в этом окне экран показывал
    // ПРЕЖНЕЕ значение — число откатывалось, тумблер отскакивал обратно, и
    // нажатие, сделанное в этот момент, отправляло то же самое значение
    // ещё раз (ревью задачи 13, круг 2, N11).
    onSuccess: (data) => { client.setQueryData(["prefs"], data) },
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

// Заведение и удаление старта меняют не один ответ, а четыре, и сброса
// ["sites"] мало.
//
// ["scan"] — GET /api/scan ходит по ВСЕЙ библиотеке (forecast.py:scan_week
// зовёт store.load_sites()), а его ключ (["scan", model]) про состав
// библиотеки ничего не знает. Без сброса вкладка «Все старты» до получаса
// (gcTime) показывает прежний список: удалённый старт остаётся в ней
// кликабельным и открывает прогноз ЧУЖОГО старта на свою дату, а заведённый
// не появляется вовсе — приложение даже не пытается перезапросить скан
// (финальное ревью ветки, C3).
//
// ["forecast", name] и ["windGrid", name] — потому что имя старта и есть его
// идентичность (store.find_site, /api/forecast?site=...), и оно
// переиспользуемо: правки старта в приложении нет, поправить координаты
// можно только «удалить и завести заново под тем же именем». Кэш по старому
// имени описывал бы уже другую точку — прогноз для координат, которых больше
// нет. Частичный ключ совпадает по префиксу, поэтому сбрасываются все
// диапазоны, даты и модели этого старта.
function invalidateSite(client: ReturnType<typeof useQueryClient>, name: string): void {
  void client.invalidateQueries({ queryKey: ["sites"] })
  void client.invalidateQueries({ queryKey: ["scan"] })
  void client.invalidateQueries({ queryKey: ["forecast", name] })
  void client.invalidateQueries({ queryKey: ["windGrid", name] })
}

export function useCreateSite(): UseMutationResult<Site, ApiError, SiteInput> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (site: SiteInput) => apiSend<Site>("POST", "/api/sites", site),
    retry: false,
    onSuccess: (created, site) => {
      // Заведённый старт кладётся в список СРАЗУ, ответом POST, и только потом
      // список перезапрашивается. Ждать перезапроса нельзя: тот, кто завёл
      // старт из выбиралки, тут же его и выбирает (App.tsx: pickNewSite), а
      // выбор действует, только пока имя есть в ЗАГРУЖЕННОМ списке (App.tsx:
      // selectionAlive). Пока перезапрос летит, шапка писала «Старт не
      // выбран», а «Прогноз» — «Выберите старт и день», хотя пилот только что
      // назвал старт; а отказавший перезапрос (useSites: retry: false)
      // оставлял его невыбранным навсегда и молча — обе шторки к тому моменту
      // закрыты, объяснить это уже негде.
      //
      // Тело ответа — тот же _public_site, что отдаёт и /api/sites
      // (api.py:create_site), поэтому список остаётся однородным. Порядок
      // здесь свой (в конец), а у сервера — по имени (store.load_sites:
      // ORDER BY name); поправит его перезапрос — этот список ему не замена,
      // а мост до его ответа.
      client.setQueryData<Site[]>(["sites"], (prev) => (prev === undefined ? undefined : [...prev, created]))
      invalidateSite(client, site.name)
    },
  })
}

export function useDeleteSite(): UseMutationResult<null, ApiError, string> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => apiSend<null>("DELETE", `/api/sites/${encodeURIComponent(name)}`),
    retry: false,
    onSuccess: (_data, name) => { invalidateSite(client, name) },
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
//
// `enabled` — «этому запросу пора уходить»: экран показан пилоту И действующая
// модель уже известна. Тяжёлые запросы скрытых вкладок тратили единственный
// слот пилота на сервере (api.py:one_at_a_time) раньше того экрана, на который
// он смотрит, а запрос, ушедший до ответа /api/prefs, считался ВТОРОЙ раз, как
// только модель появлялась в ключе кэша (финальное ревью ветки, I3 и I4).
// Условие «старт выбран» остаётся внутри хука — оно про сам запрос, а не про
// вызывающий экран.
export function useForecast(
  site: string | null, range: "1d", date: string | null, model: string | null, enabled?: boolean,
): UseQueryResult<Facts, ApiError>
export function useForecast(
  site: string | null, range: Exclude<ForecastRange, "1d">, date: string | null, model: string | null,
  enabled?: boolean,
): UseQueryResult<ForecastOverview, ApiError>
// `{ signal }` — из QueryFunctionContext, который TanStack Query передаёt
// каждому queryFn сам и «взводит», когда запрос перестал быть нужным (пилот
// сменил старт, ушёл с экрана). Он отдаётся ОЧЕРЕДИ, а не fetch: очередь
// снимает задачу, которая ещё не начиналась, и не трогает уже начатую —
// серверный слот на обрыв соединения не освобождается (api.py:80-96,
// request.is_disconnected() не вызывается нигде), и отпустить очередь раньше
// сервера значит гарантированно получить 429 на следующий запрос. Полный
// разбор — в шапке ./queue.
export function useForecast(
  site: string | null, range: ForecastRange, date: string | null, model: string | null, enabled = true,
): UseQueryResult<Facts | ForecastOverview, ApiError> {
  return useQuery({
    queryKey: ["forecast", site, range, date, model] as const,
    queryFn: ({ signal }) => heavy(() => apiGet<Facts | ForecastOverview>("/api/forecast", {
      site: site ?? undefined, range, date: date ?? undefined, model: model ?? undefined,
    }), signal),
    enabled: enabled && site !== null,
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
    queryFn: ({ signal }) => heavy(() => apiGet<WindGrid>("/api/forecast/wind-grid", {
      site: site ?? undefined, date: date ?? undefined, model: model ?? undefined,
    }), signal),
    // date у /api/forecast/wind-grid обязателен (api.py: `date: str`, без
    // значения по умолчанию) — запрос без даты сервер бы просто отклонил.
    enabled: site !== null && date !== null,
    retry: false,
    staleTime: STALE_TIME_MS,
    gcTime: GC_TIME_MS,
  })
}

// `enabled` — то же, что и у useForecast (см. комментарий там), плюс «в
// библиотеке есть хотя бы один старт»: /api/scan ходит за погодой по ВСЕЙ
// библиотеке, и на пустой спрашивать нечего.
export function useScan(model: string | null, enabled = true): UseQueryResult<Scan, ApiError> {
  return useQuery({
    queryKey: ["scan", model] as const,
    queryFn: ({ signal }) => heavy(() => apiGet<Scan>("/api/scan", { model: model ?? undefined }), signal),
    enabled,
    retry: false,
    staleTime: STALE_TIME_MS,
    gcTime: GC_TIME_MS,
  })
}

// ------------------------------------------------------------ разбор и маршрут
// Точка маршрута в "строчном" формате [lat, lon, name] — тот же формат, в
// котором маршруты хранятся в store и приходят из /api/routes и
// /api/route/parse. Третий элемент — `string | null`, а не просто `string`:
// route.py:Point.name типизирован `str | None` (route.py:330,
// `name=None` по умолчанию), и /api/route/parse отдаёт его как есть
// (api.py:parse_route — `[p.lat, p.lon, p.name]`). Один именованный тип на
// все три места, где эта строка встречается ниже (ParsedRoute, RouteInput,
// RouteSaveInput) — иначе шторка «Новый маршрут» (sheets/NewRouteSheet.tsx),
// которая читает результат useParseRoute и тут же отправляет его в
// useRoute/useSaveRoute, упёрлась бы в рассогласование типов между «своим»
// ответом парсера и «своим» же телом запроса маршрута.
export type RoutePointRow = [number, number, string | null]

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

// Поля повторяют api.py:RouteIn.
export type RouteInput = {
  points: RoutePointRow[]
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

export type ParsedRoute = { points: RoutePointRow[] }

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

export type RouteSaveInput = { name: string; points: RoutePointRow[] }

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

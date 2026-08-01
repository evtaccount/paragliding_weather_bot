/* Типы описывают файлы webapp/test/fixtures/*.json — настоящие ответы домена
 * (engine.py, forecast.py), снятые скриптом scripts/dump_api_fixtures.py на
 * данных tests/fixtures.py. Поле получает `| null` только если в снятом
 * файле оно реально встретилось равным null — иначе тип придуман бы по
 * памяти и разошёлся бы с бэкендом молча.
 *
 * Часть полей (site_match, storm_ahead, blocked_at_km, blocked_reason —
 * см. route.json) в этом снимке null везде: их предметная форма при
 * непустом значении сверена по route.py/criteria.py, а не выдумана.
 */

export type Model = { key: string; label: string }

export type Prefs = {
  avg_route_speed_kmh: number
  wind_correction_enabled: boolean
  model_key: string
  models: Model[]
}

export type Site = {
  name: string
  lat: number
  lon: number
  elevation_m: number
  aspect: string | null
  aspect_deg: number | null
  slope_deg: number | null
  route_top_m: number | null
  aliases: string[]
  notes: string
}

export type Assessment = {
  score: number | null
  category: string
  label_ru: string
  limiting_factor: string | null
  limiting_factor_ru: string | null
  fly_window: number[] | null
  confidence: number
  warnings: string[]
  vetoes_in_window: string[]
  unchecked_vetoes: string[]
}

export type WindLevel = {
  label: string
  alt_m_msl: number
  is_launch: boolean
  hourly: { hour: number; wind_ms: number; dir_deg: number }[]
}

export type WindGrid = {
  date: string
  timezone: string | null
  launch_m: number
  hours: number[]
  levels: WindLevel[]
}

// OverviewRow — форма ОДНОГО дня внутри GET /api/scan (forecast.py:scan_week,
// строит его через engine.overview_rows). Это НЕ форма ответа GET /api/forecast:
// у диапазонного /api/forecast (range=3d|week|2weeks) свой формат дня —
// см. ForecastOverview ниже. engine.overview_rows никогда не попадает в ответ
// /api/forecast (forecast.py:350-351: ветка "rows" зовёт overview_rows, а её
// читает только scan_week, а не get_facts).
export type OverviewRow = {
  date: string
  emoji: string
  label: string
  score: number
  category: string
  limiting: string | null
  confidence: number
  fly_window: number[] | null
  tmax: number
  wmax: number
  gmax: number
  dom: number
  precip: number
  wc: number
}

export type Scan = {
  sites: { name: string; aspect: string | null; days: OverviewRow[] }[]
  empty: string[]
  failed: string[]
}

export type SavedRoute = { name: string; points: (number | string)[][]; saved_at: string }

export type Elevation = { elevation_m: number }

// ---------------------------------------------------------- facts_1d.json

export type HourFact = {
  time: string
  temp_c: number
  wind_ms: number
  gust_ms: number
  dir_deg: number
  cloud_low_pct: number
  precip_mm: number
  cape: number
  sun_elev_deg: number
  sun_az_deg: number
  // slope_sun_index — null у старта без размеченной экспозиции: engine.py:
  // slope_sun_index() — «None when the aspect is unknown (ad-hoc point)».
  // Найдено эмпирически при прогоне facts_1d_no_ceiling.json (aspect: null) —
  // в исходном ревью этого поля не было, но tsc реально упал на нём.
  slope_sun_index: number | null
  // score/lim — criteria.py:HourAssessment.compact(): score может быть null
  // (533-534), lim (limiting) не ставится, когда ограничивать нечего (666-670).
  score: number | null
  cat: string
  lim: string | null
  // veto — ключ добавляется, только когда есть сработавшие вето
  // (criteria.py:536-537: `if self.vetoes: d["veto"] = self.vetoes`), поэтому
  // это необязательный ключ, а не поле с null. См. facts_1d_windy.json.
  veto?: string[]
}

export type Facts = {
  site: {
    name: string
    // aspect/aspect_deg — null у старта без размеченной экспозиции
    // (engine.py:1041: `card(aspect) if aspect is not None else None`).
    // См. facts_1d_no_ceiling.json (SITE_NO_ASPECT).
    aspect: string | null
    aspect_deg: number | null
    elevation_m: number
    // timezone — `data.get("timezone")` (engine.py:1042), тот же вызов, что и
    // в WindGrid.timezone (engine.py:925) и ForecastOverview.site.timezone
    // (engine.py:1105) — везде один и тот же `| null`, чтобы три копии одного
    // поля не разошлись в разные стороны.
    timezone: string | null
    model: string
  }
  date: string
  daylight_hours: string
  // thermal_window — null, когда термическое окно не открывается (engine.py:
  // sun_hours возвращает `window = None`, если не набралось часов с достаточной
  // высотой солнца). Не гипотеза: воспроизведено на настоящих координатах
  // Гудаури (42.47) с северной экспозицией в декабре — рабочий зимний сценарий
  // бота, не искусственная широта.
  thermal_window: {
    start_hour: number
    end_hour: number
    peak_hour: number
    solar_noon: string
  } | null
  criteria_version: string
  assessment: Assessment
  precip_sum_mm: number
  cape_max: number
  // freezing_level_m/thermal_ceiling_m_agl/msl — null, когда модель не отдаёт
  // boundary_layer_height/freezing_level_height (ECMWF, модель бота по
  // умолчанию — engine.py:_series_available, engine.py:1005-1006,1050-1052).
  // См. facts_1d_no_ceiling.json.
  freezing_level_m: number | null
  thermal_ceiling_m_agl: number | null
  thermal_ceiling_m_msl: number | null
  lcl_m_agl: number
  blue_thermals: boolean
  peak_hour: number
  fly_dir_deg: number
  dir_verdict: string
  dir_class: string
  caveats: string[]
  hourly_daytime: HourFact[]
  wind_profile_peak_hour: { level: string; alt_m_msl: number; wind_ms: number; dir_deg: number }[]
  // derived_peak_hour — engine.py:1070-1072 строит словарь через
  // `{k: v for k, v in derive_hour(...).items() if v is not None}`: параметр
  // без данных не зануляется, а ОТСУТСТВУЕТ как ключ. Поэтому каждое поле
  // необязательное (`?:`), а не `| null`. См. facts_1d_windy.json (нет
  // lifted_index) и facts_1d_no_ceiling.json (нет w_star/bl_depth/dir_offset/
  // base_over_route/foehn_suspect).
  derived_peak_hour: {
    wind_10m?: number
    wind_925?: number
    wind_850?: number
    gust_factor?: number
    gust_delta?: number
    dir_offset?: number
    w_star?: number
    bl_depth?: number
    thermal_index?: number
    cape?: number
    lifted_index?: number
    cloud_low?: number
    base_clearance?: number
    precip_prob?: number
    visibility?: number
    shear_100m?: number
    spread?: number
    window_hours?: number
    precip_mm?: number
    cin?: number
    wind_at_base?: number
    base_over_route?: number
    dir_misalign?: number
    ti_level_m?: number
    foehn_suspect?: boolean
  }
}

// ------------------------------------------------------------ forecast_3d.json
// GET /api/forecast?range=1d отдаёт Facts (engine.facts_1day) — форма выше.
// GET /api/forecast?range=3d|week|2weeks отдаёт СОВСЕМ ДРУГУЮ форму —
// engine.facts_overview (forecast.py:347-349: `engine.facts_1day(...) if rng ==
// "1d" else engine.facts_overview(data, site, rng)`). У неё свой site (без
// "model"), свой список дней ("days_daytime", а не "hourly_daytime") и другой
// набор ключей внутри дня. Экран обзора (задача 10) читает ЭТУ форму, когда
// открывает диапазон, а не Facts и не OverviewRow (тот — форма /api/scan,
// см. комментарий у OverviewRow выше).
export type ForecastOverview = {
  site: {
    name: string
    aspect: string | null
    aspect_deg: number | null
    elevation_m: number
    // Тот же `data.get("timezone")`, что и в Facts.site.timezone/WindGrid.timezone.
    timezone: string | null
  }
  range: string
  criteria_version: string
  fidelity: string
  days_daytime: {
    date: string
    weather: string
    temp_max_c: number
    temp_min_c: number
    wind_max_ms: number
    gust_max_ms: number
    wind_dir_window: string
    precip_mm: number
    sunshine_h: number
    // thermal_window — та же функция (engine.py:sun_summary → sun_hours), что и
    // у Facts.thermal_window, и то же условие null (см. комментарий там).
    thermal_window: {
      start_hour: number
      end_hour: number
      peak_hour: number
      solar_noon: string
    } | null
    assessment: Assessment
  }[]
}

// -------------------------------------------------------------- route.json
// Одна точка маршрута несёт "сырую" почасовую погоду под теми же ключами,
// что и открытый прогноз open-meteo (см. tests/fixtures.HOURLY_DEFAULTS).
//
// Каждое поле — `number | null`, а не только `number`: forecast.py:_hourly_facts
// (507-517) кладёт КЛЮЧ для каждой почасовой переменной БЕЗУСЛОВНО (`for key in
// H`), а вот значение — через route.interp/_bracket (route.py:542-563), которые
// возвращают None и когда всего ряда нет (модель его не отдаёт), и когда сам час
// внутри ряда null. Ключ не пропадает — пропадает только значение. Проверено:
// forecast._hourly_facts на теле с om_null(..., "boundary_layer_height",
// "freezing_level_height") — оба ключа присутствуют со значением None.
export type RouteWeather = {
  temperature_2m: number | null
  dew_point_2m: number | null
  relative_humidity_2m: number | null
  wind_speed_10m: number | null
  wind_gusts_10m: number | null
  wind_direction_10m: number | null
  wind_speed_80m: number | null
  wind_direction_80m: number | null
  wind_speed_120m: number | null
  wind_direction_120m: number | null
  precipitation: number | null
  precipitation_probability: number | null
  cape: number | null
  lifted_index: number | null
  convective_inhibition: number | null
  visibility: number | null
  shortwave_radiation: number | null
  cloud_cover_low: number | null
  cloud_cover_mid: number | null
  cloud_cover_high: number | null
  boundary_layer_height: number | null
  freezing_level_height: number | null
  temperature_850hPa: number | null
  temperature_700hPa: number | null
  relative_humidity_925hPa: number | null
  wind_speed_925hPa: number | null
  wind_direction_925hPa: number | null
  geopotential_height_925hPa: number | null
  wind_speed_850hPa: number | null
  wind_direction_850hPa: number | null
  geopotential_height_850hPa: number | null
  wind_speed_700hPa: number | null
  wind_direction_700hPa: number | null
  geopotential_height_700hPa: number | null
  wind_speed_600hPa: number | null
  wind_direction_600hPa: number | null
  geopotential_height_600hPa: number | null
  wind_speed_500hPa: number | null
  wind_direction_500hPa: number | null
  geopotential_height_500hPa: number | null
}

export type RoutePoint = {
  km: number
  leg_length_km: number
  role: string
  lat: number
  lon: number
  name: string | null
  track_bearing_deg: number
  // eta уходит в null, если расчётный прилёт попадает за полночь (данные
  // запрошены на один день дальше не считаются) — forecast.py:_evaluate
  // (`for s in over: s.eta_h = None`), проверено
  // tests/test_route_profile.py::test_arrival_past_midnight_is_truncated_and_reported.
  eta: string | null
  eta_fixed: string
  // terrain_m/terrain_point_m остаются null, если рельеф не получен —
  // route.py:attach_terrain делает `if not elevations or not grid: return` и
  // высоты сэмпла не проставляются; см. route_no_terrain.json.
  terrain_m: number | null
  terrain_point_m: number | null
  is_terrain_peak: boolean
  // cloud_base_m/working_band_m — null без рельефа (route.py:cloud_base_m /
  // working_band_m возвращают None при terrain_m is None) и дополнительно не
  // считаются вовсе для точек с eta is None (forecast.py:_evaluate пропускает
  // расчёт по `continue`, оставляя дефолт None у Sample).
  cloud_base_m: number | null
  working_band_m: number | null
  wind_along_kmh: number | null
  wind_cross_kmh: number | null
  wind_working_alt_kmh: number | null
  wind_working_alt_dir: number | null
  effective_ground_speed_kmh: number
  crab_limited: boolean
  // window — термическое окно; route.py:thermal_window возвращает None на
  // нескольких ветках (нет blh/radiation, астрономическое окно пусто, рабочих
  // часов не нашлось).
  window: { start_hour: number; end_hour: number } | null
  time_margin_min: number | null
  w_star_ms: number | null
  site_match: string | null
  // weather — {} (без единого ключа) у точек с eta is None (route.py:Sample.weather
  // по умолчанию `field(default_factory=dict)`, а forecast.py:_evaluate не
  // вызывает _hourly_facts для таких точек — см. eta выше); иначе — ПОЛНЫЙ набор
  // из 40 ключей (см. комментарий у RouteWeather), каждый — число или null.
  // Partial<RouteWeather> был неверен: он допускал ЧАСТИЧНО заполненный объект,
  // а домен отдаёт только "все 40 ключей" или "ни одного".
  weather: RouteWeather | Record<string, never>
  profile: string
  // score/category/limiting вместе становятся null, когда s.assessment is None
  // (forecast.py:_point_dict — `None if s.assessment is None else ...`,
  // то есть та же точка, что и eta is None выше). limiting дополнительно
  // может быть null и при существующей оценке: criteria.py — «если всё на
  // максимуме, ограничивать нечему — лимит-фактора нет» (a.limiting остаётся
  // None).
  score: number | null
  category: string | null
  limiting: string | null
  vetoes: string[]
  storm_ahead: { km: number; eta: string | null } | null
  is_turnpoint: boolean
  // thermal_ceiling_m — null без рельефа или без boundary_layer_height
  // (forecast.py:_ceiling_m: `if s.terrain_m is None or blh is None: return None`).
  thermal_ceiling_m: number | null
  // Набор ключей subs/groups зависит от профиля точки (takeoff/enroute/goal
  // считаются разными наборами критериев) — фиксированной формы у него нет.
  subs: Record<string, number>
  groups: Record<string, number>
}

export type RouteResult = {
  route: {
    // name — null у безымянного маршрута: поле запроса необязательно
    // (api.py:RouteIn — `name: str | None = None`), а домен кладёт его в
    // ответ как есть (forecast.py:799 — `"name": name`). Экран маршрута
    // сегодня получает именно null (App.tsx передаёт name={null}, пока
    // задача 13 не даёт выбрать сохранённый маршрут).
    name: string | null
    date: string
    departure: string
    timezone: string
    total_km: number
    avg_route_speed_kmh: number
    wind_correction_enabled: boolean
    sample_step_km: number
    sample_count: number
    model: string
  }
  points: RoutePoint[]
  // terrain — null, если Elevation API не ответил: forecast.py:get_route —
  // `"terrain": ({...} if elev else None)`. См. route_no_terrain.json.
  terrain: { km: number[]; elevations: number[] } | null
  verdict: {
    // score/mean_score — null, если ни одна точка не получила оценку
    // (criteria.py:score_route — `if not scored: return RouteAssessment(None,
    // *NO_DATA, ...)`, mean_score остаётся на дефолте None).
    score: number | null
    category: string
    label: string
    emoji: string
    feasibility: string
    // bottleneck — null в том же случае (RouteAssessment.bottleneck: dict |
    // None = None, не устанавливается в ветке `not scored`).
    // reason — null, если у самой слабой точки нет лимитирующего фактора
    // (criteria.py: `"reason": worst["assessment"].limiting`, а
    // HourAssessment.limiting: str | None).
    bottleneck: { km: number; score: number; reason: string | null } | null
    blocked_at_km: number | null
    blocked_reason: string | null
    flyable_until_km: number | null
    mean_score: number | null
    confidence: number
  }
  // score в каждой записи скана — null по той же причине, что и verdict.score
  // (тот же RouteAssessment на другое время вылета).
  departure_scan: { departure: string; score: number | null; feasibility: string }[]
  // best_departure — null, если ни один вариант вылета не «завершаемый»
  // (forecast.py:get_route — `best = max(completable, ...) if completable
  // else None`; tests/test_route_scored.py::test_best_departure_is_none_when_nothing_is_completable).
  best_departure: { departure: string; score: number | null; feasibility: string } | null
  reverse: { score: number | null; feasibility: string; better: boolean }
  notes: string[]
}

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
  slope_sun_index: number
  score: number
  cat: string
  lim: string
}

export type Facts = {
  site: {
    name: string
    aspect: string
    aspect_deg: number
    elevation_m: number
    timezone: string
    model: string
  }
  date: string
  daylight_hours: string
  thermal_window: {
    start_hour: number
    end_hour: number
    peak_hour: number
    solar_noon: string
  }
  criteria_version: string
  assessment: Assessment
  precip_sum_mm: number
  cape_max: number
  freezing_level_m: number
  thermal_ceiling_m_agl: number
  thermal_ceiling_m_msl: number
  lcl_m_agl: number
  blue_thermals: boolean
  peak_hour: number
  fly_dir_deg: number
  dir_verdict: string
  dir_class: string
  caveats: string[]
  hourly_daytime: HourFact[]
  wind_profile_peak_hour: { level: string; alt_m_msl: number; wind_ms: number; dir_deg: number }[]
  derived_peak_hour: {
    wind_10m: number
    wind_925: number
    wind_850: number
    gust_factor: number
    gust_delta: number
    dir_offset: number
    w_star: number
    bl_depth: number
    thermal_index: number
    cape: number
    lifted_index: number
    cloud_low: number
    base_clearance: number
    precip_prob: number
    visibility: number
    shear_100m: number
    spread: number
    window_hours: number
    precip_mm: number
    cin: number
    wind_at_base: number
    base_over_route: number
    dir_misalign: number
    ti_level_m: number
    foehn_suspect: boolean
  }
}

// -------------------------------------------------------------- route.json
// Одна точка маршрута несёт "сырую" почасовую погоду под теми же ключами,
// что и открытый прогноз open-meteo (см. tests/fixtures.HOURLY_DEFAULTS).

export type RouteWeather = {
  temperature_2m: number
  dew_point_2m: number
  relative_humidity_2m: number
  wind_speed_10m: number
  wind_gusts_10m: number
  wind_direction_10m: number
  wind_speed_80m: number
  wind_direction_80m: number
  wind_speed_120m: number
  wind_direction_120m: number
  precipitation: number
  precipitation_probability: number
  cape: number
  lifted_index: number
  convective_inhibition: number
  visibility: number
  shortwave_radiation: number
  cloud_cover_low: number
  cloud_cover_mid: number
  cloud_cover_high: number
  boundary_layer_height: number
  freezing_level_height: number
  temperature_850hPa: number
  temperature_700hPa: number
  relative_humidity_925hPa: number
  wind_speed_925hPa: number
  wind_direction_925hPa: number
  geopotential_height_925hPa: number
  wind_speed_850hPa: number
  wind_direction_850hPa: number
  geopotential_height_850hPa: number
  wind_speed_700hPa: number
  wind_direction_700hPa: number
  geopotential_height_700hPa: number
  wind_speed_600hPa: number
  wind_direction_600hPa: number
  geopotential_height_600hPa: number
  wind_speed_500hPa: number
  wind_direction_500hPa: number
  geopotential_height_500hPa: number
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
  // weather — {} (без единого ключа) у точек с eta is None (см. eta выше);
  // иначе полный набор почасовых величин. Partial честно отражает оба случая.
  weather: Partial<RouteWeather>
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
    name: string
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

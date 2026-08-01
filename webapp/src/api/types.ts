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
  fly_window: [number, number] | null
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
  fly_window: [number, number] | null
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
  eta: string
  eta_fixed: string
  terrain_m: number
  terrain_point_m: number
  is_terrain_peak: boolean
  cloud_base_m: number
  working_band_m: number
  wind_along_kmh: number
  wind_cross_kmh: number
  wind_working_alt_kmh: number
  wind_working_alt_dir: number
  effective_ground_speed_kmh: number
  crab_limited: boolean
  window: { start_hour: number; end_hour: number }
  time_margin_min: number
  w_star_ms: number
  site_match: string | null
  weather: RouteWeather
  profile: string
  score: number
  category: string
  limiting: string
  vetoes: string[]
  storm_ahead: { km: number; eta: string | null } | null
  is_turnpoint: boolean
  thermal_ceiling_m: number
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
  terrain: { km: number[]; elevations: number[] }
  verdict: {
    score: number
    category: string
    label: string
    emoji: string
    feasibility: string
    bottleneck: { km: number; score: number; reason: string }
    blocked_at_km: number | null
    blocked_reason: string | null
    flyable_until_km: number
    mean_score: number
    confidence: number
  }
  departure_scan: { departure: string; score: number; feasibility: string }[]
  best_departure: { departure: string; score: number; feasibility: string }
  reverse: { score: number; feasibility: string; better: boolean }
  notes: string[]
}

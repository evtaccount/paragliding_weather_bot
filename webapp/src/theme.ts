// Слияние переменных темы Telegram с запасной палитрой — целым,
// внутренне согласованным набором под конкретную схему, а не по одной
// переменной.
//
// Правка ревью task-6 (Important): раньше styles.css давал каждой
// переменной (--surface, --ink и т.д.) свой независимый запасной цвет из
// светлой палитры (var(--tg-bg-color, #FCFCFB) и т.п.), никак не
// привязанный к схеме. Telegram не гарантирует, что пришлёт все ключи
// themeParams — когда пришла только часть (например, только bg_color при
// colorScheme: "dark", как в App.test.tsx), --surface брал тёмное
// значение от Telegram, а --ink оставался на светлом запасном "#1C1C1A" —
// тоже тёмном на дисплее: контраст 1.08:1 при норме 4.5:1, текст
// физически не читается.
//
// Здесь схема (telegram.colorScheme() — она есть всегда, даже без
// themeParams) выбирает ОДНУ ИЗ ДВУХ полных согласованных палитр целиком
// (светлая/тёмная — те же hex, что в miniapp/prototype.html:11-20,
// 44-56), и уже поверх неё, ключ за ключом, накладываются те поля
// themeParams, которые Telegram реально прислал. Недостающие поля берут
// значение из ТОЙ ЖЕ схемы, что и присланные, — половина одного набора с
// половиной другого не смешивается ни при каком сочетании полей.

export type ColorScheme = "light" | "dark"

type Palette = Record<
  "--surface" | "--panel" | "--sunk" | "--ink" | "--muted" | "--faint" | "--rule" | "--air" | "--air-deep" | "--air-wash",
  string
>

const LIGHT_PALETTE: Palette = {
  "--surface": "#FCFCFB",
  "--panel": "#FFFFFF",
  "--sunk": "#F3F1EB",
  "--ink": "#1C1C1A",
  "--muted": "#6A6A63",
  "--faint": "#9E9E94",
  "--rule": "#E6E4DD",
  "--air": "#6EAAD2",
  "--air-deep": "#2F6F8F",
  "--air-wash": "rgba(110, 170, 210, .14)",
}

const DARK_PALETTE: Palette = {
  "--surface": "#14181C",
  "--panel": "#1B2127",
  "--sunk": "#0F1317",
  "--ink": "#E9E7E1",
  "--muted": "#98A1A8",
  "--faint": "#69727A",
  "--rule": "#28313A",
  "--air": "#7FB8E0",
  "--air-deep": "#9CC9EA",
  "--air-wash": "rgba(127, 184, 224, .13)",
}

// Ключ, который отдаёт telegram.themeVars() (`--tg-${snake_case → kebab}`),
// → наш слот палитры. --air-wash соответствия в Telegram не имеет —
// Telegram не присылает подложку под акцент, только сами цвета — поэтому
// всегда берётся из палитры схемы.
const PALETTE_KEY_FROM_TG: Record<string, keyof Palette> = {
  "--tg-bg-color": "--surface",
  "--tg-section-bg-color": "--panel",
  "--tg-secondary-bg-color": "--sunk",
  "--tg-text-color": "--ink",
  "--tg-hint-color": "--muted",
  "--tg-subtitle-text-color": "--faint",
  "--tg-section-separator-color": "--rule",
  "--tg-link-color": "--air",
  "--tg-button-color": "--air-deep",
}

export function resolveThemeVars(scheme: ColorScheme, tgVars: Record<string, string>): Record<string, string> {
  const base = scheme === "dark" ? DARK_PALETTE : LIGHT_PALETTE
  const resolved: Record<string, string> = { ...base }
  for (const [tgKey, cssVar] of Object.entries(PALETTE_KEY_FROM_TG)) {
    const value = tgVars[tgKey]
    if (value) resolved[cssVar] = value
  }
  return resolved
}

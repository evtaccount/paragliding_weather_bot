// Тонкая обёртка над window.Telegram.WebApp.
//
// Официальный SDK Telegram намеренно не используется (см. фазу 4, задача 2) —
// нужен только доступ к нескольким полям и методам глобального объекта,
// который скрипт telegram-web-app.js создаёт в настоящем клиенте Telegram
// (подключён в webapp/index.html). При открытии в обычном браузере этого
// объекта нет вообще, поэтому каждая функция здесь обязана деградировать
// тихо и никогда не бросать исключение — иначе пилот увидит белый экран
// вместо объяснения «откройте из Telegram».

interface BackButton {
  show(): void
  hide(): void
  onClick(handler: () => void): void
  offClick(handler: () => void): void
}

// Методы необязательные по той же причине, по которой необязателен сам
// HapticFeedback у WebApp: клиент может быть старше Bot API 6.1 (см. haptic()
// внизу файла).
interface HapticFeedback {
  impactOccurred?(style: "light" | "medium" | "heavy" | "rigid" | "soft"): void
  notificationOccurred?(type: "error" | "success" | "warning"): void
}

interface WebApp {
  initData: string
  colorScheme: "light" | "dark"
  themeParams: Record<string, string>
  ready(): void
  expand(): void
  BackButton: BackButton
  HapticFeedback?: HapticFeedback
}

declare global {
  interface Window {
    Telegram: { WebApp: WebApp }
  }
}

function webApp(): WebApp | undefined {
  return window.Telegram?.WebApp
}

let currentBackHandler: (() => void) | null = null

export function initData(): string {
  return webApp()?.initData ?? ""
}

export function colorScheme(): "light" | "dark" {
  return webApp()?.colorScheme ?? "light"
}

export function themeVars(): Record<string, string> {
  const params = webApp()?.themeParams
  if (!params) return {}
  const vars: Record<string, string> = {}
  for (const [key, value] of Object.entries(params)) {
    vars[`--tg-${key.replace(/_/g, "-")}`] = value
  }
  return vars
}

export function ready(): void {
  const app = webApp()
  app?.ready()
  app?.expand()
}

export function onBack(handler: (() => void) | null): void {
  const app = webApp()
  if (!app) return
  if (currentBackHandler) {
    app.BackButton.offClick(currentBackHandler)
  }
  currentBackHandler = handler
  if (handler) {
    app.BackButton.onClick(handler)
    app.BackButton.show()
  } else {
    app.BackButton.hide()
  }
}

// Вибро: короткое уведомление об отказе (ErrorBox — единственное место, где
// приложение показывает отказ сервера) и «щелчок» для остальных случаев.
//
// HapticFeedback проверяется отдельно от самого WebApp: он появился в Bot API
// 6.1, и в клиенте постарше объект Telegram есть, а этой группы методов у него
// нет. Обёртка обязана деградировать молча (см. шапку файла) — вибро приятно,
// но падать из-за него на весь экран нельзя; ровно так и оказалось при первом
// применении: экран ошибки уронил шесть тестов, потому что каждый подделывает
// в window.Telegram только те поля, которые ему нужны.
export function haptic(kind: "light" | "medium" | "error"): void {
  const feedback = webApp()?.HapticFeedback
  if (!feedback) return
  if (kind === "error") {
    feedback.notificationOccurred?.("error")
  } else {
    feedback.impactOccurred?.(kind)
  }
}

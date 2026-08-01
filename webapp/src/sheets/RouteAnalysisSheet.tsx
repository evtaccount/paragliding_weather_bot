// Тело шторки «Разбор маршрута» — вызывает useRouteAnalysis() один раз при
// открытии (шторка монтируется заново на каждый sheets.push, см. App.tsx),
// показывает Spinner до ответа, затем текст. Раскладка — openRouteAI
// (miniapp/prototype.html:1556-1576): бейдж с источником, текст разбора.
//
// Тело запроса — те же points/name/date/departure/model, что сейчас
// показывает экран «Маршрут» (Route.tsx передаёт их как есть): разбор
// говорит про ТОТ маршрут и ТО время вылета, которые пилот видит на экране,
// а не всегда про самый первый вариант.
//
// Как и DayAnalysisSheet.tsx (задача 9): здесь НАМЕРЕННО нет стража против
// повторного вызова mutate() в эффекте. Под <StrictMode> (main.tsx
// оборачивает им всё приложение безусловно) React синхронно отписывает и
// переподписывает внутренний слушатель useSyncExternalStore, на котором
// построен useMutation (@tanstack/query-core, mutationObserver.ts:96-100) —
// страж-флаг блокировал бы именно тот повторный вызов, который возвращает
// наблюдателя на мутацию, и первая (реально выполняющаяся) мутация осталась
// бы без наблюдателя навсегда (Critical, task-9 review). Двойной вызов в
// dev — сам смысл <StrictMode> (проверка эффекта на неидемпотентность); в
// продакшен-сборке его не будет вовсе, а серверный кэш разбора (forecast.py)
// и клиентская очередь (api/queue.ts) не дают второму запросу тратить квоту
// Gemini впустую.
import { useEffect, useRef } from "react"
import { useRouteAnalysis } from "../api/queries"
import type { RoutePointRow } from "../api/queries"
import { ErrorBox } from "../ui/ErrorBox"
import { Spinner } from "../ui/Spinner"

type RouteAnalysisSheetProps = {
  points: RoutePointRow[]
  name: string | null
  date: string
  departure: string | null
  model: string | null
}

export function RouteAnalysisSheet({ points, name, date, departure, model }: RouteAnalysisSheetProps) {
  const analysis = useRouteAnalysis()
  const { mutate } = analysis
  // ДЕФЕКТ ДЛЯ КРАСНОЙ ФАЗЫ (временно): страж от повторного вызова.
  const called = useRef(false)

  useEffect(() => {
    if (called.current) return
    called.current = true
    mutate({ points, name, date, departure, model })
  }, [points, name, date, departure, model, mutate])

  if (analysis.isSuccess) {
    return (
      <div>
        <span
          style={{
            display: "inline-block", padding: "4px 9px", borderRadius: 7, fontSize: 11, fontWeight: 600,
            color: "var(--panel)", background: "var(--air-deep)",
          }}
        >
          Gemini · по профилю маршрута
        </span>
        <p style={{ whiteSpace: "pre-wrap", marginTop: 12, marginBottom: 12, fontSize: 13.5, lineHeight: 1.5 }}>
          {analysis.data.text}
        </p>
        <div style={{ fontSize: 11, color: "var(--faint)" }}>
          Модель называет только числа из профиля маршрута; вердикт — её интерпретация
        </div>
      </div>
    )
  }

  if (analysis.isError) {
    return <ErrorBox error={analysis.error} onRetry={() => mutate({ points, name, date, departure, model })} />
  }

  return <Spinner />
}

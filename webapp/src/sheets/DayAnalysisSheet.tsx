// Тело шторки «Разбор от ИИ» — вызывает useAnalysis() один раз при
// открытии (шторка монтируется заново на каждый sheets.push, см. App.tsx),
// показывает Spinner до ответа, затем текст. Раскладка — openDayAI
// (miniapp/prototype.html:1533-1555): бейдж с источником, текст разбора,
// приписка про то, что вердикт — интерпретация модели, а не новые факты.
//
// Текст приходит одной строкой без разметки (api/queries.ts: useAnalysis
// → { text: string }) — переносы строк сохраняются через white-space:
// pre-wrap (бриф, task-9-brief.md), а не разбором на параграфы: сервер не
// присылает структуру внутри текста, только сам текст.
//
// Автоповтора нет (глобальное ограничение задачи) — при отказе (в т.ч. 429
// от guards.INFLIGHT, если пилот успел открыть что-то ещё тяжёлое) ErrorBox
// показывает текст ошибки и кнопку «Повторить», которая просто вызывает ту
// же мутацию заново по нажатию.
import { useEffect, useRef } from "react"
import { useAnalysis } from "../api/queries"
import { ErrorBox } from "../ui/ErrorBox"
import { Spinner } from "../ui/Spinner"

type DayAnalysisSheetProps = {
  site: string
  date: string | null
  model: string | null
}

export function DayAnalysisSheet({ site, date, model }: DayAnalysisSheetProps) {
  const analysis = useAnalysis()
  const { mutate } = analysis
  // main.tsx оборачивает приложение в <StrictMode> — в dev-сборке React
  // намеренно монтирует, размонтирует и заново монтирует компонент при
  // первом рендере, чтобы поймать эффекты без очистки. Без этой защиты
  // useAnalysis() (heavy-мутация, поход к Gemini) ушёл бы В DEV-РЕЖИМЕ
  // дважды на одно открытие шторки — то самое "тихое удвоение расхода
  // квоты", которого api/queue.ts и client.ts избегают для повторов по
  // таймеру; ref переживает фиктивный размонтаж/монтаж StrictMode (в
  // отличие от useState) и гарантирует ровно один вызов на настоящее
  // открытие шторки.
  const requested = useRef(false)

  useEffect(() => {
    if (requested.current) return
    requested.current = true
    mutate({ site, range: "1d", date, model })
  }, [site, date, model, mutate])

  if (analysis.isSuccess) {
    return (
      <div>
        <span
          style={{
            display: "inline-block",
            padding: "4px 9px",
            borderRadius: 7,
            fontSize: 11,
            fontWeight: 600,
            color: "var(--panel)",
            background: "var(--air-deep)",
          }}
        >
          Gemini · по фактам open-meteo
        </span>
        <p style={{ whiteSpace: "pre-wrap", marginTop: 12, marginBottom: 12, fontSize: 13.5, lineHeight: 1.5 }}>
          {analysis.data.text}
        </p>
        <div style={{ fontSize: 11, color: "var(--faint)" }}>
          Модель называет только числа из прогноза; вердикт — её интерпретация
        </div>
      </div>
    )
  }

  if (analysis.isError) {
    return <ErrorBox error={analysis.error} onRetry={() => mutate({ site, range: "1d", date, model })} />
  }

  return <Spinner />
}

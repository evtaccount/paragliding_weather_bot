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
//
// Ревью (task-9): здесь НАМЕРЕННО нет стража против повторного вызова
// mutate() в dev-режиме под <StrictMode> (main.tsx оборачивает им всё
// приложение безусловно). Первая версия такого стража (useRef-флаг)
// оказалась Critical-дефектом, а не защитой: под <StrictMode> React
// синхронно отписывает и переподписывает внутренний слушатель
// useSyncExternalStore, на котором построен useMutation
// (@tanstack/query-core, mutationObserver.ts:96-100 — onUnsubscribe снимает
// observer с ТЕКУЩЕЙ мутации, если слушателей не осталось); отписанный
// observer возвращается на мутацию только ПОВТОРНЫМ вызовом mutate() —
// именно его страж и блокировал. В результате первая (реально
// выполняющаяся) мутация оставалась без единого наблюдателя, и её
// результат было некому доставить: шторка вечно висела на Spinner, без
// единой ошибки в консоли (см. App.test.tsx: «под строгим режимом
// разработки открытие «Разбор от ИИ» доходит до текста, а не виснет» —
// красная фаза воспроизводится ТОЛЬКО через настоящий клик в настоящем
// дереве, не прямым рендером шторки в изоляции).
//
// Двойной вызов mutate() в dev — ровно то, ради чего существует
// <StrictMode>: он проверяет эффект на неидемпотентность. В продакшен-
// сборке (`vite build`) двойного вызова не будет вовсе — там StrictMode
// ничего не делает. А в самом dev-режиме второй запрос не тратит
// реальную квоту Gemini впустую: forecast.py держит серверный кэш разбора
// (`_acache`, ключ site+range+date+model+deep, комментарий в исходнике —
// «so a repeat button press is free»), и клиентская очередь (api/queue.ts)
// в любом случае не даёт второму запросу уйти в сеть раньше, чем придёт
// ответ на первый, — так что к моменту, когда второй реальный запрос
// долетает до сервера, кэш уже тёплый.
import { useEffect } from "react"
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

  useEffect(() => {
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

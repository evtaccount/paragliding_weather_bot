// Экран «Прогноз»: вердикт дня, полоса часов, столб воздуха, строка
// ограничения, оговорки, кнопки шторок — порядок ровно из task-8-brief.md
// ("Порядок на экране"), а не из порядка блоков в макете: в
// miniapp/prototype.html:739-942 (renderDay) строка ограничения (lim)
// нарисована ВНУТРИ той же панели, что вердикт и полоса часов (panel p1,
// до столба воздуха), а кнопки действий (acts) — до оговорок (caveats).
// Бриф явно перечисляет другой порядок (ограничение после столба воздуха,
// оговорки перед кнопками) — это разрешено раскладкой макета для ОТДЕЛЬНЫХ
// приборов (какие данные показывать и как), но порядок экрана как целого
// задаёт бриф, и ревью задачи 8 поймало первую попытку буквально повторить
// вложенность макета вместо явно прописанного порядка. Раскладка каждого
// прибора внутри (вердикт+полоса часов в одной панели, столб воздуха — в
// отдельной) взята из макета, само чередование блоков — из брифа. Секция
// "факты" макета (диапазон температуры/ветра/направления/осадков, строки
// 892-910) сюда не перенесена — её нет в перечне экранных элементов брифа.
import { useForecast } from "../api/queries"
import type { Facts } from "../api/types"
import { useSheetsContext } from "../App"
import { AirColumn } from "../charts/AirColumn"
import { HourStrip } from "../charts/HourStrip"
import { colorOfCategory } from "../charts/palette"
import { fmtHour } from "../format"
import { DayAnalysisSheet } from "../sheets/DayAnalysisSheet"
import { MeteogramSheet } from "../sheets/MeteogramSheet"
import { WindGridSheet } from "../sheets/WindGridSheet"
import { ErrorBox } from "../ui/ErrorBox"
import { Spinner } from "../ui/Spinner"

type ForecastProps = {
  site: string | null
  date: string | null
  model: string | null
  // Показан ли экран и известна ли действующая модель — см. подробный разбор
  // у OverviewProps.active и у `enabled` в api/queries.ts. Экран «Прогноз»
  // виден первым при открытии приложения, но скрытым он бывает не реже
  // других: пилот на «Маршруте» жмёт чип модели, и прогноз скрытой вкладки
  // занимает единственный слот сервера раньше маршрута, на который пилот
  // смотрит (финальное ревью ветки, I3).
  active?: boolean
}

// fly_window — null, когда лётное окно не открывается вовсе (см.
// facts_1d_no_window.json: assessment.fly_window null) — часы не
// выдумываются, текст говорит об этом прямо.
function windowLabel(window: number[] | null): string {
  const start = window?.[0]
  const end = window?.[1]
  if (start === undefined || end === undefined) return "окно не определено"
  return `${fmtHour(start)} – ${fmtHour(end)}`
}

// thermal_window — null по той же причине (engine.py:sun_hours), что и
// fly_window, но это отдельное поле про солнце на склоне, а не про
// лётность само по себе — текст сформулирован иначе (не "окно не
// определено"), чтобы поиск текста в тесте мог отличить одну подпись от
// другой, а не поймать сразу обе.
function thermalWindowLabel(facts: Facts): string {
  const tw = facts.thermal_window
  const sun = tw === null
    ? "термическое окно не открывается"
    : `солнце на склоне ${fmtHour(tw.start_hour)}–${fmtHour(tw.end_hour)}`
  return `${sun} · световой день ${facts.daylight_hours}`
}

export function Forecast({ site, date, model, active = true }: ForecastProps) {
  const sheets = useSheetsContext()
  const forecast = useForecast(site, "1d", date, model, active)

  // Нет сохранённых стартов (свежая установка — старты заводятся на
  // вкладке «Настройки») — понятный текст вместо вечной загрузки: useForecast сам
  // никогда не завершит "загрузку", пока site === null (enabled: false в
  // queries.ts), то же рассуждение, что и для шапки в App.tsx.
  if (site === null) {
    return (
      <div className="empty">
        <b>Нет стартов</b>
        Добавьте старт, чтобы увидеть прогноз.
      </div>
    )
  }
  if (forecast.isPending) {
    return <Spinner />
  }
  if (forecast.isError) {
    return <ErrorBox error={forecast.error} onRetry={() => { void forecast.refetch() }} />
  }

  const facts = forecast.data
  const { assessment } = facts

  return (
    <>
      <div className="panel panel--flush">
        <div className="panel__head" style={{ padding: "0 14px" }}>
          <span className="lbl">Лётное окно</span>
          <span className="lbl">пик {fmtHour(facts.peak_hour)}</span>
        </div>
        <div className="verdict" style={{ padding: "0 14px" }}>
          <div>
            <div className="verdict__win">{windowLabel(assessment.fly_window)}</div>
            <div className="verdict__sub">{thermalWindowLabel(facts)}</div>
          </div>
          <div className="verdict__score">
            <div className="verdict__num" style={{ color: colorOfCategory(assessment.category) }}>
              {assessment.score ?? "—"}
            </div>
            <div className="verdict__cat">{assessment.label_ru}</div>
          </div>
        </div>
        <div className="strip">
          <HourStrip hours={facts.hourly_daytime} window={assessment.fly_window} />
        </div>
      </div>

      <div className="panel">
        <div className="panel__head">
          <span className="lbl">Столб воздуха</span>
          <span className="lbl">метры MSL</span>
        </div>
        <AirColumn facts={facts} />
      </div>

      {assessment.limiting_factor_ru !== null && (
        <div className="limiting">
          <span className="limiting__k">Ограничивает</span>
          <span>{assessment.limiting_factor_ru}</span>
        </div>
      )}

      {facts.caveats.length > 0 && (
        <div className="panel caveats">
          <div className="lbl">Оговорки</div>
          <ul>
            {facts.caveats.map((c, i) => <li key={`${i}-${c}`}>{c}</li>)}
          </ul>
        </div>
      )}

      <div className="acts">
        <button
          type="button"
          className="act"
          onClick={() => sheets.push(<WindGridSheet site={site} date={date} model={model} />, "Ветер по высотам")}
        >
          <b>Ветер по высотам</b>
          {/* Чисел здесь нет намеренно. Форма таблицы не постоянна: уровней
              остаётся столько, сколько их выше старта плюс один ближайший
              снизу (engine.py:919-923), а столбцов — сколько светлых часов у
              этой даты (daylight_idx). Подпись «6 уровней × 10 часов» была
              неверна уже на собственной фикстуре проекта (wind_grid.json —
              5 × 16) и стала бы врать заново при каждой смене старта или
              сезона (финальное ревью ветки, I3). Настоящие числа показывает
              сама шторка, когда ответ пришёл (sheets/WindGridSheet.tsx). */}
          <span>таблица «высота × час» на этот день</span>
        </button>
        <button
          type="button"
          className="act"
          onClick={() => sheets.push(<DayAnalysisSheet site={site} date={date} model={model} />, "Разбор от ИИ")}
        >
          <b>Разбор от ИИ</b>
          <span>Gemini по этим числам</span>
        </button>
        <button
          type="button"
          className="act act--wide"
          onClick={() => sheets.push(<MeteogramSheet facts={facts} />, "Метеограмма")}
        >
          <b>Метеограмма</b>
          <span>температура, ветер, порывы</span>
        </button>
      </div>
    </>
  )
}

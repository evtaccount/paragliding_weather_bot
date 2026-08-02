// Выбиралка дня — вторая половина явного выбора в шапке: старт отвечает «где
// я лечу», день — «когда». До этой задачи день не выбирался вовсе: оболочка
// подставляла сегодняшний, и приложение открывалось готовым прогнозом, о
// котором пилот не просил.
//
// Раскладка и поведение — как у соседней SitePickerSheet: тот же список
// `.pick`, галочка у выбранного, нажатие закрывает шторку (закрывает её
// оболочка, App.tsx: pickDate — здесь только колбэк).
//
// Данных с сервера шторке не нужно вовсе: список дней считается из часов
// устройства и глубины прогноза домена. Поэтому здесь нет ни одного хука
// данных — в отличие от SitePickerSheet, которой список стартов приходится
// читать самой (шторка кладётся в стек готовым элементом, и проп со списком
// застыл бы на момент нажатия, ревью задачи 13 N2).
import { RANGE_DAYS_2WEEKS } from "../domain"
import { fmtDate, isoDate } from "../format"

type DayPickerProps = {
  // Сырой выбор пилота: null — явного выбора ещё не было, и не отмечен ни
  // один день (шапка в этом состоянии пишет «День не выбран»).
  selected: string | null
  onPick: (date: string) => void
}

// Ближайшие дни, начиная с сегодняшнего. Сколько именно — решает домен
// (engine.RANGE_DAYS["2weeks"], копия в ../domain под сверкой
// tests/test_webapp_sync.py): это самый дальний день, на который прогноз
// вообще считается.
//
// Дата берётся по местному поясу устройства (isoDate, ../format), а сдвиг —
// через setDate: переход через конец месяца и переводы часов он берёт на себя
// сам, в отличие от арифметики по миллисекундам.
function nextDays(): string[] {
  const today = new Date()
  return Array.from({ length: RANGE_DAYS_2WEEKS }, (_, offset) => {
    const day = new Date(today)
    day.setDate(today.getDate() + offset)
    return isoDate(day)
  })
}

// «сегодня» и «завтра» — то же, чем эти два дня называет чат (bot.py:
// /day и /tomorrow): в них пилот попадает чаще всего, и дату для них
// приходится сверять с календарём. Дальше слов нет: «послезавтра» уже
// требует счёта, а дата видна и так.
function dayLabel(iso: string, offset: number): string {
  const date = fmtDate(iso)
  if (offset === 0) return `сегодня, ${date}`
  if (offset === 1) return `завтра, ${date}`
  return date
}

export function DayPickerSheet({ selected, onPick }: DayPickerProps) {
  return (
    <div className="pick">
      {nextDays().map((iso, offset) => (
        <button
          key={iso}
          type="button"
          aria-pressed={iso === selected}
          onClick={() => onPick(iso)}
        >
          <b>{dayLabel(iso, offset)}</b>
          {iso === selected && <em>✓</em>}
        </button>
      ))}
    </div>
  )
}

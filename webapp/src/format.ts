// Форматирование чисел, дат, направлений ветра и часов — общее для всех
// экранов мини-приложения.
//
// Числа и румбы взяты дословно из miniapp/prototype.html (единственный
// источник вёрстки и форматов, см. task-6-brief): `num` (строка 715) и
// `CARD16`/`compass` (строки 497-499) — чтобы вид совпадал с тем, что бот
// уже показывает пилоту в PNG-графиках и тексте.
//
// Дата (`fmtDate`) и час (`fmtHour`) в макете форматируются иначе (там —
// сокращённый месяц и заглавный день недели для внутреннего прототипа);
// здесь формат продиктован дословным тестом task-6-brief (Step 1) —
// "сб, 25 июля": строчный день недели, число без ведущего нуля, месяц
// полным словом в родительном падеже.

const CARD16 = ["С", "ССВ", "СВ", "ВСВ", "В", "ВЮВ", "ЮВ", "ЮЮВ", "Ю", "ЮЮЗ", "ЮЗ", "ЗЮЗ", "З", "ЗСЗ", "СЗ", "ССЗ"]

const WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

const MONTHS_GENITIVE = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

export function fmtNum(v: number, dec?: number): string {
  return v.toFixed(dec ?? 0).replace(".", ",")
}

export function compass(deg: number): string {
  const normalized = ((deg % 360) + 360) % 360
  return CARD16[Math.round(normalized / 22.5) % 16]!
}

export function fmtDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00`)
  const weekday = WEEKDAYS[(date.getDay() + 6) % 7]!
  const month = MONTHS_GENITIVE[date.getMonth()]!
  return `${weekday}, ${date.getDate()} ${month}`
}

// Дата сохранения маршрута из значения поля SavedRoute.saved — полного
// ISO-таймстампа в UTC (store.py:88-89 пишет `2026-07-25T06:33:49+00:00`).
// Перевод в местный пояс обязателен и делается ровно там же, где его делает
// чат (bot.py:1058 _local_date): store пишет UTC — однозначно и сортируемо, —
// а пилот живёт в поясе старта, и вечером после сохранения UTC-дата это ещё
// «вчера». Пояс берётся с устройства (new Date(...) без указания зоны) — тот
// же источник, что у «сегодня» в шапке приложения (App.tsx: todayIso).
//
// Запасной путь на неразобранной строке — как в боте: показать то, что
// пришло, до "T", а не «Invalid Date». Старая запись чужого формата у пилота
// в базе есть, а падать подписи маршрута из-за неё не из-за чего.
export function fmtSavedDate(iso: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return iso.split("T")[0] ?? iso
  const month = String(at.getMonth() + 1).padStart(2, "0")
  const day = String(at.getDate()).padStart(2, "0")
  return `${at.getFullYear()}-${month}-${day}`
}

// м/с с одним знаком после запятой — то же соглашение, что в макете для
// скорости ветра (`num(v, 1) + " м/с"`, см. строки 812, 905, 972, 1518).
export function fmtWind(ms: number): string {
  return `${fmtNum(ms, 1)} м/с`
}

export function fmtHour(h: number): string {
  return `${String(h).padStart(2, "0")}:00`
}

// Число точек маршрута с правильным окончанием: 1 точка, 2 точки, 5 точек,
// 11 точек, 21 точка. Нужно в двух местах — в подписи сохранённого маршрута
// («N точек · дата», sheets/SavedRoutesSheet.tsx) и на кнопке «Показать
// маршрут» в шторке нового маршрута, — поэтому живёт здесь, а не копией в
// каждой шторке. Правило обычное для русского счёта: 11-14 всегда «точек»,
// иначе смотрим на последнюю цифру.
export function fmtPoints(count: number): string {
  const lastTwo = Math.abs(count) % 100
  const last = Math.abs(count) % 10
  if (lastTwo >= 11 && lastTwo <= 14) return `${count} точек`
  if (last === 1) return `${count} точка`
  if (last >= 2 && last <= 4) return `${count} точки`
  return `${count} точек`
}

// Даты ближайших дней для тестов — СВОЕЙ арифметикой, независимой от той,
// которой их считает продукт (sheets/DayPickerSheet.tsx: nextDays + isoDate).
// Возьми тест значения у продукта — сдвиг на день уехал бы в обе стороны
// сразу и остался бы незамеченным.
//
// Общий модуль, а не копия в каждом файле тестов: дни нужны и тестам шторки
// (sheets/forms.test.tsx), и тестам всего приложения (src/App.test.tsx), а
// две копии одной арифметики расходятся ровно так же, как расходятся копии
// знания в продукте.
export function isoInDays(offset: number): string {
  const day = new Date()
  day.setDate(day.getDate() + offset)
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`
}

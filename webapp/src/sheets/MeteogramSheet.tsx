// Тело шторки «Метеограмма» — рисует уже загруженные данные экрана
// «Прогноз» (facts.hourly_daytime/assessment.fly_window уже на экране),
// отдельного запроса не делает: то же правило, что и у прочих приборов
// (HourStrip/AirColumn) — вкладка «Прогноз» грузит Facts один раз, шторки
// только показывают его иначе.
import type { Facts } from "../api/types"
import { Meteogram } from "../charts/Meteogram"

type MeteogramSheetProps = { facts: Facts }

export function MeteogramSheet({ facts }: MeteogramSheetProps) {
  return <Meteogram hours={facts.hourly_daytime} window={facts.assessment.fly_window} />
}

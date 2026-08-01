// Экран «Настройки» — раскладка из макета (renderSet,
// miniapp/prototype.html:1363-1468): метеомодель, маршрут, старты.
//
// Раздела «Доступ» из макета здесь нет: список допущенных и пауза между
// запросами живут в переменных окружения бота (ALLOWED_USER_IDS, guards.py),
// наружу их не отдаёт ни один эндпоинт api.py — показать их можно было бы
// только выдуманными числами.
//
// Настройки правятся по одному полю: PATCH /api/prefs принимает любое
// подмножество (api.py:PrefsPatch — все поля необязательные), поэтому
// переключение тумблера не перезаписывает скорость и наоборот.
//
// Пределы (скорость 10–45 км/ч — store.SPEED_MIN/MAX, набор ключей моделей —
// engine.MODELS) на клиенте не продублированы: шаг «плюс» отправляет
// значение, и если сервер его не принял, показывается его же объяснение.
import { useState } from "react"
import { usePrefs, useSites, useUpdatePrefs } from "../api/queries"
import type { Site } from "../api/types"
import { useSheetsContext } from "../App"
import { fmtNum } from "../format"
import { AddSiteSheet } from "../sheets/AddSiteSheet"
import { ModelPickerSheet } from "../sheets/ModelPickerSheet"
import { SiteEditorSheet, siteSubtitle } from "../sheets/SitePickerSheet"
import { ErrorBox } from "../ui/ErrorBox"
import { Row } from "../ui/Row"
import { Spinner } from "../ui/Spinner"

type SettingsProps = {
  // Какой старт сейчас показывает приложение — строка этого старта помечена
  // «активен», как в макете (renderSet, строка 1431).
  currentSite: string | null
  // Разовая модель и оба способа её сменить живут в оболочке (App.tsx): это
  // состояние ВСЕГО приложения, а не экрана настроек, — тот же выбор делает
  // чип в шапке.
  onceModel: string | null
  onPickOnce: (key: string) => void
  onPickPermanent: (key: string) => void
  onOpenSiteForecast: (name: string) => void
}

export function Settings({
  currentSite, onceModel, onPickOnce, onPickPermanent, onOpenSiteForecast,
}: SettingsProps) {
  const sheets = useSheetsContext()
  const prefs = usePrefs()
  const sites = useSites()
  const update = useUpdatePrefs()
  // Черновики скорости и тумблера — на время, пока PATCH в пути: до ответа
  // сервера в кэше лежит прежнее значение, и без черновика второе нажатие
  // «плюс» отправило бы то же самое число, а тумблер визуально не сдвинулся
  // бы вовсе. Отказ сервера сбрасывает черновик — на экране снова правда из
  // store, а не то, что пилот хотел.
  const [speedDraft, setSpeedDraft] = useState<number | null>(null)
  const [windDraft, setWindDraft] = useState<boolean | null>(null)

  if (prefs.isPending) return <Spinner />
  if (prefs.isError) return <ErrorBox error={prefs.error} onRetry={() => { void prefs.refetch() }} />

  const speed = speedDraft ?? prefs.data.avg_route_speed_kmh
  const windOn = windDraft ?? prefs.data.wind_correction_enabled
  const modelLabel = prefs.data.models.find((m) => m.key === prefs.data.model_key)?.label ?? prefs.data.model_key

  function stepSpeed(delta: number): void {
    const next = speed + delta
    setSpeedDraft(next)
    update.mutate({ avg_route_speed_kmh: next }, { onError: () => setSpeedDraft(null) })
  }

  function toggleWind(): void {
    const next = !windOn
    setWindDraft(next)
    update.mutate({ wind_correction_enabled: next }, { onError: () => setWindDraft(null) })
  }

  function openModelSheet(): void {
    sheets.push(
      <ModelPickerSheet
        models={prefs.data?.models ?? []}
        permanent={prefs.data?.model_key ?? null}
        once={onceModel}
        onPickOnce={onPickOnce}
        onPickPermanent={onPickPermanent}
      />,
      "Метеомодель",
    )
  }

  function openSiteEditor(site: Site): void {
    sheets.push(
      <SiteEditorSheet site={site} onOpenForecast={onOpenSiteForecast} onDeleted={() => sheets.pop()} />,
      site.name,
    )
  }

  function openAddSite(): void {
    sheets.push(<AddSiteSheet sites={sites.data ?? []} onCreated={() => sheets.pop()} />, "Добавить старт")
  }

  return (
    <>
      <div className="lbl" style={{ padding: "6px 2px 0" }}>Метеомодель</div>
      <div className="rows">
        <Row
          title="Постоянная модель"
          subtitle="Ей считаются все прогнозы, пока не сменишь"
          value={<div className="row__v">{modelLabel} ›</div>}
          onClick={openModelSheet}
        />
        <Row
          title="Потолок термички"
          subtitle="Всегда считается по GFS — только она даёт высоту слоя перемешивания"
          value={<div className="row__v">GFS</div>}
        />
      </div>

      <div className="lbl" style={{ padding: "6px 2px 0" }}>Маршрут</div>
      <div className="rows">
        <Row
          title="Средняя маршрутная скорость"
          subtitle="С учётом наборов в термиках, не скорость крыла"
          value={
            <div className="stepper">
              <button type="button" aria-label="Уменьшить маршрутную скорость" onClick={() => stepSpeed(-1)}>−</button>
              <b>{fmtNum(speed)} км/ч</b>
              <button type="button" aria-label="Увеличить маршрутную скорость" onClick={() => stepSpeed(1)}>+</button>
            </div>
          }
        />
        {/* Строка-тумблер собрана здесь, а не через Row: доступная роль
            switch должна быть на САМОЙ нажимаемой строке. В макете
            role="switch" висит на декоративном кружке внутри кнопки — так
            скринридер объявляет строку обычной кнопкой, а состояние
            «включено/выключено» остаётся на элементе, который не нажимают. */}
        <button type="button" className="row" role="switch" aria-checked={windOn} onClick={toggleWind}>
          <div className="row__m">
            <div className="row__t">Учитывать ветер во времени прилёта</div>
            <div className="row__s">Марш вперёд: GS = V·cos(WCA) + попутная составляющая</div>
          </div>
          <span className="sw" aria-hidden="true" />
        </button>
      </div>
      {update.isError && (
        <ErrorBox
          error={update.error}
          onRetry={() => { if (update.variables) update.mutate(update.variables) }}
        />
      )}

      <div className="lbl" style={{ padding: "6px 2px 0" }}>Старты · {sites.data?.length ?? 0}</div>
      {sites.isError && <ErrorBox error={sites.error} onRetry={() => { void sites.refetch() }} />}
      <div className="rows">
        {(sites.data ?? []).map((site) => (
          <Row
            key={site.name}
            title={site.name}
            subtitle={`${fmtNum(site.lat, 3)}, ${fmtNum(site.lon, 3)} · ${siteSubtitle(site)}`}
            value={<div className="row__v">{site.name === currentSite ? "активен" : "›"}</div>}
            onClick={() => openSiteEditor(site)}
          />
        ))}
        <Row
          title="Добавить старт"
          subtitle="Координаты или точка на карте — высоту приложение возьмёт само"
          value={<div className="row__v">+</div>}
          onClick={openAddSite}
        />
      </div>

      <div className="attrib">Прогноз: Open-Meteo · рельеф: Copernicus DEM GLO-90 · разбор: Gemini</div>
    </>
  )
}

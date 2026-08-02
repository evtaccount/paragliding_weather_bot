// Шторка «Метеомодель» — раскладка из макета (openModelSheet,
// miniapp/prototype.html:1652-1694): два списка моделей, разовый и
// постоянный, и объяснение про потолок термички.
//
// Почему списка два. Разовая модель — параметр ЗАПРОСА (api.py:_model_for:
// `model=` из query побеждает настройку и никуда не сохраняется), постоянная
// — запись в store (PATCH /api/prefs → store.set_model). Это разные вещи для
// пилота: «посмотреть этот день ещё и по GFS» против «считать всё по GFS».
// Одна шторка на оба случая — как в макете: openModelSheet(scope) там тоже
// показывает оба списка, а не разные экраны.
//
// Список моделей приходит с сервера вместе с настройками (api.py:
// _prefs_payload кладёт [{key, label}] по engine.MODELS) — своего перечня
// моделей у приложения нет и быть не может: ключ, которого нет в
// engine.MODELS, сервер отклонит с 400. Читаются настройки ЗДЕСЬ, а не
// приходят пропами: шторку кладут в стек готовым элементом, и пропы застыли
// бы на момент нажатия — открытая до ответа /api/prefs шторка навсегда
// осталась бы с двумя пустыми списками (ревью задачи 13, N2).
//
// У пунктов нет подписи `<s>` из макета (там — `m.note`, короткое пояснение
// про модель, prototype.html:1659, 1677): api._prefs_payload шлёт только
// {key, label}, и брать пояснение неоткуда. Выдумывать текст про чужую
// метеомодель нельзя — это утверждение о том, чего приложение не знает.
import { usePrefs, useUpdatePrefs } from "../api/queries"
import { ErrorBox } from "../ui/ErrorBox"
import { Spinner } from "../ui/Spinner"

type Props = {
  // Разовая модель, выбранная в этом сеансе (null — разового выбора не было).
  // Пропом, а не из настроек: разовый выбор нигде не сохраняется и живёт
  // только в оболочке (App.tsx). Застыть он не может — выбор закрывает шторку.
  once: string | null
  onPickOnce: (key: string) => void
  // Зовётся только после УСПЕШНОГО PATCH: пока сервер не подтвердил, шторку
  // закрывать нельзя — иначе отказ (неизвестная модель, нет связи) пропал бы
  // вместе со шторкой.
  onPickPermanent: (key: string) => void
}

export function ModelPickerSheet({ once, onPickOnce, onPickPermanent }: Props) {
  const prefs = usePrefs()
  const update = useUpdatePrefs()

  function setPermanent(key: string): void {
    update.mutate({ model_key: key }, { onSuccess: () => onPickPermanent(key) })
  }

  if (prefs.isPending) return <Spinner />
  if (prefs.isError) return <ErrorBox error={prefs.error} onRetry={() => { void prefs.refetch() }} />

  const models = prefs.data.models
  const permanent = prefs.data.model_key

  return (
    <>
      <div className="lbl">Разово — только для этого прогноза</div>
      <div className="pick" role="group" aria-label="Разово — только для этого прогноза" style={{ marginTop: 7 }}>
        {models.map((m) => (
          <button key={m.key} type="button" aria-pressed={m.key === once} onClick={() => onPickOnce(m.key)}>
            <b>{m.label}</b>
            {m.key === once && <em>✓</em>}
          </button>
        ))}
      </div>

      <div className="lbl" style={{ display: "block", padding: "18px 0 7px" }}>
        Постоянная — для всех следующих запросов
      </div>
      <div className="pick" role="group" aria-label="Постоянная — для всех следующих запросов">
        {models.map((m) => (
          <button
            key={m.key}
            type="button"
            aria-pressed={m.key === permanent}
            disabled={update.isPending}
            onClick={() => setPermanent(m.key)}
          >
            <b>{m.label}</b>
            {m.key === permanent && <em>✓</em>}
          </button>
        ))}
      </div>

      {update.isPending && <Spinner />}
      {update.isError && (
        <ErrorBox
          error={update.error}
          onRetry={() => {
            const key = update.variables?.model_key
            if (key !== undefined) setPermanent(key)
          }}
        />
      )}

      {/* Потолок термички считается одной моделью независимо от выбранной:
          остальные не отдают высоту слоя перемешивания
          (engine._series_available, boundary_layer_height) — если этого не
          сказать, разница между «моделью прогноза» и «моделью потолка»
          выглядит как ошибка приложения. Имя модели берётся из настроек
          (prefs.ceiling_model, api.py:_prefs_payload по
          engine.CEILING_MODEL_KEY), а не пишется здесь словом «GFS» — см.
          разбор у той же строки на экране настроек (screens/Settings.tsx,
          финальное ревью ветки I1). */}
      <p className="prose" style={{ marginTop: 14 }}>
        <em>
          Потолок термички всегда считается по {prefs.data.ceiling_model.label}: остальные модели
          не отдают высоту слоя перемешивания. Смена модели здесь на это не влияет.
        </em>
      </p>
    </>
  )
}

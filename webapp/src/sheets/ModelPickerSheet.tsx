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
// engine.MODELS, сервер отклонит с 400.
import type { Model } from "../api/types"
import { useUpdatePrefs } from "../api/queries"
import { ErrorBox } from "../ui/ErrorBox"
import { Spinner } from "../ui/Spinner"

type Props = {
  models: Model[]
  // Постоянная модель пилота (prefs.model_key) и разовая, выбранная в этом
  // сеансе (null — разового выбора не было).
  permanent: string | null
  once: string | null
  onPickOnce: (key: string) => void
  // Зовётся только после УСПЕШНОГО PATCH: пока сервер не подтвердил, шторку
  // закрывать нельзя — иначе отказ (неизвестная модель, нет связи) пропал бы
  // вместе со шторкой.
  onPickPermanent: (key: string) => void
}

export function ModelPickerSheet({ models, permanent, once, onPickOnce, onPickPermanent }: Props) {
  const update = useUpdatePrefs()

  function setPermanent(key: string): void {
    update.mutate({ model_key: key }, { onSuccess: () => onPickPermanent(key) })
  }

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

      {/* Потолок термички считается по GFS независимо от выбранной модели:
          остальные модели не отдают высоту слоя перемешивания
          (engine._series_available, boundary_layer_height) — если этого не
          сказать, разница между «моделью прогноза» и «моделью потолка»
          выглядит как ошибка приложения. */}
      <p className="prose" style={{ marginTop: 14 }}>
        <em>
          Потолок термички всегда считается по GFS: остальные модели не отдают высоту слоя
          перемешивания. Смена модели здесь на это не влияет.
        </em>
      </p>
    </>
  )
}

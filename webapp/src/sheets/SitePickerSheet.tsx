// Две шторки про старты: выбор текущего старта (шапка приложения) и
// карточка старта с его удалением (экран настроек). Раскладки — из макета:
// openSiteSheet (miniapp/prototype.html:1632-1651) и openSiteEditor
// (1806-1836).
//
// Обе живут в одном файле, потому что это один разговор с пилотом про один
// и тот же список: выбиралка отвечает «на каком старте я сейчас», карточка —
// «что это за старт и нужен ли он вообще». Разнести их значило бы держать
// подпись старта (экспозиция · высота) в двух местах.
//
// Выбор идёт ПО ИМЕНИ, а не по индексу в списке: имя — ключ старта и в
// store (store.find_site), и в каждом запросе (/api/forecast?site=...).
// Индекс не переживает ни фоновую перезагрузку /api/sites, ни удаление
// соседнего старта — ровно этот класс дефекта был Critical задачи 10 (тап
// по дню второго старта открывал прогноз первого).
import { useState } from "react"
import { useDeleteSite, useSites } from "../api/queries"
import type { Site } from "../api/types"
import { colorOfCategory } from "../charts/palette"
import { compass, fmtNum } from "../format"
import { ErrorBox } from "../ui/ErrorBox"
import { Spinner } from "../ui/Spinner"

// Подпись старта под именем — то, чем старты различаются в поле: куда
// смотрит склон и на какой он высоте (макет, строка 1637). Экспозиция
// бывает не размечена (Site.aspect: string | null, engine.py:1041) —
// тогда о ней просто не говорится, а не печатается «null».
//
// Румб считается из градусов, а не берётся из Site.aspect: в /api/sites это
// поле — строка В ТОМ ВИДЕ, В КАКОМ ЕЁ ЗАПИСАЛ автор старта (store.py:216
// пишет как есть), и поставочный sites.json несёт латинское "S", а
// заведённый из чата или из приложения старт — «Ю» (bot.py:544,
// AddSiteSheet.tsx:128 зовут engine.card/compass). Соседние строки списка
// читались «S 180°» и «Ю 180°» — две системы обозначений в одном списке.
// Одно правило на всё приложение: румб — это compass(градусы), как в чате;
// авторская строка остаётся запасным вариантом ровно там, где градусов нет.
export function siteSubtitle(site: Site): string {
  const parts = [`${fmtNum(site.elevation_m)} м`]
  if (site.aspect_deg !== null) {
    parts.unshift(`${compass(site.aspect_deg)} ${fmtNum(site.aspect_deg)}°`)
  } else if (site.aspect !== null) {
    parts.unshift(site.aspect)
  }
  return parts.join(" · ")
}

type PickerProps = {
  // Выбор пилота; null — явного выбора ещё не было, и тогда не отмечен ни
  // один старт.
  selected: string | null
  onPick: (name: string) => void
  onAddSite: () => void
}

// Вход в карту из выбиралки: пилот открыл её, чтобы выбрать старт, и нужного
// в списке может не оказаться. Строка одна на обе ветки шторки — и на список
// стартов, и на пустую библиотеку: «нужного нет» одинаково верно в обоих
// случаях, а два разных предложения об одном и том же расходились бы.
//
// Имя кнопки намеренно НЕ повторяет строку экрана настроек («Добавить
// старт»): по этому имени в тестах настроек ищется кнопка отправки формы
// внутри самой шторки добавления, и одинаковые имена в одном дереве дали бы
// неоднозначный поиск.
function AddSiteButton({ onAddSite }: { onAddSite: () => void }) {
  return (
    <button type="button" onClick={onAddSite}>
      <b>Отметить новый на карте</b>
      <s>Тап по карте ставит точку — высоту приложение возьмёт само</s>
    </button>
  )
}

export function SitePickerSheet({ selected, onPick, onAddSite }: PickerProps) {
  // Список читается здесь, а не приходит пропом: шторку кладут в стек готовым
  // элементом, и проп застыл бы на момент нажатия — открытая до ответа
  // сервера шторка так навсегда оставалась с «Нет стартов» (ревью задачи 13,
  // N2). Запрос тот же самый (ключ ["sites"]), поэтому второго обращения к
  // сети не происходит — подписка на общий кэш.
  const sites = useSites()

  if (sites.isPending) return <Spinner />
  if (sites.isError) return <ErrorBox error={sites.error} onRetry={() => { void sites.refetch() }} />

  // Отмечен ровно тот старт, который выбрал пилот, и никакой иначе: запасного
  // старта в приложении больше нет (шапка при пустом выборе так и пишет —
  // «Старт не выбран»), а галочка у первого старта обещала бы выбор, которого
  // не было.
  const notes = sites.data.find((s) => s.name === selected)?.notes ?? ""

  // Пустая библиотека больше не отсылает на другую вкладку — старт заводится
  // не сходя со шторки. Заголовок «Нет стартов» дословный: по нему отличают
  // «стартов нет» от «список ещё не пришёл» (forms.test.tsx, тест про
  // шторку, открытую до ответа сервера).
  if (sites.data.length === 0) {
    return (
      <>
        <div className="empty">
          <b>Нет стартов</b>
        </div>
        {/* Отступ — как у списка действий в карточке старта ниже: без него
            рамка списка легла бы вплотную к пунктирной рамке «Нет стартов». */}
        <div className="pick" style={{ marginTop: 12 }}>
          <AddSiteButton onAddSite={onAddSite} />
        </div>
      </>
    )
  }

  return (
    <>
      <div className="pick">
        {sites.data.map((site) => (
          <button
            key={site.name}
            type="button"
            aria-pressed={site.name === selected}
            onClick={() => onPick(site.name)}
          >
            <b>{site.name}</b>
            <s>{siteSubtitle(site)}</s>
            {site.name === selected && <em>✓</em>}
          </button>
        ))}
        {/* Последней строкой того же списка, тем же элементом: разметка
            списка едина, и вход в карту стоит там, где пилот дочитал список
            и своего старта не нашёл. */}
        <AddSiteButton onAddSite={onAddSite} />
      </div>
      {/* Заметки текущего старта (макет, 1646-1649): пилот пишет туда, где
          парковка и куда садиться — показывать их незачем, если пусто. */}
      {notes !== "" && <p className="prose" style={{ marginTop: 12 }}><em>{notes}</em></p>}
    </>
  )
}

type EditorProps = {
  site: Site
  onOpenForecast: (name: string) => void
  onDeleted: () => void
}

export function SiteEditorSheet({ site, onOpenForecast, onDeleted }: EditorProps) {
  // Удаление в два шага (в макете кнопка ничего не делает — прототип
  // статичен): старт из общей библиотеки удаляется у всех пилотов сразу
  // (api.py:delete_site пишет в общий store), а рядом с ним в списке стоят
  // такие же строки других стартов — промах пальцем не должен стоить чужого
  // старта. window.confirm сюда не годится: Telegram показывает
  // мини-приложение в своём webview, где системный диалог выглядит чужим и
  // на части клиентов не появляется вовсе.
  const [confirming, setConfirming] = useState(false)
  const remove = useDeleteSite()

  return (
    <>
      <div className="kv">
        <div><span>Координаты</span><b>{fmtNum(site.lat, 4)}, {fmtNum(site.lon, 4)}</b></div>
        <div><span>Высота по гриду</span><b>{fmtNum(site.elevation_m)} м</b></div>
        <div>
          <span>Экспозиция</span>
          {/* Условие то же, при котором siteSubtitle ставит экспозицию первой
              частью: иначе карточка говорила бы «не размечена» о старте, у
              которого в списке над ней написан румб. */}
          <b>{site.aspect_deg === null && site.aspect === null ? "не размечена" : siteSubtitle(site).split(" · ")[0]}</b>
        </div>
      </div>

      {site.notes !== "" && <p className="prose" style={{ margin: "12px 0" }}><em>{site.notes}</em></p>}

      <div className="pick" style={{ marginTop: 12 }}>
        <button type="button" onClick={() => onOpenForecast(site.name)}>
          <b>Смотреть прогноз</b>
        </button>
        {!confirming && (
          <button type="button" onClick={() => setConfirming(true)}>
            <b style={{ color: colorOfCategory("no_fly") }}>Удалить старт</b>
          </button>
        )}
        {confirming && (
          <button
            type="button"
            disabled={remove.isPending}
            onClick={() => remove.mutate(site.name, { onSuccess: () => onDeleted() })}
          >
            <b style={{ color: colorOfCategory("no_fly") }}>Да, удалить «{site.name}»</b>
            {remove.isPending && <Spinner />}
          </button>
        )}
        {confirming && (
          <button type="button" onClick={() => setConfirming(false)}>
            <b>Оставить</b>
          </button>
        )}
      </div>

      {remove.isError && (
        <ErrorBox error={remove.error} onRetry={() => remove.mutate(site.name, { onSuccess: () => onDeleted() })} />
      )}
    </>
  )
}

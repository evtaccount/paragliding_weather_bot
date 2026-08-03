// Экран «Обзор»: прогноз на несколько дней вперёд (сегменты 3d/week/2weeks,
// GET /api/forecast?range=...) и отдельный режим «Все старты»
// (GET /api/scan) — раскладка `renderOver` (miniapp/prototype.html:943-1014)
// и `renderScan` (miniapp/prototype.html:1015-1066).
//
// Два разных запроса за двумя разными формами ответа (см. комментарий у
// ForecastOverview/OverviewRow в api/types.ts — их легко перепутать):
// диапазонные сегменты идут через useForecast(site, range, ...) и
// ForecastOverview.days_daytime, «Все старты» — через useScan(model) и
// Scan.sites[].days (OverviewRow[]).
//
// `date` диапазонному /api/forecast безразличен: engine.build_url формирует
// URL для range≠"1d" через `forecast_days=RANGE_DAYS[rng]` и не читает date
// вовсе (engine.py:146-154) — диапазон всегда считается "от сегодня", а не
// от даты, выбранной ранее на экране прогноза. Поэтому сюда передаётся `null`
// независимо от того, какой день сейчас выбран в шапке приложения — иначе
// смена дня в «Прогнозе" молча меняла бы ключ кэша этого запроса, ничего не
// меняя в самом ответе сервера.
//
// Причина ограничения в строке дня вытесняет описание погоды — `.day__f`
// (miniapp/prototype.html:252-253) однострочный, с ellipsis, обе фразы не
// влезают, а причина полезнее пилоту: она говорит, что оценивать, а не
// просто "переменная облачность". Когда ограничивать нечего, на её месте
// стоит погода — и это правило одно на ОБА режима экрана (см. overviewDayLine
// и scanRowLine ниже: раньше «Все старты» подставляли туда название
// категории). В лид-панели "Лучший день" погода стоит всегда: у неё
// отдельная, более просторная строка (miniapp/prototype.html:972).
import { useState } from "react"
import type { ForecastRange } from "../api/queries"
import { useForecast, useScan, useSites } from "../api/queries"
import type { ForecastOverview, OverviewRow, Site } from "../api/types"
import { colorOfCategory } from "../charts/palette"
import { RAIN_DAY_MM } from "../domain"
import { compass, fmtDate, fmtNum } from "../format"
import { ErrorBox } from "../ui/ErrorBox"
import { Spinner } from "../ui/Spinner"

// onOpenDay несёт имя старта, а не только дату: в режиме «Все старты»
// строка дня принадлежит КОНКРЕТНОМУ старту группы (Scan.sites[i].name), а
// не тому "текущему" старту, чей прогноз показан на диапазонных сегментах
// (проп site ниже). Без имени старта в колбэке вызывающий код (App.tsx) не
// может понять, чей именно день нажали, и молча подставляет прежний
// текущий старт — это и было причиной Critical-находки ревью (тап по дню
// второго старта в скане открывал прогноз первого).
type OverviewProps = {
  site: string | null
  model: string | null
  // Показан ли экран (вкладка активна) И известна ли действующая модель.
  // Пока false, экран в сеть не ходит вовсе: /api/scan — самый дорогой запрос
  // приложения (forecast.scan_week идёт за погодой по ВСЕЙ библиотеке
  // стартов), а сервер держит один тяжёлый запрос на пилота
  // (api.py:one_at_a_time). Скрытый «Обзор» занимал этот единственный слот
  // раньше того экрана, на который пилот смотрит: один тап по чипу модели на
  // «Маршруте» отправлял три тяжёлых запроса, и собственный запрос пилота
  // уходил третьим (финальное ревью ветки, I3). Размонтировать экран вместо
  // этого нельзя — на том, что все четыре смонтированы всегда, держится
  // отложенная подгонка карты (map/MapView.tsx).
  //
  // Значение по умолчанию — true: экран, отрисованный без оболочки (тесты
  // экрана), показан по определению.
  active?: boolean
  onOpenDay: (site: string, date: string) => void
}

type RangeKey = Exclude<ForecastRange, "1d">

// Подписи и порядок — из миниapp/prototype.html:948, но БЕЗ четвёртой кнопки
// «Все старты»: это не период. Домен подтверждает — GET /api/scan
// (forecast.scan_week) параметра диапазона не имеет вовсе и считает только
// неделю, тогда как три ключа ниже — те самые, что понимает /api/forecast
// (engine.RANGE_DAYS). Пилот выбирал «Все старты» в ряду сроков и получал
// ответ на другой вопрос (просьба владельца, бриф explicit-site-and-day).
const RANGE_TABS: { key: RangeKey; label: string }[] = [
  { key: "3d", label: "3 дня" },
  { key: "week", label: "Неделя" },
  { key: "2weeks", label: "2 недели" },
]

// «Лётно / не лётно» — по assessment.flyable, то есть по criteria.FLYABLE
// (engine.py:assessment_facts). Своего правила у экрана нет намеренно: копия
// («не лётно» только у no_fly и danger) уже разошлась с доменом на категории
// marginal, и старт со всеми маргинальными днями был подписан «лётно» в
// каждой строке «Недели» и лежал в «Без лётных дней» на вкладке «Все старты»
// — один экран противоречил сам себе через один тап (финальное ревью ветки,
// I2).
function flyTag(flyable: boolean): string {
  return flyable ? "лётно" : "не лётно"
}

// Осадки показываются с того же порога, с которого о них говорит чат
// (bot.py:252 — `r["precip"] > engine.RAIN_DAY`); значение — копия
// criteria.RAIN_DAY_MM под сверкой tests/test_webapp_sync.py (см. ../domain).
function precipTail(mm: number): string {
  return mm > RAIN_DAY_MM ? ` · ${fmtNum(mm, 1)} мм` : ""
}

type OverviewDay = ForecastOverview["days_daytime"][number]

// Причина ограничения важнее описания погоды (см. комментарий в шапке файла);
// описание погоды — запасной вариант ровно тогда, когда ограничивать нечего
// (assessment.limiting_factor_ru === null — Assessment.limiting_factor_ru
// того же значения, что и на экране "Прогноз", см. Forecast.tsx).
function overviewDayLine(day: OverviewDay): string {
  const reason = day.assessment.limiting_factor_ru ?? day.weather
  return `до ${fmtNum(day.wind_max_ms, 1)} порыв ${fmtNum(day.gust_max_ms, 1)} · ${day.wind_dir_window} · ${reason}${precipTail(day.precip_mm)}`
}

// Строка дня в «Все старты» собирается ПО ТЕМ ЖЕ правилам, что и строка дня
// диапазонных вкладок выше: тот же запасной текст (описание погоды, когда
// ограничивать нечего) и тот же порог осадков. Раньше правила были разные:
// запасным текстом стояла row.label — название категории («отличная
// лётная»), которое строка и так несёт баллом и его цветом, а осадков не
// было вовсе. Чат на этом же месте печатает погоду и дождь, а категорию
// строкой не пишет (bot.py:250-252), — то есть дождливый день в скане
// приложения был неотличим от ясного (финальное ревью ветки, I6).
//
// Отличие ровно одно и оно от формы ответа: OverviewRow не несёт готовую
// строку направления — в отличие от ForecastOverview.days_daytime[].
// wind_dir_window (уже "Ю (180°)"), здесь только сырые градусы (dom),
// поэтому compass() нужен именно тут.
function scanRowLine(row: OverviewRow): string {
  const reason = row.limiting ?? row.weather
  return `до ${fmtNum(row.wmax, 1)} порыв ${fmtNum(row.gmax, 1)} · ${compass(row.dom)} · ${reason}${precipTail(row.precip)}`
}

// Кнопка дня в форме ForecastOverview.days_daytime — общая для диапазонных
// вкладок и для старта, перезапрошенного вручную из списка «Не удалось
// получить»: ответ там и там один и тот же (GET /api/forecast), и строка дня
// должна читаться одинаково.
//
// `showFlyTag` — подпись «лётно / не лётно» под баллом. Она уместна только на
// диапазонных вкладках: там в списке лежат ВСЕ дни диапазона, и лётность
// каждого — то, что пилот ищет глазами. В группе перезапрошенного старта
// нелётных дней нет по построению (см. отбор в FailedSite ниже), и подпись под
// каждым баллом ничего не сообщала бы — как её нет и у групп скана, где дни
// отобраны тем же правилом.
function OverviewDayButton({ site, day, showFlyTag, onOpenDay }: {
  site: string
  day: OverviewDay
  showFlyTag: boolean
  onOpenDay: (site: string, date: string) => void
}) {
  return (
    <button type="button" className="day" onClick={() => onOpenDay(site, day.date)}>
      <div className="day__d">{fmtDate(day.date)}</div>
      <div className="day__m">
        <div
          className="day__bar"
          style={{ background: colorOfCategory(day.assessment.category), width: `${Math.max(6, day.assessment.score ?? 0)}%` }}
        />
        <div className="day__f">{overviewDayLine(day)}</div>
      </div>
      <div className="day__s" style={{ color: colorOfCategory(day.assessment.category) }}>
        {day.assessment.score ?? "—"}
        {showFlyTag && <small>{flyTag(day.assessment.flyable)}</small>}
      </div>
    </button>
  )
}

function bestOverviewDay(days: OverviewDay[]): OverviewDay {
  return days.reduce((best, day) => (
    (day.assessment.score ?? -Infinity) > (best.assessment.score ?? -Infinity) ? day : best
  ))
}

function NoSites() {
  return (
    <div className="empty">
      <b>Нет стартов</b>
      Добавьте старт, чтобы увидеть обзор.
    </div>
  )
}

// Чего не хватает, чтобы считать диапазонный обзор. Пока выбор не полон,
// экран называет недостающее и в сеть не ходит — та же просьба владельца, по
// которой не считается «Прогноз» (бриф explicit-site-and-day). Спиннер здесь
// не годится: ждать нечего, оба выбора бывают только явными.
function NeedsChoice({ site, range, library }: {
  site: string | null
  range: RangeKey | null
  // Список стартов, если он уже приехал. Пустая библиотека — не «выбор не
  // сделан», а «выбирать не из чего»: до этой правки одна половина «Обзора»
  // предлагала выбрать старт кнопкой в шапке, где выбирать было нечего, а
  // вторая («Все старты») на том же экране честно говорила «Нет стартов»
  // (ревью ветки explicit-site-and-day, M1).
  library: Site[] | undefined
}) {
  if (library !== undefined && library.length === 0) {
    return <NoSites />
  }
  const noSite = site === null
  const noRange = range === null
  return (
    <div className="empty">
      <b>{noSite && noRange ? "Выберите старт и период" : noSite ? "Выберите старт" : "Выберите период"}</b>
      {/* Куда нажимать: старт — общий для всех экранов и живёт в шапке,
          период — только у этого экрана и стоит прямо над списком. */}
      {noSite && noRange ? "Старт выбирается кнопкой в шапке, период — кнопками выше."
        : noSite ? "Старт выбирается кнопкой в шапке."
        : "Период выбирается кнопками выше."}
    </div>
  )
}

function RangeView({ site, range, model, active, onOpenDay }: {
  // Здесь уже не `string | null`: неполный выбор разбирает сам экран
  // (NeedsChoice выше), и до этого места доходит только выбранный старт.
  site: string
  range: RangeKey
  model: string | null
  active: boolean
  onOpenDay: (site: string, date: string) => void
}) {
  const forecast = useForecast(site, range, null, model, active)

  if (forecast.isPending) {
    return <Spinner />
  }
  if (forecast.isError) {
    return <ErrorBox error={forecast.error} onRetry={() => { void forecast.refetch() }} />
  }

  const overview = forecast.data
  const days = overview.days_daytime

  // Сервер по контракту (engine.facts_overview) не отдаёт пустой
  // days_daytime на настоящий диапазон — по факту это не только гипотеза:
  // ревью этой же задачи поймало ровно такой пустой ответ ({days_daytime: []})
  // в одном из тестов App.test.tsx (упрощённая подделка fetch для теста не
  // про «Обзор»), и без этого guard'а bestOverviewDay ниже падал бы —
  // .reduce без начального значения на [] бросает исключение, а не просто
  // отдаёт "нет данных". Дешёвая защита, а падать экрану обзора не из-за
  // чего даже на "невозможном" по контракту вводе.
  if (days.length === 0) {
    return (
      <div className="empty">
        <b>Нет данных</b>
        Сервер не прислал ни одного дня для этого диапазона.
      </div>
    )
  }

  const best = bestOverviewDay(days)

  return (
    <>
      <div className="panel">
        <div className="panel__head">
          <span className="lbl">Лучший день</span>
          <span className="lbl">{overview.site.name} · {days.length} дн.</span>
        </div>
        <div className="verdict">
          <div>
            <div className="verdict__win">{fmtDate(best.date)}</div>
            <div className="verdict__sub">
              {best.weather} · до {fmtNum(best.wind_max_ms, 1)} м/с, порыв {fmtNum(best.gust_max_ms, 1)} · {best.wind_dir_window}
            </div>
          </div>
          <div className="verdict__score">
            <div className="verdict__num" style={{ color: colorOfCategory(best.assessment.category) }}>
              {best.assessment.score ?? "—"}
            </div>
            <div className="verdict__cat">{best.assessment.label_ru}</div>
          </div>
        </div>
      </div>

      <div className="days" role="group" aria-label="Дни диапазона">
        {days.map((day) => (
          <OverviewDayButton key={day.date} site={site} day={day} showFlyTag onOpenDay={onOpenDay} />
        ))}
      </div>
      <div className="attrib">Тап по дню открывает подробный прогноз — экран перерисуется, ничего не добавится в историю</div>
    </>
  )
}

// Одна строка списка «Не удалось получить»: старт, чей недельный запрос упал
// (forecast.py:92-96). Тап повторяет ЕГО запрос — тот самый, который скан и не
// смог сделать: forecast.scan_week берёт недельные данные каждого старта по
// ключу кэша (name, "week", None, model) (forecast.py:86), и по этому же ключу
// ходит GET /api/forecast?site=X&range=week. Другой диапазон грел бы другую
// запись и повтором того запроса не был бы.
//
// Перезапроса всего скана после успеха нет намеренно: данные, которых не
// хватало, уже получены, а /api/scan занял бы единственный тяжёлый слот пилота
// (api.py:one_at_a_time) обходом ВСЕЙ библиотеки ради того же ответа.
//
// Запрос живёт в отдельном компоненте на строку, потому что живёт он в хуке, а
// хук нельзя звать в цикле по списку, длина которого приходит с сервера.
//
// Имя старта берётся из пропа (то есть из Scan.failed), а не из ответа
// (overview.site.name): именем старта приложение его и опознаёт — по нему
// ходят /api/forecast, удаление и ключи кэша (см. invalidateSite в
// api/queries.ts), — и в колбэк дня должно уйти то же имя, которое пилот видел
// в списке.
function FailedSite({ name, model, onOpenDay }: {
  name: string
  model: string | null
  onOpenDay: (site: string, date: string) => void
}) {
  // Пока false, useForecast в сеть не идёт вовсе: повтор — явное действие
  // пилота, а не то, что экран делает за него. Иначе открытая вкладка сама
  // отправляла бы столько тяжёлых запросов, сколько стартов упало, — а упали
  // они, как правило, все разом и по одной причине.
  const [retrying, setRetrying] = useState(false)
  const forecast = useForecast(name, "week", null, model, retrying)

  if (!retrying) {
    return (
      <div className="failed">
        <button type="button" className="retryrow" onClick={() => { setRetrying(true) }}>
          <b>{name}</b>
          <span>Повторить</span>
        </button>
      </div>
    )
  }
  if (forecast.isPending) {
    return (
      <div className="failed">
        <div className="sitegrp__h"><b>{name}</b><span className="lbl">повторяем запрос</span></div>
        <Spinner />
      </div>
    )
  }
  if (forecast.isError) {
    return (
      <div className="failed">
        {/* Имя старта стоит и над отказом: упавших стартов бывает несколько
            (снимок пилота: четыре в одной строке), а рамка отказа сама по себе
            не говорит, чей повтор не прошёл. */}
        <div className="sitegrp__h"><b>{name}</b></div>
        <ErrorBox error={forecast.error} onRetry={() => { void forecast.refetch() }} />
      </div>
    )
  }

  const overview = forecast.data
  // Лётные дни отбираются готовым ответом сервера (assessment.flyable —
  // criteria.flyable, engine.assessment_facts) — той же функцией, которой
  // домен отбирает дни в скане (forecast.py:97). /api/forecast отдаёт ВСЕ дни
  // диапазона, и без этого отбора перезапрошенный старт стоял бы в одном
  // списке с соседями по другому правилу. Своей копии порога у приложения нет
  // намеренно (финальное ревью ветки, I2).
  const fly = overview.days_daytime.filter((day) => day.assessment.flyable)
  if (fly.length === 0) {
    // Тот же вердикт, что домен положил бы в Scan.empty, если бы запрос не
    // упал, — и теми же словами, что блок «Без лётных дней» ниже. Пустая
    // группа на этом месте читалась бы как «повтор не сработал».
    return (
      <div className="failed">
        <div className="empty">
          <b>{name}</b>
          На неделе не нашлось ни одного лётного дня.
        </div>
      </div>
    )
  }

  return (
    <div className="failed">
      <div className="sitegrp__h">
        <b>{name}</b>
        {/* Румб из градусов — как в шапке группы скана: ForecastOverview.site.
            aspect_deg тоже ГРАДУСЫ (engine.facts_overview, engine.py:1151),
            а пилот читает румб. */}
        <span className="lbl">
          {overview.site.aspect_deg === null ? "—" : compass(overview.site.aspect_deg)} · {fly.length} лётных
        </span>
      </div>
      <div className="days" role="group" aria-label={name}>
        {fly.map((day) => (
          <OverviewDayButton key={day.date} site={name} day={day} showFlyTag={false} onOpenDay={onOpenDay} />
        ))}
      </div>
    </div>
  )
}

function ScanView({ model, active, onOpenDay }: {
  model: string | null
  active: boolean
  onOpenDay: (site: string, date: string) => void
}) {
  // Выбранный в шапке старт этому режиму не нужен вовсе: скан ходит по ВСЕЙ
  // библиотеке (forecast.scan_week зовёт store.load_sites) — в этом весь его
  // смысл. А вот пустая библиотека — причина не спрашивать сервер: свежая
  // установка получала на «Все старты» совершенно пустой экран и вдобавок
  // отправляла самый дорогой запрос приложения про пустоту (финальное ревью
  // ветки, Minor 6). Раньше это состояние приезжало пропом site === null;
  // теперь такой проп значит «пилот не выбрал», а это другое, — и список
  // приходится читать самим. Запрос тот же (ключ ["sites"], его уже сделала
  // оболочка), то есть подписка на общий кэш.
  const sites = useSites()
  // Ждём ОТВЕТА про библиотеку, а не гадаем: спросить скан и только потом
  // узнать, что спрашивать было не о чем, — это тот самый лишний тяжёлый
  // запрос, ради которого всё и затевалось (api.py:one_at_a_time держит один
  // такой на пилота). Ждать почти нечего: тот же ключ ["sites"] оболочка
  // запрашивает при запуске, и к нажатию «Все старты» ответ обычно уже в кэше.
  const scan = useScan(model, active && sites.data !== undefined && sites.data.length > 0)

  if (sites.isPending) {
    return <Spinner />
  }
  // Отказ /api/sites разбирается здесь же, а не молчанием: без этой ветки
  // экран остался бы в спиннере навсегда — скан не запускается, пока список
  // неизвестен, и ждать его было бы нечего.
  if (sites.isError) {
    return <ErrorBox error={sites.error} onRetry={() => { void sites.refetch() }} />
  }
  if (sites.data.length === 0) {
    return <NoSites />
  }
  if (scan.isPending) {
    return <Spinner />
  }
  if (scan.isError) {
    return <ErrorBox error={scan.error} onRetry={() => { void scan.refetch() }} />
  }

  const data = scan.data

  return (
    <>
      {/* key={s.name}/aria-label={s.name} по имени старта, не по индексу:
          тот же приём, что и в useDeleteSite(name) (api/queries.ts) — имя
          старта уже принято уникальным идентификатором в остальном
          приложении (это же имя приходит в /api/sites и используется как
          ключ операций над стартом), а не заводится здесь заново. Риск
          низкий и не новый для этого экрана. */}
      {data.sites.map((s) => (
        <div key={s.name} className="sitegrp">
          <div className="sitegrp__h">
            <b>{s.name}</b>
            {/* Scan.sites[].aspect_deg — ГРАДУСЫ (forecast.py:91), а пилот
                читает румб: в чате тот же скан печатает «🪂 Гудаури (Ю)»
                (bot.py:244, engine.card). Печать значения как есть давала
                «180 · 2 лётных» — финальное ревью ветки, C1б. */}
            <span className="lbl">{s.aspect_deg === null ? "—" : compass(s.aspect_deg)} · {s.days.length} лётных</span>
          </div>
          <div className="days" role="group" aria-label={s.name}>
            {s.days.map((row) => (
              <button key={row.date} type="button" className="day" onClick={() => onOpenDay(s.name, row.date)}>
                <div className="day__d">{fmtDate(row.date)}</div>
                <div className="day__m">
                  <div className="day__bar" style={{ background: colorOfCategory(row.category), width: `${Math.max(6, row.score)}%` }} />
                  <div className="day__f">{scanRowLine(row)}</div>
                </div>
                <div className="day__s" style={{ color: colorOfCategory(row.category) }}>{row.score}</div>
              </button>
            ))}
          </div>
        </div>
      ))}

      {/* Порог лётности словами здесь не пересказывается («ни одного окна ≥
          удовлетворительного» было третьей копией criteria.FLYABLE, после
          isNotFly и прозы: финальное ревью ветки, I2). Состав списка задаёт
          сам домен — forecast.scan_week кладёт сюда старт, у которого
          criteria.flyable не пропустил ни одного дня, — и «лётный день» это
          его собственное слово, а не пересказ порога. */}
      {data.empty.length > 0 && (
        <div className="empty">
          <b>Без лётных дней</b>
          {data.empty.join(", ")} — на неделе не нашлось ни одного лётного дня.
        </div>
      )}
      {/* Раньше здесь стояло перечисление через запятую и совет «открой старт
          вручную, чтобы повторить запрос»: экран называл отказ и тут же
          отправлял пилота решать его на другом экране, столько раз, сколько
          стартов упало. Теперь у каждого своя строка, и повтор происходит
          здесь же (см. FailedSite). */}
      {data.failed.length > 0 && (
        <div className="sitegrp">
          <div className="sitegrp__h">
            <b>Не удалось получить</b>
            <span className="lbl">тап повторит запрос</span>
          </div>
          {data.failed.map((name) => (
            <FailedSite key={name} name={name} model={model} onOpenDay={onOpenDay} />
          ))}
        </div>
      )}
    </>
  )
}

export function Overview({ site, model, active = true, onOpenDay }: OverviewProps) {
  // Ни период, ни режим не предвыбраны: экран открывается, ничего не считая,
  // и ждёт, пока пилот скажет, что смотреть (бриф explicit-site-and-day).
  const [range, setRange] = useState<RangeKey | null>(null)
  const [allSites, setAllSites] = useState(false)
  // Подписка на тот же ключ ["sites"], что уже запросила оболочка: второго
  // запроса не будет, а пустую библиотеку надо отличать от несделанного
  // выбора (см. NeedsChoice).
  const sites = useSites()

  return (
    <>
      {/* «Все старты» — отдельный переключатель, а не четвёртый период:
          вопрос «по всем стартам или по одному» и вопрос «за какой срок» —
          разные, и у скана срок ровно один (см. RANGE_TABS выше). */}
      <div className="seg" role="group" aria-label="Что смотрим">
        <button type="button" aria-pressed={allSites} onClick={() => setAllSites((on) => !on)}>
          Все старты
        </button>
      </div>

      {allSites
        // Селектор периодов не просто гаснет, а объясняет, почему его нет:
        // GET /api/scan диапазона не принимает вовсе (forecast.scan_week
        // считает неделю), и выбирать пилоту тут нечего.
        ? <div className="attrib">по всем стартам — на неделю вперёд</div>
        : (
          <div className="seg" role="group" aria-label="Диапазон обзора">
            {RANGE_TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                aria-pressed={range === t.key}
                onClick={() => setRange(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}

      {allSites
        ? <ScanView model={model} active={active} onOpenDay={onOpenDay} />
        : site === null || range === null
          ? <NeedsChoice site={site} range={range} library={sites.data} />
          : <RangeView site={site} range={range} model={model} active={active} onOpenDay={onOpenDay} />}
    </>
  )
}

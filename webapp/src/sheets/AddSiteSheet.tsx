// Шторка «Добавить старт» — поля из макета (buildAddSite,
// miniapp/prototype.html:1837-1861: координаты, название, экспозиция,
// заметки; высоту приложение берёт само). В макете это только описание
// полей — форм прототип не содержит вовсе, поэтому разметка полей здесь
// новая, а вот порядок и подписи полей — его.
//
// Высота НЕ спрашивается у пилота: api.py:SiteIn.elevation_m обязателен, и
// «на глаз» он врал бы во всех расчётах разом (высота старта входит и в
// потолок термички, и в рабочий коридор маршрута). Её отдаёт сервер —
// POST /api/elevation (forecast.fetch_elevation по гриду Copernicus DEM).
// Запрашивается она в двух местах: сразу при тапе по карте (пилот видит
// высоту точки, по которой ткнул) и на отправке формы, если координаты
// набраны руками и высота для них ещё не известна.
//
// Пределы домена здесь не продублированы: длину имени и символ «|» проверяет
// store.name_error, диапазоны широты и долготы — store.coords_error, занятое
// имя — api.create_site (409). Каждый отказ приходит готовым текстом для
// пилота, и показывается именно он. Своя проверка одна и не про пределы:
// координаты должны быть числами — иначе запрос уходит с null в теле, и
// сервер отвечает 400 с ИМЕНЕМ ПОЛЯ («проверьте поля: lat»,
// api.py:_validation_error), а не тем, что пилоту нужно сделать.
import { useState } from "react"
import { useCreateSite, useElevation, useSites } from "../api/queries"
import type { ApiError } from "../api/client"
import type { LatLon } from "../map/MapView"
import type { Site } from "../api/types"
import { compass, fmtNum } from "../format"
import { MapView } from "../map/MapView"
import { ErrorBox } from "../ui/ErrorBox"
import { Spinner } from "../ui/Spinner"

type Props = {
  // Имя заведённого старта — тому, кто открыл шторку: из выбиралки старт
  // сразу становится выбранным (App.tsx: pickNewSite), экрану настроек имя
  // не нужно, и лишний аргумент ему не мешает.
  onCreated: (name: string) => void
}

// Пустой список стартов — константа модуля: MapView пересобирает маркеры при
// смене ССЫЛКИ на массив (см. комментарий в screens/Route.tsx).
const NO_SITES: Site[] = []

// Восемь румбов и их градусы — та же таблица, что engine._COMPASS (её же
// разбирает /add в чате: engine.parse_aspect → engine.card). Подписи не
// перечисляются: их даёт format.compass() по тем же градусам, поэтому
// разъехаться с CARD16 им негде.
const ASPECT_DEGREES = [0, 45, 90, 135, 180, 225, 270, 315]

// Координата: и «42.51», и «42,51» — запятая приходит с русской раскладки
// телефона, и терять на ней ввод пилота незачем. Возвращает null, если из
// строки не получается конечное число (пусто, буквы, два разделителя).
function parseCoord(text: string): number | null {
  const value = Number(text.trim().replace(",", "."))
  return text.trim() !== "" && Number.isFinite(value) ? value : null
}

export function AddSiteSheet({ onCreated }: Props) {
  // Уже заведённые старты — справочными пинами на карте: новый старт почти
  // всегда ставят рядом с известным. Читаются здесь, а не приходят пропом:
  // шторка кладётся в стек готовым элементом, и список, пришедший после её
  // открытия, в застывший проп уже не попал бы (ревью задачи 13, N2).
  const sites = useSites()
  const [name, setName] = useState("")
  const [latText, setLatText] = useState("")
  const [lonText, setLonText] = useState("")
  const [aspectDeg, setAspectDeg] = useState<number | null>(null)
  const [notes, setNotes] = useState("")
  // Высота вместе с координатами, для которых она получена: пилот может
  // подвинуть точку после запроса, и тогда прежняя высота уже не про эту
  // точку.
  const [elevation, setElevation] = useState<{ lat: number; lon: number; m: number } | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [coordsBad, setCoordsBad] = useState(false)
  const [nameMissing, setNameMissing] = useState(false)

  const elevationQuery = useElevation()
  const create = useCreateSite()

  const lat = parseCoord(latText)
  const lon = parseCoord(lonText)
  // Высота «про эту точку» или null: координаты могли смениться после
  // запроса, и тогда прежнее число относится уже к другому месту.
  const knownElevation =
    elevation !== null && lat === elevation.lat && lon === elevation.lon ? elevation.m : null
  const mapPoints = lat !== null && lon !== null ? [{ lat, lon, title: name === "" ? "Новый старт" : name }] : []

  function pickOnMap(p: LatLon): void {
    // Пять знаков после точки — около метра на местности: точнее тапом по
    // карте всё равно не попасть, а полная двоичная дробь («42.476142857…»)
    // в поле ввода нечитаема. Округление ДО запроса высоты, а не после:
    // иначе высота относилась бы к неокруглённой точке и при отправке формы
    // ушёл бы второй запрос за тем же самым.
    const point = { lat: Number(p.lat.toFixed(5)), lon: Number(p.lon.toFixed(5)) }
    setLatText(String(point.lat))
    setLonText(String(point.lon))
    setCoordsBad(false)
    elevationQuery.mutate(point, { onSuccess: (data) => setElevation({ ...point, m: data.elevation_m }) })
  }

  async function submit(): Promise<void> {
    // Две проверки до отправки, и обе НЕ про пределы домена. Пустое имя:
    // отправка стоила бы ТЯЖЁЛОГО запроса высоты (api.py:elevation висит на
    // one_at_a_time и ходит в сеть) ради заранее известного отказа
    // store.name_error. Нечисловые координаты: в теле оказался бы null, и
    // сервер ответил бы 400 с именем поля (api.py:_validation_error) вместо
    // «координаты должны быть числами». Длину имени, символ «|»
    // и диапазоны широты/долготы проверяет сервер — их здесь нет.
    if (name.trim() === "") {
      setNameMissing(true)
      return
    }
    setNameMissing(false)
    if (lat === null || lon === null) {
      setCoordsBad(true)
      return
    }
    setCoordsBad(false)
    setError(null)
    try {
      const elevationM = knownElevation ?? (await elevationQuery.mutateAsync({ lat, lon })).elevation_m
      setElevation({ lat, lon, m: elevationM })
      const site = await create.mutateAsync({
        // Имя без краевых пробелов: api.create_site, в отличие от
        // api.save_route, его не подрезает — старт «Гудаури » стал бы
        // отдельным от «Гудаури» и не совпал бы с именем в кнопках чата.
        name: name.trim(),
        lat,
        lon,
        elevation_m: elevationM,
        // Экспозиция необязательна: старт без неё домен считает
        // «неразмеченным» (engine.slope_sun_index возвращает None), а не
        // северным — поэтому пустой выбор едет как null, а не как 0°.
        aspect: aspectDeg === null ? null : compass(aspectDeg),
        aspect_deg: aspectDeg,
        notes,
      })
      // Имя — из ОТВЕТА сервера (api.py:create_site отдаёт _public_site), а
      // не из поля формы: под каким именем старт лёг в библиотеку, знает
      // только store — он общий с чатом, и завязываться здесь на совпадение
      // незачем, когда ответ уже в руках.
      onCreated(site.name)
    } catch (e) {
      setError(e as ApiError)
    }
  }

  const busy = elevationQuery.isPending || create.isPending

  return (
    <>
      <p className="prose">
        Экспозиция — куда смотрит склон. Она нужна, чтобы понимать, дует ли ветер в лоб или в
        спину, и когда солнце встаёт на склон.
      </p>

      <div className="map" style={{ marginTop: 12 }}>
        <MapView
          points={mapPoints}
          sites={sites.data ?? NO_SITES}
          onTap={pickOnMap}
          onDragPoint={(_i, p) => pickOnMap(p)}
        />
      </div>
      <div className="attrib">Тап по карте ставит точку старта и сразу спрашивает её высоту</div>

      <label className="field">
        <span>Название — как называть в списке</span>
        <input type="text" value={name} onChange={(e) => { setName(e.target.value); setNameMissing(false) }} />
      </label>
      {nameMissing && <div className="attrib" role="alert">Введите название — без него старт не завести.</div>}

      <label className="field">
        <span>Широта</span>
        <input inputMode="decimal" value={latText} onChange={(e) => { setLatText(e.target.value); setCoordsBad(false) }} />
      </label>
      <label className="field">
        <span>Долгота</span>
        <input inputMode="decimal" value={lonText} onChange={(e) => { setLonText(e.target.value); setCoordsBad(false) }} />
      </label>
      {coordsBad && (
        <div className="attrib" role="alert">Широта и долгота — числами, например 42.47 и 44.48.</div>
      )}

      <label className="field">
        <span>Экспозиция — куда смотрит склон</span>
        <select
          value={aspectDeg === null ? "" : String(aspectDeg)}
          onChange={(e) => setAspectDeg(e.target.value === "" ? null : Number(e.target.value))}
        >
          <option value="">не знаю</option>
          {ASPECT_DEGREES.map((deg) => (
            <option key={deg} value={String(deg)}>{compass(deg)} {deg}°</option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>Заметки — необязательно</span>
        <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>

      <div className="kv" style={{ marginTop: 12 }}>
        <div>
          <span>Высота по гриду</span>
          <b>{knownElevation === null ? "спросим при добавлении" : `${fmtNum(knownElevation)} м`}</b>
        </div>
      </div>

      <button type="button" className="btn btn--primary" disabled={busy} onClick={() => { void submit() }}>
        Добавить старт
      </button>
      {busy && <Spinner />}
      {error !== null && <ErrorBox error={error} onRetry={() => { void submit() }} />}
    </>
  )
}

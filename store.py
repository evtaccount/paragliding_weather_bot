"""SQLite-хранилище бота.

Единственный модуль, который знает про user_id и SQL. Ни от одного модуля
проекта не зависит: на нём стоят и engine, и forecast, и bot, и любая
зависимость обратно замкнула бы цикл.

Что общее, а что личное:
  общее — старты (библиотека команды), рельеф, точки по координатам;
  личное — маршруты, маршрутные настройки, выбор метеомодели.
"""
import dataclasses
import datetime as dt
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH") or os.path.join(HERE, "data", "pgbot.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
  name        TEXT PRIMARY KEY,
  lat         REAL NOT NULL,
  lon         REAL NOT NULL,
  elevation_m INTEGER NOT NULL,
  aspect      TEXT,
  aspect_deg  REAL,
  slope_deg   REAL,
  route_top_m INTEGER,
  notes       TEXT,
  added_by    INTEGER,
  added_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS site_aliases (
  alias TEXT PRIMARY KEY,
  name  TEXT NOT NULL REFERENCES sites(name) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_prefs (
  user_id                 INTEGER PRIMARY KEY,
  avg_route_speed_kmh     REAL    NOT NULL DEFAULT 25.0,
  wind_correction_enabled INTEGER NOT NULL DEFAULT 1,
  model_key               TEXT    NOT NULL DEFAULT 'auto'
);

CREATE TABLE IF NOT EXISTS routes (
  user_id  INTEGER NOT NULL,
  name     TEXT    NOT NULL,
  points   TEXT    NOT NULL,
  saved_at TEXT    NOT NULL,
  PRIMARY KEY (user_id, name)
);

CREATE TABLE IF NOT EXISTS terrain (
  grid_key   TEXT PRIMARY KEY,
  elevations TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS adhoc_points (
  name        TEXT PRIMARY KEY,
  lat         REAL NOT NULL,
  lon         REAL NOT NULL,
  elevation_m INTEGER NOT NULL,
  created_at  TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    """Соединение на операцию. WAL — потому что в одном процессе живут два
    писателя: хендлеры бота и (позже) HTTP-эндпоинты."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init() -> None:
    """Создать каталог и таблицы. Идемпотентна — зовётся на каждом старте."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ старты
# Общая библиотека: старт — это факт о местности, а не личное предпочтение.
# Имя остаётся идентичностью: на нём построены ключи кэша прогноза и
# callback_data кнопок.

_SITE_COLUMNS = ("name", "lat", "lon", "elevation_m", "aspect", "aspect_deg",
                 "slope_deg", "route_top_m", "notes", "added_by")


def _site_row_to_dict(row: sqlite3.Row, aliases: list[str]) -> dict:
    out = {k: row[k] for k in _SITE_COLUMNS}
    out["aliases"] = aliases
    return out


def load_sites() -> list[dict]:
    """Все старты, по алфавиту. Форма словаря та же, что отдавал engine.load_sites()."""
    with connect() as conn:
        rows = conn.execute("SELECT * FROM sites ORDER BY name").fetchall()
        by_site: dict[str, list[str]] = {}
        for a in conn.execute("SELECT alias, name FROM site_aliases"):
            by_site.setdefault(a["name"], []).append(a["alias"])
    return [_site_row_to_dict(r, sorted(by_site.get(r["name"], []))) for r in rows]


def find_site(name: str) -> dict | None:
    """Старт по имени или псевдониму, без учёта регистра. None, если не найден."""
    key = name.strip().lower()
    with connect() as conn:
        # Сначала ищем по имени (с учётом регистра через Python, т.к. SQLite's lower() не работает с кириллицей)
        all_sites = conn.execute("SELECT * FROM sites").fetchall()
        row = None
        for site_row in all_sites:
            if site_row["name"].lower() == key:
                row = site_row
                break

        if row is None:
            # Ищем по псевдониму
            all_aliases = conn.execute("SELECT alias, name FROM site_aliases").fetchall()
            site_name = None
            for alias_row in all_aliases:
                if alias_row["alias"].lower() == key:
                    site_name = alias_row["name"]
                    break
            if site_name is None:
                return None
            row = conn.execute(
                "SELECT * FROM sites WHERE name = ?", (site_name,)).fetchone()
            if row is None:
                return None

        aliases = [a["alias"] for a in conn.execute(
            "SELECT alias FROM site_aliases WHERE name = ?", (row["name"],))]
    return _site_row_to_dict(row, sorted(aliases))


# Имя уезжает в callback_data бота: "deep|" + name + "|2weeks|YYYY-MM-DD"
# должно уместиться в 64 байта, а поля режутся по «|». Ограничения чата, но
# проверять их обязаны обе поверхности — библиотека стартов общая, и старт,
# заведённый из приложения, ломал бы кнопки бота.
NAME_MAX_BYTES = 40


def name_error(name: str) -> str | None:
    """Почему имя не годится для callback_data, или None если годится.

    Одна функция на оба адаптера. Разнесённые проверки разъехались бы при
    первой правке, и приложение завело бы старт, невидимый для кнопок чата.

    Пустое (или из одних пробелов) имя даёт кнопку с пустым текстом, а её
    Telegram отклоняет целиком — как и слишком длинное имя, это касается
    ОБОИХ адаптеров, поэтому проверка здесь, а не в вызывающем коде: у чата
    оба места вызова уже отсекают пустой ввод раньше (и не пострадают), а
    api.create_site для стартов такой проверки не имело вовсе — пустое имя
    проходило в общую библиотеку стартов.
    """
    if not name.strip():
        return "Имя не может быть пустым."
    if "|" in name:
        return "Имя не должно содержать символ «|»."
    if len(name.encode("utf-8")) > NAME_MAX_BYTES:
        return "Слишком длинное имя — не влезет в кнопки Telegram. До ~20 символов, короче?"
    return None


def coords_error(lat: float, lon: float) -> str | None:
    """Почему координаты не годятся, или None если годятся.

    Одна функция на оба адаптера — то же обоснование, что у name_error:
    библиотека стартов общая, и координаты вне диапазона, заведённые с одной
    поверхности, торчали бы в /sites у каждого пилота и в failed у
    scan_week навсегда.
    """
    if not (-90 <= lat <= 90):
        return f"широта должна быть от -90 до 90, получено {lat}"
    if not (-180 <= lon <= 180):
        return f"долгота должна быть от -180 до 180, получено {lon}"
    return None


# Потолки остальных полей старта. Числа взяты с запасом от того, что бывает
# на Земле и в интерфейсе: заметка — абзац под карточкой старта
# (webapp/src/sheets/SitePickerSheet.tsx), псевдонимов у старта единицы
# (sites.json: один-два), высоты — от Мёртвого моря до Эвереста.
NOTES_MAX_CHARS = 500
MAX_ALIASES = 10
MIN_ELEVATION_M = -500
MAX_ELEVATION_M = 9000
# Румб пишется меткой из 1–3 букв (engine.card по 16-румбовой таблице; то же
# в webapp/src/format.ts). Ограничение здесь по РАЗМЕРУ, а не по словарю:
# третья копия таблицы румбов разъехалась бы с теми двумя.
ASPECT_LABEL_MAX_CHARS = 8


def details_error(site: dict) -> str | None:
    """Почему остальные поля старта не годятся, или None если годятся.

    Третья функция того же ряда, что name_error и coords_error, и по той же
    причине: библиотека стартов ОБЩАЯ и целиком уезжает КАЖДОМУ пилоту при
    КАЖДОМ открытии приложения (api.list_sites → GET /api/sites).

    Из чата эти поля недостижимы вовсе: bot.cmd_add (bot.py:566-588) собирает
    старт из имени, координат и экспозиции, а notes и aliases не задаёт, и
    всё, что он принимает, ограничено длиной сообщения Telegram. Через HTTP
    их не смотрел никто: один запрос с notes на 5 000 000 символов и 20 000
    псевдонимов проходил с 201, после чего GET /api/sites весил 10 269 330
    байт вместо 293 (финальное ревью ветки, безопасность, I3) — и эти десять
    мегабайт качал бы каждый пилот с мобильного интернета в горах, ради чего
    приложение и делалось.

    Псевдоним проверяется тем же name_error: find_site ищет по имени И по
    псевдониму, то есть псевдоним — это второе имя старта, и ограничения у
    него ровно те же.

    Сравнения диапазонов заодно отсекают NaN и Infinity: любое сравнение с
    NaN ложно, а bool(inf <= 9000) — False. Отдельной проверки на них не
    нужно, как и в coords_error.
    """
    notes = site.get("notes") or ""
    if len(notes) > NOTES_MAX_CHARS:
        return (f"Заметка длиннее {NOTES_MAX_CHARS} символов ({len(notes)}) — "
                "её видит каждый пилот, сократи.")

    aliases = site.get("aliases") or []
    if len(aliases) > MAX_ALIASES:
        return f"Слишком много псевдонимов: {len(aliases)}, потолок {MAX_ALIASES}."
    for alias in aliases:
        bad = name_error(alias) if isinstance(alias, str) else "Псевдоним должен быть строкой."
        if bad:
            return f"Псевдоним «{alias}»: {bad}"

    aspect = site.get("aspect")
    if isinstance(aspect, str) and len(aspect) > ASPECT_LABEL_MAX_CHARS:
        return (f"Экспозиция пишется румбом (Ю, ЮЗ, ЮЮЗ), а не текстом длиннее "
                f"{ASPECT_LABEL_MAX_CHARS} символов.")

    for field, low, high in (("elevation_m", MIN_ELEVATION_M, MAX_ELEVATION_M),
                             ("route_top_m", MIN_ELEVATION_M, MAX_ELEVATION_M),
                             ("aspect_deg", 0, 360),
                             ("slope_deg", 0, 90)):
        value = site.get(field)
        if value is None:
            continue
        if not low <= value <= high:
            return f"{field}: допустимо от {low} до {high}, получено {value}"
    return None


def add_site(site: dict, added_by: int | None = None) -> None:
    """Добавить старт. ValueError, если имя занято именем ИЛИ псевдонимом другого:
    find_site матчит и то и другое, и затенённый старт стал бы недостижим."""
    key = site["name"].strip().lower()
    with connect() as conn:
        # Проверка по имени (с учётом регистра через Python, т.к. SQLite's lower() не работает с кириллицей)
        all_sites = conn.execute("SELECT name FROM sites").fetchall()
        for site_row in all_sites:
            if site_row["name"].lower() == key:
                raise ValueError(f"старт «{site['name']}» уже есть")

        # Проверка по псевдониму
        all_aliases = conn.execute("SELECT alias, name FROM site_aliases").fetchall()
        for alias_row in all_aliases:
            if alias_row["alias"].lower() == key:
                raise ValueError(f"имя «{site['name']}» уже занято как псевдоним "
                                 f"старта «{alias_row['name']}»")

        conn.execute(
            "INSERT INTO sites (name, lat, lon, elevation_m, aspect, aspect_deg,"
            " slope_deg, route_top_m, notes, added_by, added_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (site["name"], site["lat"], site["lon"], site["elevation_m"],
             site.get("aspect"), site.get("aspect_deg"), site.get("slope_deg"),
             site.get("route_top_m"), site.get("notes"), added_by, _now()))
        for alias in site.get("aliases") or []:
            a = alias.strip().lower()
            if a and a != key:
                conn.execute("INSERT OR IGNORE INTO site_aliases (alias, name)"
                             " VALUES (?, ?)", (a, site["name"]))


def remove_site(name: str) -> None:
    """Удалить старт по имени. ValueError, если не найден. Псевдонимы уходят каскадом."""
    key = name.strip().lower()
    with connect() as conn:
        # Поиск по имени (с учётом регистра через Python, т.к. SQLite's lower() не работает с кириллицей)
        all_sites = conn.execute("SELECT name FROM sites").fetchall()
        actual_name = None
        for site_row in all_sites:
            if site_row["name"].lower() == key:
                actual_name = site_row["name"]
                break

        if actual_name is None:
            raise ValueError(f"старт «{name}» не найден")
        conn.execute("DELETE FROM sites WHERE name = ?", (actual_name,))


# ------------------------------------------------------------ личные настройки
# 25 км/ч — разумный дефолт для уверенного XC-пилота на B+. Реальный разброс:
# 18–22 в слабый день, 25–30 в рабочий, 30–35 у сильных пилотов на коротком маршруте.
SPEED_MIN, SPEED_MAX = 10.0, 45.0


@dataclasses.dataclass(frozen=True)
class Prefs:
    """Личные настройки пользователя.

    Не словарь: обращения к нему расходятся по обоим адаптерам (бот и HTTP),
    и опечатка в имени поля должна падать сразу, а не отдавать None.
    Имена полей совпадают с ключами старого settings.DEFAULTS.
    """
    avg_route_speed_kmh: float = 25.0
    wind_correction_enabled: bool = True
    model_key: str = "auto"


DEFAULT_PREFS = Prefs()


def prefs(user_id: int) -> Prefs:
    """Настройки пользователя; дефолты, если он ещё ничего не менял.

    Строку не создаёт: новый пилот не должен ничего регистрировать, чтобы
    посмотреть прогноз.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT avg_route_speed_kmh, wind_correction_enabled, model_key"
            " FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return DEFAULT_PREFS
    return Prefs(avg_route_speed_kmh=row["avg_route_speed_kmh"],
                 wind_correction_enabled=bool(row["wind_correction_enabled"]),
                 model_key=row["model_key"])


def _set_pref(user_id: int, column: str, value) -> None:
    """UPSERT одного поля. Имя колонки подставляется из литералов вызывающих
    функций — снаружи оно не приходит."""
    with connect() as conn:
        conn.execute(
            f"INSERT INTO user_prefs (user_id, {column}) VALUES (?, ?)"
            f" ON CONFLICT(user_id) DO UPDATE SET {column} = excluded.{column}",
            (user_id, value))


def set_speed(user_id: int, value: float) -> None:
    """Средняя маршрутная скорость в км/ч. ValueError вне допустимого диапазона."""
    value = float(value)
    if not SPEED_MIN <= value <= SPEED_MAX:
        raise ValueError(
            f"средняя маршрутная скорость должна быть от {SPEED_MIN:.0f} "
            f"до {SPEED_MAX:.0f} км/ч. Это средняя по маршруту с учётом наборов "
            "в термиках, а не скорость крыла.")
    _set_pref(user_id, "avg_route_speed_kmh", value)


def set_wind_correction(user_id: int, on: bool) -> None:
    _set_pref(user_id, "wind_correction_enabled", 1 if on else 0)


def set_model(user_id: int, key: str) -> None:
    """Постоянная модель пользователя. Ключ валидирует вызывающий (engine.MODELS):
    список моделей — знание домена, а не хранилища."""
    _set_pref(user_id, "model_key", key)


# ------------------------------------------------------------ личные маршруты
# Хранится ТОЛЬКО геометрия. Погода всегда считается заново, поэтому устаревать
# здесь нечему: сохранённый маршрут — это набор координат, а не прогноз.
# Точки лежат JSON-строкой намеренно: запросов по отдельной точке нет,
# отдельная таблица была бы схемой ради схемы.
MAX_ROUTES = 20


def routes_list(user_id: int) -> dict[str, dict]:
    """Все маршруты пользователя. Битые записи пропускаются, а не роняют выдачу."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT name, points, saved_at FROM routes WHERE user_id = ? ORDER BY name",
            (user_id,)).fetchall()
    out = {}
    for r in rows:
        try:
            pts = json.loads(r["points"])
        except ValueError:
            continue
        if isinstance(pts, list):
            out[r["name"]] = {"points": pts, "saved": r["saved_at"]}
    return out


def route_exists(user_id: int, name: str) -> bool:
    """Занято ли имя маршрута. Отдельно от routes_list() намеренно.

    routes_list() пропускает битые записи, а «имя занято» — факт о строке в
    таблице, а не о том, читается ли её JSON. Иначе перезапись маршрута с
    порченым points отчиталась бы «Сохранил» вместо «Перезаписал».
    """
    with connect() as conn:
        return conn.execute(
            "SELECT 1 FROM routes WHERE user_id = ? AND name = ?",
            (user_id, name)).fetchone() is not None


def route_rows(user_id: int, name: str) -> list | None:
    """Сырые строки точек: [[lat, lon, name], ...]. None, если нет или битая."""
    with connect() as conn:
        row = conn.execute(
            "SELECT points FROM routes WHERE user_id = ? AND name = ?",
            (user_id, name)).fetchone()
    if row is None:
        return None
    try:
        pts = json.loads(row["points"])
    except ValueError:
        return None
    return pts if isinstance(pts, list) else None


def route_save(user_id: int, name: str, rows: list) -> None:
    """Сохранить точки под именем. ValueError при переполнении.

    Перезапись существующего имени переполнением не считается — иначе на
    заполненном списке нельзя было бы поправить уже сохранённый маршрут.
    """
    with connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM routes WHERE user_id = ? AND name = ?",
            (user_id, name)).fetchone()
        if not exists:
            n = conn.execute("SELECT count(*) c FROM routes WHERE user_id = ?",
                             (user_id,)).fetchone()["c"]
            if n >= MAX_ROUTES:
                raise ValueError(f"сохранено уже {MAX_ROUTES} маршрутов — "
                                 "удали ненужный через /delroute")
        conn.execute(
            "INSERT INTO routes (user_id, name, points, saved_at) VALUES (?,?,?,?)"
            " ON CONFLICT(user_id, name) DO UPDATE SET"
            " points = excluded.points, saved_at = excluded.saved_at",
            (user_id, name, json.dumps(rows, ensure_ascii=False), _now()))


def route_delete(user_id: int, name: str) -> bool:
    """True, если удалили; False, если такого маршрута не было."""
    with connect() as conn:
        cur = conn.execute("DELETE FROM routes WHERE user_id = ? AND name = ?",
                           (user_id, name))
        return cur.rowcount > 0


# ------------------------------------------------- рельеф и точки по координатам
# Рельеф не меняется никогда, но стоит отдельного запроса к Elevation API.
# До переезда в БД он жил в словаре процесса и терялся при каждом рестарте.


def terrain_get(grid_key: str) -> list | None:
    with connect() as conn:
        row = conn.execute("SELECT elevations FROM terrain WHERE grid_key = ?",
                           (grid_key,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["elevations"])
    except ValueError:
        return None


def terrain_put(grid_key: str, elevations: list) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO terrain (grid_key, elevations, fetched_at) VALUES (?,?,?)"
            " ON CONFLICT(grid_key) DO UPDATE SET"
            " elevations = excluded.elevations, fetched_at = excluded.fetched_at",
            (grid_key, json.dumps(elevations), _now()))


def adhoc_name(lat: float, lon: float) -> str:
    """Имя точки по координатам. Оно же ключ: координаты уникальны глобально,
    поэтому таблица общая, а не по пользователям."""
    return f"{lat:.4f}, {lon:.4f}"


def adhoc_put(lat: float, lon: float, elevation_m: int) -> str:
    name = adhoc_name(lat, lon)
    with connect() as conn:
        conn.execute(
            "INSERT INTO adhoc_points (name, lat, lon, elevation_m, created_at)"
            " VALUES (?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET"
            " elevation_m = excluded.elevation_m, created_at = excluded.created_at",
            (name, lat, lon, elevation_m, _now()))
    return name


def adhoc_get(name: str) -> dict | None:
    """Точка в форме словаря старта. Экспозиция неизвестна, поэтому вердикт по
    направлению ветра для неё пропускается — так же, как было в памяти."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM adhoc_points WHERE name = ?",
                           (name,)).fetchone()
    if row is None:
        return None
    return {"name": row["name"], "aliases": [], "lat": row["lat"], "lon": row["lon"],
            "elevation_m": row["elevation_m"], "aspect": None, "aspect_deg": None,
            "slope_deg": None, "route_top_m": None, "notes": "", "added_by": None}


def purge_adhoc(older_than_days: int = 30) -> int:
    """Убрать старые точки по координатам. Возвращает число удалённых."""
    cutoff = (dt.datetime.now(dt.timezone.utc)
              - dt.timedelta(days=older_than_days)).isoformat(timespec="seconds")
    with connect() as conn:
        cur = conn.execute("DELETE FROM adhoc_points WHERE created_at < ?", (cutoff,))
        return cur.rowcount


# ------------------------------------------------------------------ миграция
# Разовый перенос с JSON-файлов. Файлы не удаляются, а переименовываются в
# *.migrated: откат — вернуть имена и откатить образ.

def _read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _mark_migrated(path: str) -> None:
    os.replace(path, path + ".migrated")


def _legacy_path(dirs, filename: str, skip_paths) -> str | None:
    """Первый существующий старый файл среди каталогов, или None.

    Каталогов два, и порядок важен. Под Docker личные файлы лежали в
    примонтированном томе — там же, где теперь БД, поэтому каталог БД первый.
    На systemd-пути бот запускается из корня репозитория, а старые дефолты
    SITES_FILE / ROUTES_FILE / SETTINGS_FILE / MODEL_FILE клали файлы рядом с
    кодом — без второго каталога личные маршруты и настройки такой установки
    не нашлись бы никогда.

    `skip_paths` — что переносить нельзя. Упакованный засев стартов лежит в
    корне репозитория под именем sites.json: переименуй его в *.migrated — и
    после первой же пересборки образа удалённые старты вернутся.
    """
    skip = {os.path.realpath(p) for p in skip_paths}
    for d in dirs:
        p = os.path.join(d, filename)
        if os.path.exists(p) and os.path.realpath(p) not in skip:
            return p
    return None


def _add_site_counted(site, index: int, source: str, report: dict) -> None:
    """Добавить старт из JSON; причину неудачи записать в report["dropped"].

    Ни одна порченая запись не роняет перенос целиком — файл после него
    переименовывается в *.migrated, и упавший старт исчез бы молча.
    sqlite3.Error здесь такая же построчная беда, как ValueError: старт с
    "lat": null даёт NOT NULL constraint failed, и раньше он вылетал наружу
    из bootstrap и ронял старт бота одинаково на каждом рестарте.
    """
    if not isinstance(site, dict):
        report["dropped"].append(f"{source}: запись #{index} не словарь ({site!r})")
        return
    name = site.get("name")
    label = name if isinstance(name, str) else f"запись #{index}"
    try:
        add_site(site)
        report["sites"] += 1
    except (ValueError, TypeError, KeyError, sqlite3.Error) as e:
        report["dropped"].append(f"{source}: «{label}» — {e}")


def _take_speed(value, source: str, defaults: dict, report: dict) -> None:
    """Средняя скорость из settings.json — только если это число в диапазоне.

    Миграция — единственный путь записи, перед которым нет валидации set_speed():
    строка вместо числа доезжала до колонки как есть (SQLite типы не навязывает)
    и потом падала уже в расчёте маршрута.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = None
    if v is None or not SPEED_MIN <= v <= SPEED_MAX:
        report["dropped"].append(
            f"{source}: avg_route_speed_kmh={value!r} — не скорость "
            f"{SPEED_MIN:.0f}–{SPEED_MAX:.0f} км/ч, взят дефолт "
            f"{DEFAULT_PREFS.avg_route_speed_kmh:.0f}")
        return
    defaults["avg_route_speed_kmh"] = v


def _take_model(key, source: str, defaults: dict, report: dict, valid_model_keys) -> None:
    """Ключ метеомодели из model.json — только известный вызывающему.

    Отката «не передали список — не проверяем» здесь нет намеренно: он и был
    дырой. Неизвестный ключ доезжал до колонки и потом ронял engine.model_id
    KeyError'ом на КАЖДОМ запросе этого пилота, навсегда и без самолечения.
    """
    if key not in valid_model_keys:
        report["dropped"].append(
            f"{source}: model={key!r} — неизвестная модель, взят дефолт "
            f"«{DEFAULT_PREFS.model_key}»")
        return
    defaults["model_key"] = key


def migrate_from_json(data_dir: str, allowed_user_ids, *, valid_model_keys,
                      extra_dirs=(), skip_paths=()) -> dict:
    """Перенести sites/routes/settings/model из JSON в БД.

    allowed_user_ids — кому раздать бывшие общими маршруты и личные настройки.
    Пустой список означает, что владелец ещё не заполнил .env (и до тех пор
    бот с приложением не пускают никого, guards.allowed_ids): раздавать
    некому — routes/settings/model пропускаются, файлы остаются на месте, и
    миграцию можно повторить, когда список появится.

    valid_model_keys — допустимые ключи метеомодели, ОБЯЗАТЕЛЕН. Список моделей
      это знание домена, хранилище его не держит и импортировать engine не
      может (цикл), поэтому список приходит параметром — но без дефолта:
      «забыли передать» означало бы «не проверяем», а миграция это единственный
      путь записи model_key без валидации перед ним. Неизвестный ключ доезжал
      бы до колонки и ронял engine.model_id на каждом запросе этого пилота.
      set_model() при этом валидацию по-прежнему не делает — там её место у
      вызывающего, и это осознанное решение, а не недосмотр.
    extra_dirs — где ещё искать старые файлы, кроме каталога БД (см. _legacy_path).
    skip_paths — пути, которые личными данными не считаются (упакованный засев).

    report["dropped"] — всё, что в БД не попало, строкой с причиной. Файлы после
    переноса переименовываются, и без этого списка потеря была бы молчаливой:
    данные лежат в *.migrated, но никто не знает, что туда надо смотреть.
    """
    report = {"sites": 0, "routes": 0, "users": 0, "skipped": [], "dropped": []}
    dirs = [data_dir, *extra_dirs]

    sites_path = _legacy_path(dirs, "sites.json", skip_paths)
    if sites_path:
        src = os.path.basename(sites_path)
        try:
            raw = _read_json(sites_path)
            for k, s in enumerate(raw.get("sites", [])):
                _add_site_counted(s, k, src, report)
            _mark_migrated(sites_path)
        except (OSError, ValueError, AttributeError):
            report["skipped"].append(src)

    routes_path = _legacy_path(dirs, "routes.json", skip_paths)
    if routes_path:
        src = os.path.basename(routes_path)
        if not allowed_user_ids:
            report["skipped"].append(src)
        else:
            try:
                raw = _read_json(routes_path)
                for name, entry in (raw or {}).items():
                    pts = entry.get("points") if isinstance(entry, dict) else None
                    if not isinstance(pts, list):
                        report["dropped"].append(f"{src}: «{name}» — points не список")
                        continue
                    for uid in allowed_user_ids:
                        try:
                            route_save(uid, name, pts)
                            report["routes"] += 1
                        except (ValueError, TypeError, sqlite3.Error) as e:
                            report["dropped"].append(f"{src}: «{name}» → {uid} — {e}")
                _mark_migrated(routes_path)
            except (OSError, ValueError, AttributeError):
                report["skipped"].append(src)

    defaults = {}
    settings_path = _legacy_path(dirs, "settings.json", skip_paths)
    if settings_path:
        src = os.path.basename(settings_path)
        if not allowed_user_ids:
            report["skipped"].append(src)
        else:
            try:
                raw = _read_json(settings_path)
                if isinstance(raw, dict):
                    if "avg_route_speed_kmh" in raw:
                        _take_speed(raw["avg_route_speed_kmh"], src, defaults, report)
                    if "wind_correction_enabled" in raw:
                        defaults["wind_correction_enabled"] = \
                            1 if raw["wind_correction_enabled"] else 0
                _mark_migrated(settings_path)
            except (OSError, ValueError):
                report["skipped"].append(src)

    model_path = _legacy_path(dirs, "model.json", skip_paths)
    if model_path:
        src = os.path.basename(model_path)
        if not allowed_user_ids:
            report["skipped"].append(src)
        else:
            try:
                raw = _read_json(model_path)
                key = raw.get("model") if isinstance(raw, dict) else None
                if key:
                    _take_model(key, src, defaults, report, valid_model_keys)
                _mark_migrated(model_path)
            except (OSError, ValueError):
                report["skipped"].append(src)

    if defaults:
        for uid in allowed_user_ids:
            for column, value in defaults.items():
                _set_pref(uid, column, value)
            report["users"] += 1

    return report


def bootstrap(data_dir: str, allowed_user_ids, packaged_sites: str, *,
              valid_model_keys, extra_dirs=()) -> dict:
    """Полная подготовка хранилища на старте: схема, миграция, засев.

    Засев из упакованного sites.json срабатывает только на пустой библиотеке —
    иначе удалённый старт возвращался бы после каждого рестарта. По той же
    причине упакованный файл исключён из поиска старых файлов миграцией.

    valid_model_keys обязателен и просто передаётся дальше: дефолт здесь снова
    сделал бы проверку модели необязательной, на слой выше.
    """
    init()
    report = migrate_from_json(data_dir, allowed_user_ids,
                               valid_model_keys=valid_model_keys,
                               extra_dirs=extra_dirs,
                               skip_paths=(packaged_sites,))
    if not load_sites() and os.path.exists(packaged_sites):
        src = os.path.basename(packaged_sites)
        try:
            for k, s in enumerate(_read_json(packaged_sites).get("sites", [])):
                _add_site_counted(s, k, src, report)
        except (OSError, ValueError, AttributeError):
            report["skipped"].append(src)
    purge_adhoc()
    return report

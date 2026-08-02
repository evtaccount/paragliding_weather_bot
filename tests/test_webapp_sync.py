"""Копии знания в мини-приложении держатся рядом со своим источником.

Тот же приём, что и tests/test_palette_sync.py для цветов: часть величин
приходится держать в TypeScript второй копией — языки разные, а отдавать
константу отдельным полем в каждом ответе сервера дороже, чем она стоит.
Копии собраны в одном файле (webapp/src/domain.ts), а этот тест читает его и
сверяет каждую с питоном. Разошлись — краснеет прогон, а не пилот на склоне:
незамеченное расхождение здесь означает латинский `no_window` под баллом
маршрута, «goal» в заголовке карточки точки или дождь, о котором чат говорит,
а приложение молчит.

Значения, которые ЗАВИСЯТ от запроса (модель прогноза, лётность дня, описание
погоды), сюда не входят — они приходят ответом сервера и копий не имеют.

Здесь же — две проверки, у которых источник не питоновский, а внутри самого
приложения (палитра темы, директивы линтера). Живут они тут потому, что
питоновский прогон читает файлы приложения с диска как есть, а прогон
vitest — через сборщик Vite, и при `css: false` (webapp/vite.config.ts)
содержимое styles.css доезжает до теста ПУСТОЙ строкой: проверка проходила бы
всегда, ничего не проверяя (воспроизведено пробником).
"""
import ast
import json
import pathlib
import re

import criteria
import engine
import route

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOMAIN_TS = ROOT / "webapp" / "src" / "domain.ts"
MAP_VIEW_TS = ROOT / "webapp" / "src" / "map" / "MapView.tsx"
THEME_TS = ROOT / "webapp" / "src" / "theme.ts"
STYLES_CSS = ROOT / "webapp" / "src" / "styles.css"
PACKAGE_JSON = ROOT / "webapp" / "package.json"
WEBAPP_SRC = ROOT / "webapp" / "src"
SITES_JSON = ROOT / "sites.json"


def _literal(source: str, name: str) -> object:
    """Значение объявления `export const <name>[: тип] = <литерал>` из TypeScript.

    Литералы объектов и массивов у обоих языков совпадают по написанию
    настолько, что их разбирает ast.literal_eval — своего разборщика
    TypeScript тут не нужно. Ключи объекта без кавычек (`takeoff: "старт"`)
    закавычиваются перед разбором.
    """
    match = re.search(rf"export const {name}(?::[^=]+)? = (.+?)\n(?:\n|export |//)",
                      source + "\n\n", re.DOTALL)
    assert match, f"в {DOMAIN_TS.name} нет объявления {name}"
    body = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', match.group(1).strip())
    return ast.literal_eval(body)


def _domain() -> str:
    return DOMAIN_TS.read_text(encoding="utf-8")


def test_compass_rose_matches_engine():
    """Роза румбов приложения — та же, что рисует бот (engine.card)."""
    assert _literal(_domain(), "CARD16") == engine.CARD


def test_rain_threshold_matches_criteria():
    """Порог «про дождь стоит сказать» — тот же, по которому его печатает чат."""
    assert _literal(_domain(), "RAIN_DAY_MM") == criteria.RAIN_DAY_MM


def test_ms_to_kmh_matches_route():
    assert _literal(_domain(), "MS_TO_KMH") == route.MS_TO_KMH


def test_feasibility_labels_match_route():
    """Проходимость маршрута подписана в приложении теми же словами, что в чате."""
    assert _literal(_domain(), "FEASIBILITY_RU") == route.FEASIBILITY_RU


def test_every_feasibility_key_is_translated():
    """Новый статус в criteria.FEASIBILITY без подписи — латынь на экране.

    Проверяются ОБА словаря: и питоновский (карточка в чате), и его копия в
    приложении. Приложение показывает незнакомый ключ как есть
    (`FEASIBILITY_RU[f] ?? f`, screens/Route.tsx), то есть печатает
    `no_window` под баллом маршрута и на чипе времени вылета.
    """
    keys = set(criteria.FEASIBILITY)
    assert keys <= set(route.FEASIBILITY_RU)
    assert keys <= set(_literal(_domain(), "FEASIBILITY_RU"))


def test_role_labels_match_route():
    assert _literal(_domain(), "ROLE_RU") == route.ROLE_RU


def test_map_fallback_center_is_a_site_from_the_shipped_library():
    """Запасной центр карты — первый старт ПОСТАВОЧНОГО sites.json.

    Свежая установка без стартов и без маршрута — единственный случай, когда
    карте не на что навестись, кроме этой константы. Раньше в ней стояли
    координаты Гудаури из тестовой фикстуры — старта, которого в поставке нет
    (финальное ревью ветки, m5).
    """
    first = json.loads(SITES_JSON.read_text(encoding="utf-8"))["sites"][0]
    text = MAP_VIEW_TS.read_text(encoding="utf-8")
    match = re.search(r"const FALLBACK_CENTER[^=]*= (\[[^\]]+\])", text)
    assert match, "в MapView.tsx нет объявления FALLBACK_CENTER"
    assert ast.literal_eval(match.group(1)) == [first["lat"], first["lon"]]


def test_theme_palette_is_not_copied_into_the_stylesheet():
    """Цвета темы объявлены ровно в одном месте — theme.ts.

    Раньше светлая палитра лежала и в theme.ts (LIGHT_PALETTE), и в styles.css
    (:root) — десять значений слово в слово. Копия в CSS была не просто
    лишней, а ловушкой: правка цвета там — первое место, куда идёт человек, —
    не давала ничего, потому что App.tsx первым же эффектом выставляет весь
    набор из theme.ts на document.documentElement (финальное ревью ветки, m2).
    Проверяется отсутствие ВТОРОГО объявления, а не совпадение значений:
    совпадающие копии всё равно оставляли бы правку в CSS бесполезной.
    """
    palette = set(re.findall(r'"(--[a-z-]+)":', THEME_TS.read_text(encoding="utf-8")))
    assert palette, "в theme.ts не нашлось ни одного слота палитры — проверьте разбор"
    declared = set(re.findall(r"^\s*(--[a-z-]+)\s*:", STYLES_CSS.read_text(encoding="utf-8"), re.M))
    assert not (palette & declared), (
        "цвета темы объявлены и в styles.css: " + ", ".join(sorted(palette & declared)))


def test_no_eslint_directives_while_there_is_no_eslint():
    """Директива линтера, которого нет, обещает читателю проверку-призрак.

    eslint в проекте не установлен и не настроен: ни зависимости в
    package.json, ни конфигурации. Строка `eslint-disable-next-line
    react-hooks/exhaustive-deps` в map/MapView.tsx выглядела как «здесь
    линтер проверил и мы его отключили осознанно», хотя не проверял никто
    (финальное ревью ветки, m7). Появится eslint — этот тест придётся снять
    вместе с добавлением конфигурации, и это правильный повод пересмотреть
    сами директивы.
    """
    package = PACKAGE_JSON.read_text(encoding="utf-8")
    assert "eslint" not in package, "eslint появился — пересмотрите этот тест и директивы в коде"
    offenders = [str(p.relative_to(ROOT)) for p in WEBAPP_SRC.rglob("*.ts*")
                 if "eslint-disable" in p.read_text(encoding="utf-8")]
    assert not offenders, ("директивы eslint без самого eslint: " + ", ".join(offenders))

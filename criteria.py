"""Парапланерные критерии: пороги, веса, вето, скоринг 0–100.

ЕДИНСТВЕННОЕ место в проекте, где живут числа. `engine`, `charts` и промпт
`analysis` читают их отсюда — раньше одни и те же пороги были продублированы
литералами в трёх файлах и пересказаны текстом в промпте, и расходились при
любой правке.

Калибровка — уверенный XC-пилот на Niviuk Ikuma 3 P (trim ≈38 км/ч ≈ 10,6 м/с),
НЕ новичок. Пороги ветра/порывов — экспертный консенсус пилотских источников,
а не результат стандартизованных испытаний; их стоит калибровать под себя.

Модуль чистый: значения на вход → оценки на выход. Ни сети, ни файлов, ни
импорта engine. Скорость ветра везде в м/с, высоты в метрах, температура в °C.

Схема расчёта часа:
    значение параметра → уровень (бэнд) → субоценка 0–100
    → свёртка по группе (min/mean) → веса групп → взвешенная сумма
    → мультипликативные штрафы → потолок по лимитирующему фактору
    → вето → категория

Правило пропусков: параметр None не оценивается, его группа считается по
оставшимся, веса перенормируются, в warnings уходит `no_data:<поле>`.
Значения НИКОГДА не подставляются.
"""
from dataclasses import dataclass, field

CRITERIA_VERSION = "2026-07-doc-v1"
GLIDER = "Niviuk Ikuma 3 P"
TRIM_MS = 10.6          # trim-скорость крыла, м/с (≈38 км/ч) — жёсткий потолок по ветру
TOP_MS = 14.2           # максимальная скорость на акселераторе (≈51 км/ч)

RAIN_DAY_MM = 0.2       # осадки за день → мокрый день
RAIN_HR_MM = 0.1        # осадки за час → мокрый час
LCL_M_PER_C = 122       # база облаков: метров на 1 °C спреда T−Td (Bradbury / FAA)

MIN_GROUND_SPEED_KMH = 8.0   # ниже этой путевой маршрут практически не идётся
MIN_WORKING_ALT_AGL = 300    # ниже пилот не идёт на переход, а ищет площадку

# Отношение порыв/ветер неустойчиво на слабом ветре: 2,1 м/с с порывом 5,6 —
# это обычный рабочий термический день, а формальный «фактор 2,6» давал вето и
# красил такой час в ⛔. Правило «порывы >1,5× среднего» из пилотской практики
# подразумевает СОИЗМЕРИМЫЙ средний ветер, при штиле оно вырождается.
#
# Поэтому знаменатель ограничен снизу опорным ветром — верхней границей
# «отличного» диапазона у земли, то есть скоростью, при которой ветер уже сам
# по себе фактор. Ниже неё порывистость оценивает абсолютный отрыв
# (параметр gust_delta) — он в той же группе и сворачивается по худшему,
# и при слабом ветре именно он и есть мера рваности.
#
# Документ такой оговорки не даёт: она добавлена после проверки на реальных
# данных. Без неё ветер 4 м/с с порывом 7 (14→25 км/ч — обычный рабочий день)
# получал «нелётно» по группе порывов и топил весь день до маргинального,
# а ветер 2 м/с с порывом 5,6 — прямое вето.
GUST_FACTOR_REF_WIND_MS = 6.1

# Если суммарный вес доступных групп ниже этого — категория ограничивается
# сверху «удовлетворительной»: нельзя объявить идеальный день, не проверив
# треть критериев.
MIN_CONFIDENCE = 0.6

# Потолок по лимитирующему фактору.
#
# Взвешенная сумма по десяти группам сама по себе слишком снисходительна: если
# девять групп идеальны, десятая не сдвинет балл ниже ~85, даже когда она
# «нелётная». Ветер точно в спину склону давал «идеальный день» — так нельзя.
# Документ называет лимитирующий фактор («то, что тянет день вниз»), но в
# формуле его не использует; здесь он и применяется: итоговый балл не может
# быть выше, чем на ОДИН уровень над худшей значимой группой.
#
# Группы весом 0,02 (стратификация, длительность окна) в потолок не входят —
# документ сам объявил их второстепенными, и давать им право обрушить оценку
# было бы противоречием.
LIMIT_CAP_MIN_WEIGHT = 0.06

GRADES = ("ideal", "excellent", "fair", "marginal", "no_fly", "danger")
GRADE_SCORE = {"ideal": 100, "excellent": 85, "fair": 65, "marginal": 40, "no_fly": 15, "danger": 0}
GRADE_LABEL = {"ideal": "идеально", "excellent": "отлично", "fair": "удовлетворительно",
               "marginal": "маргинально", "no_fly": "нелётно", "danger": "опасно"}

# Балл → категория. Порядок по убыванию нижней границы.
CATEGORIES = (
    ("ideal",     85, "🟢🟢", "идеальная"),
    ("excellent", 70, "🟢",   "отличная лётная"),
    ("fair",      55, "🟡",   "удовлетворительная"),
    ("marginal",  40, "🟠",   "маргинальная"),
    ("no_fly",    15, "🔴",   "нелётная"),
    ("danger",     0, "⛔",   "опасная"),
)
NO_DATA = ("no_data", "⚪", "нет данных")


@dataclass(frozen=True)
class Param:
    """Один критерий: как называется, к какой группе относится, как размечен.

    `bands` — уровни в порядке возрастания значения параметра; интервалы
    полуоткрытые [lo, hi), None означает ±бесконечность. У немонотонных
    параметров (W*, Thermal Index, спред, облачность) один уровень может
    состоять из нескольких интервалов — оптимум у них в середине.
    """
    key: str
    group: str
    label: str
    unit: str
    bands: tuple            # ((grade, ((lo, hi), ...)), ...)
    fmt: str = "{:.1f}"

    def grade(self, value):
        if value is None:
            return None
        for grade, intervals in self.bands:
            for lo, hi in intervals:
                if (lo is None or value >= lo) and (hi is None or value < hi):
                    return grade
        return None  # недостижимо: покрытие оси проверяется тестом

    def show(self, value):
        return "н/д" if value is None else self.fmt.format(value) + (f" {self.unit}" if self.unit else "")


@dataclass(frozen=True)
class Group:
    """Группа критериев со своим весом и объявленным способом свёртки.

    `min` — для групп безопасности: решает худший параметр (сильный ветер не
    компенсируется удачным направлением). `mean` — для термички и температуры,
    где важна общая картина, а не одно число.
    """
    key: str
    weight: float
    label: str
    agg: str = "min"


GROUPS = {g.key: g for g in (
    Group("wind",       0.22, "ветер"),
    Group("gusts",      0.15, "порывы"),
    Group("direction",  0.12, "направление к склону"),
    Group("thermals",   0.15, "термичка", agg="mean"),
    Group("storms",     0.12, "неустойчивость/грозы"),
    Group("cloud",      0.08, "облачность и база"),
    Group("precip_vis", 0.06, "осадки и видимость"),
    Group("shear",      0.06, "сдвиг ветра"),
    Group("temp",       0.02, "стратификация", agg="mean"),
    Group("extra",      0.02, "длительность окна"),
)}

# Веса маршрутного профиля. Направление к склону и порывы у земли ушли совсем —
# их место заняли ветер вдоль курса, рабочий диапазон высот и увеличенный вес гроз.
# Это и есть содержательная разница между «стою на старте» и «лечу».
ROUTE_GROUPS = {g.key: g for g in (
    Group("wind_along",   0.20, "ветер вдоль курса"),
    Group("thermals",     0.18, "термичка", agg="mean"),
    Group("working_band", 0.16, "рабочий диапазон высот"),
    Group("storms",       0.16, "неустойчивость/грозы"),
    Group("wind_abs",     0.10, "ветер на рабочей высоте"),
    Group("precip_vis",   0.08, "осадки и видимость"),
    Group("cloud",        0.06, "облачность"),
    Group("wind_cross",   0.04, "снос поперёк курса"),
    Group("extra",        0.02, "окно и запас времени"),
)}

_ALL = (None, None)  # вся ось — для читаемости таблицы

# Шкала ветра на высоте. Общая для 850 гПа и для среднего ветра рабочего слоя:
# это одна и та же физика на близких высотах, и две копии чисел разъехались бы.
_WIND_ALOFT_BANDS = (
    ("ideal",     ((None, 6.1),)),
    ("excellent", ((6.1, 8.3),)),
    ("fair",      ((8.3, 10.6),)),
    ("marginal",  ((10.6, 12.5),)),
    ("no_fly",    ((12.5, 13.9),)),
    ("danger",    ((13.9, None),)),
)

PARAMS = {p.key: p for p in (
    # --- ветер (0,22) ---------------------------------------------------------
    # «Опасно» задано как приближение к trim крыла: при среднем ветре ≈trim пилот
    # теряет путевую скорость и не может уйти от рельефа и ротора.
    Param("wind_10m", "wind", "ветер у земли", "м/с", (
        ("ideal",     ((None, 4.2),)),
        ("excellent", ((4.2, 6.1),)),
        ("fair",      ((6.1, 7.8),)),
        ("marginal",  ((7.8, 9.2),)),
        ("no_fly",    ((9.2, TRIM_MS),)),
        ("danger",    ((TRIM_MS, None),)),
    )),
    Param("wind_925", "wind", "ветер на 925 гПа", "м/с", (
        ("ideal",     ((None, 5.0),)),
        ("excellent", ((5.0, 6.9),)),
        ("fair",      ((6.9, 8.9),)),
        ("marginal",  ((8.9, 10.6),)),
        ("no_fly",    ((10.6, 12.5),)),
        ("danger",    ((12.5, None),)),
    )),
    Param("wind_850", "wind", "ветер на 850 гПа", "м/с", _WIND_ALOFT_BANDS),
    # --- порывы (0,15) --------------------------------------------------------
    # Общепринятое правило: порывы >1,5× среднего или >8 узлов над ним — воздух
    # слишком активен для мягкого крыла. Абсолютная дельта важна при слабом
    # среднем: 10→24 узла опаснее устойчивых 14.
    Param("gust_factor", "gusts", "порывистость (порыв/ветер)", "", (
        ("ideal",     ((None, 1.25),)),
        ("excellent", ((1.25, 1.35),)),
        ("fair",      ((1.35, 1.45),)),
        ("marginal",  ((1.45, 1.55),)),
        ("no_fly",    ((1.55, 1.7),)),
        ("danger",    ((1.7, None),)),
    ), fmt="{:.2f}"),
    Param("gust_delta", "gusts", "отрыв порыва от ветра", "м/с", (
        ("ideal",     ((None, 1.7),)),
        ("excellent", ((1.7, 2.5),)),
        ("fair",      ((2.5, 3.3),)),
        ("marginal",  ((3.3, 4.2),)),
        ("no_fly",    ((4.2, 5.6),)),
        ("danger",    ((5.6, None),)),
    )),
    # --- направление (0,12) ---------------------------------------------------
    Param("dir_offset", "direction", "отклонение ветра от склона", "°", (
        ("ideal",     ((None, 15),)),
        ("excellent", ((15, 25),)),
        ("fair",      ((25, 35),)),
        ("marginal",  ((35, 45),)),
        ("no_fly",    ((45, 60),)),
        ("danger",    ((60, None),)),
    ), fmt="{:.0f}"),
    # --- термичка (0,15) ------------------------------------------------------
    # Оптимум в середине: выше 4,5–5,5 м/с потоки становятся узкими, рваными и
    # с сильной турбулентностью на срыве — формально «сильно», практически «опасно».
    Param("w_star", "thermals", "сила потоков (оценка W*)", "м/с", (
        ("no_fly",    ((None, 1.0),)),
        ("marginal",  ((1.0, 1.3), (4.5, 5.5))),
        ("fair",      ((1.3, 1.7), (3.5, 4.5))),
        ("excellent", ((1.7, 2.0), (3.0, 3.5))),
        ("ideal",     ((2.0, 3.0),)),
        ("danger",    ((5.5, None),)),
    )),
    Param("bl_depth", "thermals", "глубина рабочего слоя", "м", (
        ("no_fly",    ((None, 300),)),
        ("marginal",  ((300, 500),)),
        ("fair",      ((500, 800),)),
        ("excellent", ((800, 1200), (2500, None))),
        ("ideal",     ((1200, 2500),)),
    ), fmt="{:.0f}"),
    Param("thermal_index", "thermals", "Thermal Index", "", (
        ("danger",    ((None, -8),)),
        ("excellent", ((-8, -6), (-3, -2))),
        ("ideal",     ((-6, -3),)),
        ("fair",      ((-2, -1),)),
        ("marginal",  ((-1, 0),)),
        ("no_fly",    ((0, None),)),
    )),
    # --- грозы и неустойчивость (0,12) ---------------------------------------
    # CAPE — «топливо» для гроз, а НЕ мера силы рабочих термиков. Для параплана
    # опасность начинается задолго до синоптического «severe» (2000+ J/kg).
    Param("cape", "storms", "CAPE", "Дж/кг", (
        ("ideal",     ((None, 300),)),
        ("excellent", ((300, 800),)),
        ("fair",      ((800, 1500),)),
        ("marginal",  ((1500, 2500),)),
        ("danger",    ((2500, None),)),
    ), fmt="{:.0f}"),
    Param("lifted_index", "storms", "Lifted Index", "", (
        ("danger",    ((None, -4),)),
        ("marginal",  ((-4, -2),)),
        ("fair",      ((-2, 0),)),
        ("excellent", ((0, 2),)),
        ("ideal",     ((2, None),)),
    )),
    # --- облачность и база (0,08) --------------------------------------------
    # Cu — лучший маркер термиков, но плотный покров отсекает солнце и выключает
    # конвекцию. Ниже 10 % — «голубой» день: потоки есть, маркеров нет.
    Param("cloud_low", "cloud", "низкая облачность", "%", (
        ("excellent", ((None, 10), (30, 45))),
        ("ideal",     ((10, 30),)),
        ("fair",      ((45, 60),)),
        ("marginal",  ((60, 75),)),
        ("no_fly",    ((75, None),)),
    ), fmt="{:.0f}"),
    Param("base_clearance", "cloud", "запас база−старт", "м", (
        ("no_fly",    ((None, 150),)),
        ("marginal",  ((150, 200),)),
        ("fair",      ((200, 400),)),
        ("excellent", ((400, 600),)),
        ("ideal",     ((600, None),)),
    ), fmt="{:.0f}"),
    # --- осадки и видимость (0,06) -------------------------------------------
    Param("precip_prob", "precip_vis", "вероятность осадков", "%", (
        ("ideal",     ((None, 10),)),
        ("excellent", ((10, 20),)),
        ("fair",      ((20, 40),)),
        ("marginal",  ((40, 60),)),
        ("danger",    ((60, None),)),
    ), fmt="{:.0f}"),
    Param("visibility", "precip_vis", "видимость", "м", (
        ("danger",    ((None, 1500),)),
        ("marginal",  ((1500, 5000),)),
        ("fair",      ((5000, 10000),)),
        ("ideal",     ((10000, None),)),
    ), fmt="{:.0f}"),
    # --- сдвиг ветра (0,06) ---------------------------------------------------
    Param("shear_100m", "shear", "сдвиг ветра у земли (0–100 м)", "м/с", (
        ("ideal",     ((None, 2.2),)),
        ("excellent", ((2.2, 3.3),)),
        ("fair",      ((3.3, 4.2),)),
        ("marginal",  ((4.2, 5.6),)),
        ("no_fly",    ((5.6, 6.9),)),
        ("danger",    ((6.9, None),)),
    )),
    # --- стратификация (0,02) -------------------------------------------------
    # Спред — драйвер высоты базы. Малый спред → низкая база и риск осадков,
    # большой → высокая база, но «голубой» день без маркеров.
    Param("spread", "temp", "спред T−Td", "°C", (
        ("no_fly",    ((None, 1),)),
        ("marginal",  ((1, 2), (16, None))),
        ("fair",      ((2, 3), (12, 16))),
        ("ideal",     ((3, 8),)),
        ("excellent", ((8, 12),)),
    )),
    # --- длительность окна (0,02) --------------------------------------------
    # Несколько «отличных» часов подряд ценнее одного «идеального».
    Param("window_hours", "extra", "длительность окна", "ч", (
        ("no_fly",    ((None, 0.5),)),
        ("marginal",  ((0.5, 1),)),
        ("fair",      ((1, 2),)),
        ("excellent", ((2, 4),)),
        ("ideal",     ((4, None),)),
    ), fmt="{:.1f}"),
    # --- маршрутные параметры -------------------------------------------------
    # Шкала асимметрична намеренно: сильный попутный — подарок, сильный встречный
    # растягивает маршрут и закрывает окно раньше, чем пилот долетит. Уровень
    # «опасно» ниже −25 км/ч: при воздушной 25 км/ч это отрицательная путевая.
    Param("wind_along", "wind_along", "ветер вдоль курса", "км/ч", (
        ("danger",    ((None, -25),)),
        ("no_fly",    ((-25, -15),)),
        ("marginal",  ((-15, -8),)),
        ("fair",      ((-8, 0), (28, None))),
        ("excellent", ((0, 8), (20, 28))),
        ("ideal",     ((8, 20),)),
    ), fmt="{:+.0f}"),
    # Значение подаётся ПО МОДУЛЮ: снос вправо и влево одинаково требует крабинга.
    # «Опасно» с 45 км/ч — заметно выше воздушной скорости, курс не удержать.
    Param("wind_cross", "wind_cross", "снос поперёк курса", "км/ч", (
        ("ideal",     ((None, 10),)),
        ("excellent", ((10, 18),)),
        ("fair",      ((18, 26),)),
        ("marginal",  ((26, 34),)),
        ("no_fly",    ((34, 45),)),
        ("danger",    ((45, None),)),
    ), fmt="{:.0f}"),
    Param("working_band", "working_band", "рабочий диапазон высот", "м", (
        ("danger",    ((None, 0),)),
        ("no_fly",    ((0, 150),)),
        ("marginal",  ((150, 300),)),
        ("fair",      ((300, 600),)),
        ("excellent", ((600, 1200),)),
        ("ideal",     ((1200, None),)),
    ), fmt="{:.0f}"),
    Param("time_margin", "extra", "запас времени до закрытия окна", "мин", (
        ("danger",    ((None, 0),)),
        ("no_fly",    ((0, 20),)),
        ("marginal",  ((20, 60),)),
        ("fair",      ((60, 120),)),
        ("excellent", ((120, 180),)),
        ("ideal",     ((180, None),)),
    ), fmt="{:.0f}"),
    Param("wind_working", "wind_abs", "ветер на рабочей высоте", "м/с",
          _WIND_ALOFT_BANDS),
)}


@dataclass(frozen=True)
class Rule:
    """Вето или штраф. `needs` — поля, без которых правило нельзя проверить:
    если хоть одно None, правило НЕ срабатывает и попадает в unchecked."""
    key: str
    label: str
    needs: tuple
    test: object
    factor: float = 0.0   # для штрафа — множитель; для вето не используется


def _lt(v, x):
    return v is not None and v < x


def _ge(v, x):
    return v is not None and v >= x


# Любое сработавшее вето → категория «опасная», балл 0, независимо от суммы.
# Фён в этот список НЕ входит: правило Шамони (перепад давления через хребет)
# требует двух точек по разные стороны хребта, у бота точечные данные.
# Он остаётся эвристическим предупреждением (см. foehn_suspect в engine).
VETOES = (
    Rule("precip_hour", "осадки в этот час", ("precip_mm",),
         lambda r: r["precip_mm"] > RAIN_HR_MM),
    Rule("precip_prob", "высокая вероятность осадков (>60%)", ("precip_prob",),
         lambda r: r["precip_prob"] > 60),
    Rule("cape_extreme", "экстремальный CAPE (>2500)", ("cape",),
         lambda r: r["cape"] > 2500),
    Rule("cape_cin", "высокий CAPE при снятой крышке (CIN<25)", ("cape", "cin"),
         lambda r: r["cape"] > 1500 and r["cin"] < 25),
    Rule("lifted_index", "сильная неустойчивость (LI<−4)", ("lifted_index",),
         lambda r: r["lifted_index"] < -4),
    Rule("lee_side", "старт с подветра", ("dir_offset",),
         lambda r: r["dir_offset"] > 90),
    Rule("wind_launch", f"ветер у земли ≥ trim крыла ({TRIM_MS} м/с)", ("wind_10m",),
         lambda r: r["wind_10m"] >= TRIM_MS),
    Rule("wind_base", f"ветер на базе ≥ trim крыла ({TRIM_MS} м/с)", ("wind_at_base",),
         lambda r: r["wind_at_base"] >= TRIM_MS),
    Rule("gust_factor", "порывистость >1,7×", ("gust_factor",),
         lambda r: r["gust_factor"] > 1.7),
    Rule("gust_delta", "отрыв порыва >5,6 м/с", ("gust_delta",),
         lambda r: r["gust_delta"] > 5.6),
    Rule("base_below_route", "база ниже вершин маршрута", ("base_over_route",),
         lambda r: r["base_over_route"] <= 0),
    Rule("visibility", "видимость <1,5 км", ("visibility",),
         lambda r: r["visibility"] < 1500),
    Rule("shear", "сдвиг ветра у земли >6,9 м/с", ("shear_100m",),
         lambda r: r["shear_100m"] > 6.9),
    # --- маршрутные вето ------------------------------------------------------
    # Срабатывают только в профиле маршрута и НЕ обнуляют весь маршрут: свёртка
    # переводит его в состояние «обрывается на N-м км» с указанием километра.
    Rule("route_terrain_block", "база ниже безопасной высоты над рельефом",
         ("working_band",), lambda r: r["working_band"] <= 0),
    Rule("route_no_progress", f"эффективная путевая ≤ {MIN_GROUND_SPEED_KMH:.0f} км/ч",
         ("ground_speed",), lambda r: r["ground_speed"] <= MIN_GROUND_SPEED_KMH),
    Rule("route_window_closed", "прилёт после закрытия термического окна",
         ("time_margin",), lambda r: r["time_margin"] < 0),
)

# Нелинейные взаимодействия: сильный ветер плюс сильные термики дают
# мультипликативный, а не аддитивный риск.
PENALTIES = (
    Rule("wind_x_thermal", "сильный ветер вместе с мощными потоками",
         ("wind_10m", "w_star"), lambda r: r["wind_10m"] > 7.8 and r["w_star"] > 3.5, factor=0.80),
    Rule("dir_misalign", "направление ветра расходится по высотам >45°",
         ("dir_misalign",), lambda r: r["dir_misalign"] > 45, factor=0.85),
    Rule("low_base_active", "малый запас под базой при активной термичке",
         ("base_clearance", "w_star"),
         lambda r: r["base_clearance"] < 300 and r["w_star"] >= 2.0, factor=0.85),
)


@dataclass(frozen=True)
class Profile:
    """Роль точки определяет, по каким критериям её оценивать.

    У точки в воздухе нет склона, поэтому спрашивать «совпадает ли ветер с
    направлением склона» там бессмысленно; на финише наоборот снова важны
    приземный ветер и порывы — это посадка. Веса, набор параметров, вето и
    штрафы едут вместе, потому что менять их поодиночке нельзя: выкинутая
    группа без перенормировки весов тихо занижает балл.
    """
    key: str
    label: str
    groups: dict
    params: tuple
    vetoes: tuple
    penalties: tuple

    def group_params(self, gkey):
        return tuple(k for k in self.params if PARAMS[k].group == gkey)


# Наборы параметров перечислены ЯВНО, а не выведены из PARAMS: иначе любой новый
# параметр молча протекал бы во все профили сразу.
_LAUNCH_PARAMS = ("wind_10m", "wind_925", "wind_850", "gust_factor", "gust_delta",
                  "dir_offset", "w_star", "bl_depth", "thermal_index", "cape",
                  "lifted_index", "cloud_low", "base_clearance", "precip_prob",
                  "visibility", "shear_100m", "spread", "window_hours")

_ENROUTE_PARAMS = ("wind_along", "wind_cross", "working_band", "wind_working",
                   "w_star", "bl_depth", "thermal_index", "cape", "lifted_index",
                   "cloud_low", "precip_prob", "visibility", "window_hours",
                   "time_margin")

# Вето, применимые везде: погода не спрашивает, стоишь ты или летишь.
_COMMON_VETOES = ("precip_hour", "precip_prob", "cape_extreme", "cape_cin",
                  "lifted_index", "visibility", "wind_base")
# Вето про близость к земле — старт и посадка.
_GROUND_VETOES = ("wind_launch", "gust_factor", "gust_delta", "shear")
# Вето, осмысленные только на старте.
_LAUNCH_ONLY_VETOES = ("lee_side", "base_below_route")
_ROUTE_VETOES = ("route_terrain_block", "route_no_progress", "route_window_closed")

_ALL_PENALTIES = tuple(r.key for r in PENALTIES)

TAKEOFF = Profile(
    "takeoff", "старт", GROUPS, _LAUNCH_PARAMS,
    _COMMON_VETOES + _GROUND_VETOES + _LAUNCH_ONLY_VETOES, _ALL_PENALTIES)

# Финиш — это посадка: приземный ветер и порывы снова важны, направление склона нет.
# Веса не перенормируются вручную: score_hour делит на сумму выживших групп сам.
GOAL = Profile(
    "goal", "финиш",
    {k: g for k, g in GROUPS.items() if k != "direction"},
    tuple(k for k in _LAUNCH_PARAMS if k != "dir_offset") + ("time_margin",),
    _COMMON_VETOES + _GROUND_VETOES, _ALL_PENALTIES)

# На маршруте из штрафов остаётся только расхождение направления по высотам.
# Два других завязаны на приземный ветер и запас под базой; выдумывать для них
# маршрутные аналоги значило бы калибровать без источника.
ENROUTE = Profile(
    "enroute", "маршрут", ROUTE_GROUPS, _ENROUTE_PARAMS,
    _COMMON_VETOES + _ROUTE_VETOES, ("dir_misalign",))

PROFILES = {p.key: p for p in (TAKEOFF, ENROUTE, GOAL)}


@dataclass
class HourAssessment:
    hour: int
    score: float | None
    category: str
    emoji: str
    label: str
    limiting: str | None = None          # ключ параметра с минимальной субоценкой
    limiting_label: str | None = None
    weighted: float | None = None        # взвешенная сумма ДО штрафов и потолка
    capped: bool = False                 # балл срезан потолком по лимит-фактору
    grades: dict = field(default_factory=dict)     # param key → grade
    subs: dict = field(default_factory=dict)       # param key → 0..100
    groups: dict = field(default_factory=dict)     # group key → 0..100
    confidence: float = 0.0
    penalties: list = field(default_factory=list)
    vetoes: list = field(default_factory=list)
    unchecked_vetoes: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def compact(self):
        """Короткая форма для данных, уходящих в LLM (payload не раздувается)."""
        d = {"score": None if self.score is None else round(self.score),
             "cat": self.category, "lim": self.limiting}
        if self.vetoes:
            d["veto"] = self.vetoes
        return d


@dataclass
class DayAssessment:
    date: str
    hours: list
    window: dict | None                  # термическое окно (engine.sun_hours)
    score: float | None
    category: str
    emoji: str
    label: str
    limiting: str | None = None
    limiting_label: str | None = None
    fly_hours: list = field(default_factory=list)   # лётные часы ВНУТРИ термического окна
    fly_window: tuple | None = None      # (час_начала, час_конца) по fly_hours
    confidence: float = 0.0
    warnings: list = field(default_factory=list)
    unchecked_vetoes: list = field(default_factory=list)
    vetoes_in_window: list = field(default_factory=list)


def grade_of(param_key, value):
    """Уровень параметра ('ideal'…'danger') или None, если значения нет."""
    return PARAMS[param_key].grade(value)


def category_of(score):
    """Балл → (ключ, эмодзи, русское название). None → «нет данных»."""
    if score is None:
        return NO_DATA
    for key, lo, emoji, label in CATEGORIES:
        if score >= lo:
            return key, emoji, label
    return CATEGORIES[-1][0], CATEGORIES[-1][2], CATEGORIES[-1][3]


FLYABLE = ("ideal", "excellent", "fair")


def flyable(category):
    """Категория, при которой день/час считается лётным (≥ «удовлетворительная»)."""
    return category in FLYABLE


def _cap(score, ceiling_grade):
    """Ограничить балл сверху потолком категории."""
    ceiling = {k: lo for k, lo, _e, _l in CATEGORIES}
    # верхняя граница уровня = нижняя граница следующего сверху минус 1
    order = [k for k, _lo, _e, _l in CATEGORIES]
    i = order.index(ceiling_grade)
    top = 100 if i == 0 else ceiling[order[i - 1]] - 1
    return min(score, top)


def _grade_of_score(value):
    """Субоценка → уровень, в чей диапазон она попадает (свёртка `mean` даёт
    промежуточные числа: 78 — это ещё «удовлетворительно», не «отлично»)."""
    for g in GRADES:                       # от лучшего к худшему
        if value >= GRADE_SCORE[g]:
            return g
    return "danger"


def _present_share(a, group_key, profile):
    """Доля параметров группы, у которых были данные."""
    keys = profile.group_params(group_key)
    return sum(1 for k in keys if k in a.subs) / len(keys) if keys else 0.0


def _one_level_up(grade):
    """Уровень на ступень выше ('no_fly' → 'marginal', 'ideal' → 'ideal')."""
    i = GRADES.index(grade)
    return GRADES[max(0, i - 1)]


def score_hour(raw, hour=0, profile=TAKEOFF):
    """Оценить один час по профилю роли точки. `raw` — плоский словарь.

    Ключи-параметры перечислены в PARAMS; дополнительно правила читают
    precip_mm, cin, wind_at_base, base_over_route, dir_misalign, ground_speed.

    Дефолт — профиль старта: он равен поведению до появления профилей, поэтому
    все существующие вызовы считают ровно то же самое.
    """
    a = HourAssessment(hour=hour, score=None, category=NO_DATA[0],
                       emoji=NO_DATA[1], label=NO_DATA[2], raw=dict(raw))

    # 1. субоценки параметров
    for key in profile.params:
        p = PARAMS[key]
        g = p.grade(raw.get(key))
        if g is None:
            a.warnings.append(f"no_data:{key}")
            continue
        a.grades[key] = g
        a.subs[key] = GRADE_SCORE[g]

    # 2. свёртка по группам (только по присутствующим параметрам)
    for gkey, group in profile.groups.items():
        vals = [a.subs[k] for k in profile.group_params(gkey) if k in a.subs]
        if not vals:
            continue
        a.groups[gkey] = min(vals) if group.agg == "min" else sum(vals) / len(vals)

    # Особый случай: CAPE высокий, а CIN неизвестен. Вето проверить нельзя
    # (см. unchecked ниже), но и рисовать зелёную группу «грозы» нельзя —
    # ограничиваем её сверху «маргинально».
    if "storms" in a.groups and _ge(raw.get("cape"), 1500) and raw.get("cin") is None:
        a.groups["storms"] = min(a.groups["storms"], GRADE_SCORE["marginal"])

    if not a.groups:
        return a  # нечего оценивать

    # 3. перенормировка весов на выжившие группы.
    #
    # Для СЧЁТА группа берётся целиком: если из трёх её параметров пришёл один,
    # она всё равно вносит свой вес, просто по тому, что есть.
    # Для ОТЧЁТА (confidence) вес группы уменьшается пропорционально доле
    # пришедших параметров: строка «критериев посчитано» должна говорить,
    # сколько критериев реально отработало, а не сколько групп уцелело —
    # иначе она показывала бы 100%, когда половина параметров группы отсутствует.
    total_w = sum(profile.groups[g].weight for g in a.groups)
    score = sum(profile.groups[g].weight * v for g, v in a.groups.items()) / total_w
    a.confidence = round(sum(
        profile.groups[g].weight * _present_share(a, g, profile) for g in a.groups), 3)
    a.weighted = round(score, 1)

    # 4. лимитирующий фактор — параметр с минимальной субоценкой. Если всё на
    # максимуме, ограничивать нечему — лимит-фактора нет.
    if a.subs and min(a.subs.values()) < GRADE_SCORE["ideal"]:
        lim = min(a.subs, key=lambda k: (a.subs[k], k))
        a.limiting, a.limiting_label = lim, PARAMS[lim].label

    # 5. мультипликативные штрафы
    for rule in PENALTIES:
        if rule.key not in profile.penalties:
            continue
        if any(raw.get(n) is None for n in rule.needs):
            continue
        if rule.test(raw):
            score *= rule.factor
            a.penalties.append(rule.key)

    # 6. потолок по худшей значимой группе (см. LIMIT_CAP_MIN_WEIGHT)
    heavy = [v for g, v in a.groups.items()
             if profile.groups[g].weight >= LIMIT_CAP_MIN_WEIGHT]
    if heavy:
        capped = _cap(score, _one_level_up(_grade_of_score(min(heavy))))
        a.capped = capped < score
        score = capped

    # 7. вето (последними: перекрывают любой балл)
    for rule in VETOES:
        if rule.key not in profile.vetoes:
            continue
        if any(raw.get(n) is None for n in rule.needs):
            a.unchecked_vetoes.append(rule.key)
            continue
        if rule.test(raw):
            a.vetoes.append(rule.key)
    if a.vetoes:
        score = 0.0

    # 8. потолок при неполных данных
    elif a.confidence < MIN_CONFIDENCE:
        score = _cap(score, "fair")
        a.warnings.append("low_confidence")

    a.score = round(score, 1)
    a.category, a.emoji, a.label = category_of(a.score)
    return a


# ---------------------------------------------------------------- свёртка маршрута
# Коэффициент из ТЗ: маршрут — цепь и рвётся по слабому звену, но одна плохая
# точка не должна обнулять хороший день. Величина компромиссная, измерений нет.
BOTTLENECK_WEIGHT = 0.6
TOO_SLOW_MARGIN_MIN = 20.0
# С какого выигрыша в баллах обратный маршрут стоит отдельной строки. Порог
# подобран так, чтобы строка не появлялась на шуме округления; измерений нет.
REVERSE_GAIN = 12.0
# Грозовые вето — те, что говорят о конвекции, а не о рельефе или ветре.
STORM_VETOES = ("cape_extreme", "cape_cin", "lifted_index")
STORM_LOOKAHEAD_KM = 60.0

FEASIBILITY = ("completable", "blocked_at_km", "too_slow", "unknown")


@dataclass
class RouteAssessment:
    score: float | None
    category: str
    emoji: str
    label: str
    feasibility: str                     # см. FEASIBILITY
    bottleneck: dict | None = None       # {"km", "score", "reason"}
    blocked_at_km: float | None = None
    blocked_reason: str | None = None
    flyable_until_km: float | None = None
    mean_score: float | None = None
    confidence: float = 0.0
    warnings: list = field(default_factory=list)


def _goal_margin(points):
    return points[-1]["assessment"].raw.get("time_margin") if points else None


def _flyable_until(points, blocked):
    """Километр последней точки перед первым вето — ради этого вето и не обнуляет
    весь маршрут.

    Опирается на прямую между точками. Фактическая точка разворота зависит от
    того, где найдётся последний рабочий поток, и будет раньше.
    """
    if not points:
        return None
    if blocked is None:
        return points[-1]["km"]
    # сравнение по идентичности, а не через .index: две точки с одинаковым
    # содержимым равны по ==, и километр уехал бы на первую попавшуюся
    i = next(k for k, p in enumerate(points) if p is blocked)
    return points[i - 1]["km"] if i else 0


def score_route(points):
    """Точки маршрута → оценка маршрута.

    `points` — [{"km", "leg_length_km", "assessment"}]. Свёртка намеренно ничего
    не знает о том, откуда взялись оценки: её тестируют на заранее заданных баллах.

    Вето на точке НЕ обнуляет маршрут — оно переводит его в «обрывается на N-м км».
    Пилоту важно знать, что 60 км из 80 проходятся отлично: тогда маршрут
    перекраивают, а не отменяют день.
    """
    blocked = next((p for p in points if p["assessment"].vetoes), None)
    scored = [p for p in points if p["assessment"].score is not None]
    thin = (len(scored) != len(points)
            or any(p["assessment"].confidence < MIN_CONFIDENCE for p in points))

    if not scored:
        return RouteAssessment(None, *NO_DATA, feasibility="unknown",
                               flyable_until_km=_flyable_until(points, blocked))

    worst = min(scored, key=lambda p: p["assessment"].score)
    total = sum(p["leg_length_km"] for p in scored) or 1.0
    mean = sum(p["assessment"].score * p["leg_length_km"] for p in scored) / total
    score = BOTTLENECK_WEIGHT * worst["assessment"].score + (1 - BOTTLENECK_WEIGHT) * mean

    margin = _goal_margin(points)
    if blocked is not None:
        feasibility = "blocked_at_km"
    elif margin is not None and margin < TOO_SLOW_MARGIN_MIN:
        feasibility = "too_slow"
    elif thin:
        feasibility = "unknown"
    else:
        feasibility = "completable"

    cat, emoji, label = category_of(score)
    return RouteAssessment(
        score=round(score, 1), category=cat, emoji=emoji, label=label,
        feasibility=feasibility,
        bottleneck={"km": worst["km"], "score": round(worst["assessment"].score),
                    "reason": worst["assessment"].limiting},
        blocked_at_km=None if blocked is None else blocked["km"],
        blocked_reason=None if blocked is None else blocked["assessment"].vetoes[0],
        flyable_until_km=_flyable_until(points, blocked),
        mean_score=round(mean, 1),
        confidence=round(min(p["assessment"].confidence for p in points), 3))


def storm_ahead(points, lookahead_km=STORM_LOOKAHEAD_KM):
    """Для каждой точки — ближайшая точка ВПЕРЕДИ с грозовым вето, либо None.

    На старте гроза в 60 км — не твоя проблема. На 40-м километре — твоя: ты
    летишь прямо в неё. Поэтому проверка упреждающая, и каждая точка впереди
    берётся в СВОЁ время прилёта, а не в текущее.
    """
    out = []
    for i, p in enumerate(points):
        found = None
        for q in points[i + 1:]:
            if q["km"] - p["km"] > lookahead_km:
                break
            if any(v in STORM_VETOES for v in q["assessment"].vetoes):
                found = {"km": q["km"], "eta": q.get("eta")}
                break
        out.append(found)
    return out


def veto_labels(keys):
    """Ключи вето → русские формулировки (для карточки и промпта)."""
    by_key = {r.key: r.label for r in VETOES}
    return [by_key[k] for k in keys if k in by_key]


def penalty_labels(keys):
    by_key = {r.key: (r.label, r.factor) for r in PENALTIES}
    return [f"{by_key[k][0]} (×{by_key[k][1]:.2f})" for k in keys if k in by_key]


def score_day(date, hours, window):
    """Свернуть почасовые оценки в оценку дня.

    Балл дня — среднее по часам ТЕРМИЧЕСКОГО ОКНА (вне окна склон не греет,
    там никто не стартует). Без окна — среднее по всем переданным часам.
    """
    in_window = hours
    if window:
        in_window = [h for h in hours if window["start_hour"] <= h.hour <= window["end_hour"]] or hours
    scored = [h for h in in_window if h.score is not None]

    d = DayAssessment(date=date, hours=hours, window=window, score=None,
                      category=NO_DATA[0], emoji=NO_DATA[1], label=NO_DATA[2])
    if not scored:
        return d

    d.score = round(sum(h.score for h in scored) / len(scored), 1)
    d.category, d.emoji, d.label = category_of(d.score)
    d.confidence = min(h.confidence for h in scored)

    # лимитирующий фактор дня — самый частый среди часов окна
    lims = [h.limiting for h in scored if h.limiting]
    if lims:
        d.limiting = max(set(lims), key=lims.count)
        d.limiting_label = PARAMS[d.limiting].label

    # Лётные часы считаются ТОЛЬКО внутри термического окна: вне его склон не
    # греет, и спокойный штиль в 06:00 — это ночной сток, а не лётное окно.
    # И карточка, и полоса на метеограмме берут этот список, а не фильтруют
    # часы сами — иначе график рисовал бы окно с рассвета, а текст с 07:00.
    d.fly_hours = sorted(h.hour for h in in_window if flyable(h.category))
    if d.fly_hours:
        d.fly_window = (d.fly_hours[0], d.fly_hours[-1])

    seen = set()
    for h in scored:
        for w in h.warnings:
            if w not in seen:
                seen.add(w)
                d.warnings.append(w)
    d.unchecked_vetoes = sorted({v for h in scored for v in h.unchecked_vetoes})
    d.vetoes_in_window = sorted({v for h in in_window for v in h.vetoes})
    return d


# ---------------------------------------------------------------- презентация
def _interval_text(p, intervals):
    def num(x):
        return p.fmt.format(x).replace("-", "−")   # типографский минус

    parts = []
    for lo, hi in intervals:
        if lo is None:
            parts.append(f"<{num(hi)}")
        elif hi is None:
            parts.append(f"≥{num(lo)}")
        else:
            # у отрицательных диапазонов дефис-разделитель слипается с минусом
            sep = " … " if (lo < 0 or hi < 0) else "–"
            parts.append(f"{num(lo)}{sep}{num(hi)}")
    return " или ".join(parts)


def legend(param_key):
    """[(уровень, текст диапазона)] — для легенд на графиках."""
    p = PARAMS[param_key]
    return [(grade, _interval_text(p, intervals)) for grade, intervals in p.bands]


def reference_text(profile=TAKEOFF):
    """Русский блок порогов для промпта LLM — генерируется из таблицы выше,
    чтобы промпт не мог разойтись с расчётом (раньше он был захардкожен).

    У каждой роли точки свой набор критериев, поэтому и блок свой: описывать
    маршрутной точке критерий направления к склону значит звать модель судить
    по тому, чего в расчёте нет."""
    lines = [
        f"Пороги калиброваны под уверенного XC-пилота на {GLIDER}: trim {TRIM_MS} м/с, "
        f"макс {TOP_MS} м/с. Это НЕ пороги новичка.",
        "Ветер везде в м/с. Уровни: идеально / отлично / удовлетворительно / маргинально / "
        "нелётно / опасно → баллы 100 / 85 / 65 / 40 / 15 / 0.",
        "",
        "ПАРАМЕТРЫ И ДИАПАЗОНЫ:",
    ]
    for gkey, group in profile.groups.items():
        params = [PARAMS[k] for k in profile.group_params(gkey)]
        if not params:
            continue
        lines.append(f"— {group.label} (вес {group.weight:.2f}, свёртка по "
                     f"{'худшему' if group.agg == 'min' else 'среднему'}):")
        for p in params:
            spans = "; ".join(f"{GRADE_LABEL[g]} {_interval_text(p, iv)}" for g, iv in p.bands)
            lines.append(f"   • {p.label}{f' ({p.unit})' if p.unit else ''}: {spans}")
    lines += [
        "",
        "ВЕТО (любое → категория «опасная», балл 0): "
        + "; ".join(r.label for r in VETOES if r.key in profile.vetoes) + ".",
        "ШТРАФЫ (умножают балл): "
        + "; ".join(f"{r.label} ×{r.factor:.2f}"
                    for r in PENALTIES if r.key in profile.penalties) + ".",
        "ПОТОЛОК ПО ЛИМИТ-ФАКТОРУ: итоговый балл не выше, чем на один уровень над худшей "
        "значимой группой — одна нелётная группа не перекрывается девятью хорошими.",
        "КАТЕГОРИИ по баллу: " + " · ".join(f"{lo}+ {emoji} {label}" for _k, lo, emoji, label in CATEGORIES) + ".",
        "",
        "Пропуски: параметр без данных исключён из расчёта, веса перенормированы. "
        "Вето, входы которого неизвестны, НЕ срабатывает и попадает в unchecked_vetoes — "
        "их нужно назвать словами, а не умолчать.",
    ]
    return "\n".join(lines)


def thresholds_note():
    """Короткая строка порогов под карточкой обзора."""
    p = PARAMS["wind_10m"]
    return (f"Пороги ветра у земли: до {p.fmt.format(4.2)} ок · "
            f"{p.fmt.format(7.8)}–{p.fmt.format(9.2)} маргинал · "
            f"от {p.fmt.format(TRIM_MS)} (trim крыла) вето.")


# ---------------------------------------------------------------- целостность
def _check_table():
    """Таблица должна быть непротиворечивой: веса дают 1,0, интервалы каждого
    параметра не пересекаются и покрывают всю ось. Ошибка здесь — опечатка,
    которая иначе молча оставит параметр без оценки."""
    for table, name in ((GROUPS, "GROUPS"), (ROUTE_GROUPS, "ROUTE_GROUPS")):
        w = sum(g.weight for g in table.values())
        assert abs(w - 1.0) < 1e-9, f"сумма весов {name} = {w}, должна быть 1.0"
    known_groups = set(GROUPS) | set(ROUTE_GROUPS)
    for p in PARAMS.values():
        spans = sorted(((lo if lo is not None else float("-inf"),
                         hi if hi is not None else float("inf"))
                        for _g, ivs in p.bands for lo, hi in ivs))
        assert spans[0][0] == float("-inf"), f"{p.key}: нижняя часть оси не покрыта"
        assert spans[-1][1] == float("inf"), f"{p.key}: верхняя часть оси не покрыта"
        for (_lo1, hi1), (lo2, _hi2) in zip(spans, spans[1:]):
            assert hi1 == lo2, f"{p.key}: разрыв или наложение интервалов на {hi1}/{lo2}"
        assert {g for g, _ in p.bands} <= set(GRADES), f"{p.key}: неизвестный уровень"
        assert p.group in known_groups, f"{p.key}: неизвестная группа {p.group}"


_check_table()

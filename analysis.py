"""Weather analysis via Google Gemini.

The LLM's job is ANALYSIS, not fabrication: it receives REAL open-meteo numbers
(extracted by engine.facts_*) and interprets them into a paragliding assessment.
It must not invent numbers.

Two modes — SAME length and structure, differing in DATA and depth of reasoning:
  detail=False (fast button) — full analysis over the site's own forecast.
  detail=True  (deep button) — same, plus a context block (surrounding points +
                               previous day) that it reasons over. Richer, not longer.

If Gemini is unavailable (no key / error), the caller falls back to the
deterministic rule-based text from engine.report_*.

Free tier: Gemini Flash. Key: https://aistudio.google.com/apikey
"""
import json
import logging
import os
import re

from google import genai
from google.genai import types

import criteria

log = logging.getLogger("pgbot.analysis")

# Model chain — tried in order; the first that returns non-empty text wins. Any model
# failure (API error or empty response) falls through to the next; only when all fail
# does the caller fall back to the deterministic rules text.
_DEFAULT_MODELS = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
_client = None


def _model_chain():
    """Models to try, in order. GEMINI_MODELS (comma list) overrides the whole chain;
    a legacy single GEMINI_MODEL (from .env) is tried first, then the defaults as fallback."""
    env = os.getenv("GEMINI_MODELS")
    if env:
        return [m.strip() for m in env.split(",") if m.strip()]
    chain = list(_DEFAULT_MODELS)
    single = os.getenv("GEMINI_MODEL")
    if single:
        chain = [single] + [m for m in chain if m != single]
    return chain


def available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def model_name() -> str:
    return ",".join(_model_chain())


def _get_client():
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY не задан")
        _client = genai.Client(api_key=key)
    return _client


_PREAMBLE = """Ты — опытный метеоролог и парапланерный гид. Тебе дают РЕАЛЬНЫЕ данные прогноза (open-meteo) по конкретному старту в JSON. Проанализируй их.

Жёсткое правило: НЕ придумывай числа. Используй только значения из JSON.

В данных уже есть ДЕТЕРМИНИРОВАННАЯ оценка (assessment, и score/cat/lim у каждого часа): балл 0–100, категория, лимитирующий фактор, сработавшие вето. Она — источник истины.
- Твоя работа: объяснить её пилоту человеческим языком, связать факторы между собой и назвать риски по часам. НЕ пересчитывай балл и НЕ спорь с вето: если час помечен вето, он опасен, точка.
- Лимитирующий фактор перепроверь по числам и, если видишь, что день на деле упирается в другое, скажи об этом прямо — но категорию не меняй.
- unchecked_vetoes — вето, которые проверить НЕ ЧЕМ (модель не дала поля). Это не «всё хорошо», а «неизвестно»: назови их словами в оговорке.
- w_star (сила потоков) — ОЦЕНКА по радиации и глубине слоя, а не измерение; пиши «примерно». foehn_suspect — эвристика по косвенным приметам, а не расчёт фёна.
- Диапазоны T и ветра уже посчитаны за светлое время.

"""

_WINDOW = """
Термическое окно — главное. Летают не «весь световой день», а пока склон греет солнце:
- thermal_window (start_hour / end_hour / peak_hour / solar_noon) уже посчитан по геометрии солнца и экспозиции склона. Разбор, вердикт и риски — ТОЛЬКО про эти часы.
- Часы вне окна (раннее утро, поздний вечер) не комментируй как лётные и не выноси в риски: термички там нет, и никто в это время не стартует. Про утренний/вечерний ветер пиши, только если он прямо влияет на окно (например, усиление уже к 10:00) или если день спасает исключительно динамик/вечерний штиль — и тогда назови это прямо.
- Первые 1–2 часа окна — слабые узкие потоки, к peak_hour — самые мощные и рваные, в последний час окна термичка гаснет (вечерний штиль, ровный воздух — время спокойных полётов).
- Солнце движется: в hourly_daytime есть sun_az_deg (азимут), sun_elev_deg (высота) и slope_sun_index (0–1 — насколько прямо солнце бьёт в склон старта). Индекс падает к концу дня → склон уходит в тень, термичка гаснет раньше заката. Именно так и объясняй вечерний спад: «после HH:00 солнце уходит на запад, южный склон в тени». Если для старта важен утренний/вечерний прогрев — смотри, когда индекс растёт и когда падает.
- Ветер у земли до начала окна — это ночной сток/градиент, а не рабочий бриз; днём его сменяет термический ветер вдоль склона."""

# Вторая граница разбора после окна по времени — граница по высоте. В профиле есть
# уровни 600 и 500 гПа (4–6 км), и без этого правила модель выносила ветер на них в
# риски: «до 18.9 м/с выше 5000 м — избегайте чрезмерного набора». Туда не залетают.
_CEILING = """
Рабочий потолок — граница разбора по высоте. Выше базы облаков и верха рабочего слоя пилот не поднимается:
- Потолок = меньшее из thermal_ceiling_m_msl (верх рабочего слоя) и высоты базы (elevation_m + lcl_m_agl). Если thermal_ceiling_m_msl не дан, считай потолком базу.
- В wind_profile_peak_hour есть уровни выше потолка (600 и 500 гПа — это 4–6 км). Ветер на них не разбирай и в риски НЕ выноси: набрать такую высоту нельзя, и «избегайте набора» там — совет ни о чём. Разбирай ветер только от старта до потолка.
- Верхние уровни используй лишь как признак общего потока — например, подозрение на фён или усиление, которое опустится в рабочий слой к вечеру. Тогда так и скажи, а не «опасный ветер на высоте»."""

# Блок порогов ГЕНЕРИРУЕТСЯ из criteria — раньше он был переписан здесь руками и
# расходился с расчётом при любой правке таблицы, причём молча.
_REFERENCE = _PREAMBLE + criteria.reference_text() + _WINDOW + _CEILING

# Full analysis — used by BOTH the fast and the deep button. They differ in the DATA
# they get (deep adds surrounding points + the previous day) and in the depth of
# reasoning that data unlocks — NOT in length.
_ANALYSIS = _REFERENCE + """

Дай разбор для пилота — по делу, без воды, БЕЗ приветствий и прощаний. Цель ~1100 знаков.
Структура, короткими блоками (каждый 1–3 строки, с эмодзи):
- Вердикт: категория и балл из assessment + суть одной фразой.
- Лётное окно по часам — внутри thermal_window; если часть окна выбивает ветер, вето или дождь, сузь его и скажи почему.
- Что ограничивает: разбери лимитирующий фактор — почему именно он и что должно измениться, чтобы день стал лучше.
- Ветер: сила у земли и как поворачивает направление в окне (в лоб/в спину для экспозиции старта). По высотам — только до рабочего потолка и только если это меняет решение.
- Термичка и потолок — 1–2 фразы: когда включится, когда пик, когда погаснет (со ссылкой на уход солнца со склона).
- Риски с привязкой к часам ВНУТРИ окна (роторы при ветре в спину, рваные порывы на пике, мокрый старт).
Для обзора нескольких дней структура другая: лучший день и почему, нелётные дни и главная причина, по дню — 1 строка (у каждого дня свой thermal_window и свой assessment).
Не пересказывай все числа подряд — приводи только те, что влияют на решение. Без markdown-таблиц. В конце — одна строка-оговорка: высота по гриду, пересними за 1–2 суток, и что осталось непроверенным (unchecked_vetoes), если такое есть."""

# Appended ONLY for the deep button — this is what makes it more valuable than the
# fast one: extra data in facts["context"] and the instruction to reason over it.
_CONTEXT_ADDON = """

В данных есть блок context — это главная ценность подробного разбора, разбери его отдельным блоком «🔄 Контекст»:
- previous_day: тренд воздушной массы и прогрев склона (был ли вчера дождь / сплошная облачность → как это повлияет на сегодняшнюю термичку и сухость старта).
- surrounding_points_daytime: сравни ветер/порывы/осадки в соседних точках (С/Ю/В/З) со стартом — пространственная однородность или локальные аномалии (усиление в секторе, подветренность, сходимость потоков).
Подробный разбор должен отличаться от быстрого именно этими выводами, а не длиной."""


def analyze(facts: dict, rng: str, detail: bool = False) -> str:
    """Return Telegram-ready analysis text. Raises on Gemini failure (caller falls back).

    Both modes produce a full analysis; detail=True additionally reasons over the
    context block (surrounding points + previous day) that the caller merged in.
    """
    guidance = _ANALYSIS + (_CONTEXT_ADDON if detail else "")
    prompt = (
        f"{guidance}\n\n"
        f"Тип запроса: {'один день' if rng == '1d' else 'обзор нескольких дней'}.\n"
        f"Данные (JSON):\n{json.dumps(facts, ensure_ascii=False)}"
    )
    client = _get_client()
    config = types.GenerateContentConfig(temperature=0.3)
    errors = []
    for model in _model_chain():
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=config)
            text = (resp.text or "").strip()
            if not text:
                raise RuntimeError("пустой ответ")
            log.info("gemini ok: %s", model)
            return text
        except Exception as e:  # noqa: BLE001 — any failure → try the next model
            log.warning("gemini model %s failed: %s", model, e)
            errors.append(f"{model}: {e}")
    raise RuntimeError("все модели Gemini недоступны: " + " | ".join(errors))


# ---------------------------------------------------------------- маршрут
# Режим интерпретации: скоринг уже сделан кодом, модель пишет ТОЛЬКО текст.
# Числа у неё не запрашиваются вовсе — значит их нельзя ни переврать, ни
# «поправить», и четыре из шести проверок ответа отпадают вместе с полями.
_ROUTE_PREAMBLE = """Ты — экспертный метео-ассистент для парапланерного кросс-кантри в горах.
Оцениваешь ЗАПЛАНИРОВАННЫЙ МАРШРУТ: набор точек, у каждой своё время прилёта и свой
погодный срез на этот момент.

Всё, что можно вычислить, УЖЕ ВЫЧИСЛЕНО кодом: пеленги, проекции ветра на трек,
расстояния, время прилёта, интерполяция погоды, баллы. Не пересчитывай ничего.
Ты пишешь только текст.

Знаки величин заданы так:
  wind_along_kmh  > 0 попутный, < 0 встречный
  wind_cross_kmh  > 0 сносит вправо от трека, < 0 влево
  time_margin_min > 0 запас до закрытия термического окна в этой точке
  working_band_m  = база облаков − (рельеф + 300 м безопасной высоты)

Роли точек:
  takeoff — старт: важен наземный ветер, порывы и направление склона.
  enroute — в воздухе: наземный ветер и направление склона не применяются.
  goal    — финиш: наземный ветер снова важен (посадка), плюс запас времени.

В блоке computed у каждой точки лежит результат детерминированного скоринга: score,
category, limiting (лимитирующий фактор), vetoes и subs (субоценки 0–100 по каждому
параметру). Это ИСТИНА. Не спорь с ней и не пересчитывай её.
"""

_ROUTE_TASK = """
Верни JSON: comment у точек и три поля summary. Больше ничего — балл, категория,
статус выполнимости и время прилёта уже посчитаны и берутся не от тебя.

comment (1–2 предложения) объясняет, ПОЧЕМУ у точки такой балл, опираясь на limiting
и subs. Не пересказывай числа, которые пилот и так видит в таблице.
Плохо: «Ветер 26 км/ч, база 3230 м, рельеф 2510 м».
Хорошо: «Оценку держит перевал: 420 м рабочего диапазона — это одна попытка на
проход, второй набор сделать негде».

summary.verdict (2–3 предложения) — долечу ли я вообще и почему.
summary.bottleneck_note — где именно рвётся и чем. Нечего сказать — пустая строка.
summary.tactical_note — что делать: сдвинуть вылет, перекроить маршрут, лететь в
обратную сторону. Опирайся на departure_scan и reverse, а не на догадки. Если ни одно
время вылета не даёт completable — скажи это прямо, не предлагай «вылететь раньше».
Данных на совет нет — пустая строка, а не выдумка.

Если в точке заполнено storm_ahead — это предупреждение НА ПОДЛЁТЕ, назови километр и
час, даже если сама точка чистая.

Не выдумывай числа: только те, что есть во входных данных. Не привлекай знания о
регионе, репутации маршрута и сезоне. Без дисклеймеров про «решение за пилотом» — это
делает интерфейс. По-русски, конкретно.
"""

_ROUTE_PROMPT = (_ROUTE_PREAMBLE + criteria.reference_text(criteria.ENROUTE)
                 + _ROUTE_TASK)

# Пустая строка вместо null: часть моделей на типе ["string", "null"] в схеме
# спотыкается, а «пусто» проверяющая сторона всё равно приводит к None.
_ROUTE_SCHEMA = {
    "type": "object",
    "required": ["points", "summary"],
    "properties": {
        "points": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["km", "comment"],
                "properties": {"km": {"type": "number"},
                               "comment": {"type": "string"}},
            },
        },
        "summary": {
            "type": "object",
            "required": ["verdict", "bottleneck_note", "tactical_note"],
            "properties": {"verdict": {"type": "string"},
                           "bottleneck_note": {"type": "string"},
                           "tactical_note": {"type": "string"}},
        },
    },
}


def _loads(text):
    """JSON из ответа модели. Обрамление ```json снимается: часть моделей ставит
    его даже при заданном response_mime_type."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"ответ модели — не JSON: {e}") from None
    if not isinstance(data, dict):
        raise ValueError("ответ модели — не объект")
    return data


def analyze_route(facts: dict) -> dict:
    """Разбор маршрута от Gemini: разобранный JSON. Бросает, если все модели отказали."""
    prompt = (f"{_ROUTE_PROMPT}\n\nДанные (JSON):\n"
              f"{json.dumps(facts, ensure_ascii=False)}")
    client = _get_client()
    config = types.GenerateContentConfig(
        temperature=0.3, response_mime_type="application/json",
        response_schema=_ROUTE_SCHEMA)
    errors = []
    for model in _model_chain():
        try:
            resp = client.models.generate_content(model=model, contents=prompt,
                                                  config=config)
            answer = _loads(resp.text)
            log.info("gemini route ok: %s", model)
            return answer
        except Exception as e:  # noqa: BLE001 — любой отказ → следующая модель
            log.warning("gemini route model %s failed: %s", model, e)
            errors.append(f"{model}: {e}")
    raise RuntimeError("все модели Gemini недоступны: " + " | ".join(errors))


_TAILWIND = re.compile(r"попутн", re.I)
_HEADWIND = re.compile(r"встречн", re.I)
_KM_EPS = 0.05


def check_route_answer(answer, profile):
    """Отсеять то, что модель не имела права прислать → (чистый ответ, коды проблем).

    Чистая функция без сети: её можно и нужно гонять на подложных ответах.

    Из шести проверок промпт-документа здесь живут две. Остальные четыре (число
    точек, bottleneck.km, согласованность feasibility с вето, пересчёт балла)
    отпали вместе с полями: модель их не присылает.

    Знаковую ошибку исходный документ предлагает только залогировать. Здесь
    комментарий выбрасывается: «попутный поможет добить последнее плечо» при
    встречном ветре — это совет, прямо противоположный правильному, в тексте,
    который выглядит абсолютно уверенно.

    Чего проверки НЕ ловят: сводка не привязана к точке, и перевёрнутый знак в
    verdict или tactical_note поймать нечем — «встречный на второй половине»
    бывает верно при попутном на первой.
    """
    by_km = {round(p["km"], 1): p for p in (profile.get("points") or [])}
    flags, clean = [], []
    for item in (answer or {}).get("points") or []:
        try:
            km = round(float(item.get("km")), 1)
        except (TypeError, ValueError):
            flags.append("llm_unknown_km")
            continue
        point = next((p for k, p in by_km.items() if abs(k - km) < _KM_EPS), None)
        if point is None:
            flags.append("llm_unknown_km")
            continue
        text = (item.get("comment") or "").strip()
        if not text:
            continue
        along = point.get("wind_along_kmh")
        if along is not None and ((along < 0 and _TAILWIND.search(text))
                                  or (along > 0 and _HEADWIND.search(text))):
            flags.append("llm_wind_sign_error")
            continue
        clean.append({"km": km, "comment": text})
    clean.sort(key=lambda c: c["km"])
    summary = (answer or {}).get("summary") or {}
    return ({"points": clean,
             "summary": {k: ((summary.get(k) or "").strip() or None)
                         for k in ("verdict", "bottleneck_note", "tactical_note")}},
            flags)

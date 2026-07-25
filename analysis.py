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

from google import genai
from google.genai import types

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


# Shared reference — the paragliding thresholds the model reasons with.
_REFERENCE = """Ты — опытный метеоролог и парапланерный гид. Тебе дают РЕАЛЬНЫЕ данные прогноза (open-meteo) по конкретному старту в JSON. Проанализируй их.

Жёсткое правило: НЕ придумывай числа. Используй только значения из JSON.

Парапланерные ориентиры (ветер в м/с):
- Ветер у земли: ≤5 комфортно, 5–7 маргинально, >7 не летаем. Порывы: тревога >8, явно нет >11. Большой отрыв порыв−ветер = рваный воздух.
- Дождь (precip_mm > 0.2 за день) — нелётный день.
- Направление в рабочее окно сравнивай с экспозицией старта (site.aspect / aspect_deg): в лоб (±80°) — хорошо; в спину (≥110°) — опасно; сбоку — с оговоркой.
- Термичка: cape, инсоляция (sunshine_h), высота пограничного слоя (thermal_ceiling). blue_thermals=true — «голубой» день, потоки без облаков-маркеров.
- Низкий потолок над стартом → слабый набор и XC.
- Диапазоны T и ветра уже посчитаны за светлое время.

Термическое окно — главное. Летают не «весь световой день», а пока склон греет солнце:
- thermal_window (start_hour / end_hour / peak_hour / solar_noon) уже посчитан по геометрии солнца и экспозиции склона. Разбор, вердикт и риски — ТОЛЬКО про эти часы.
- Часы вне окна (раннее утро, поздний вечер) не комментируй как лётные и не выноси в риски: термички там нет, и никто в это время не стартует. Про утренний/вечерний ветер пиши, только если он прямо влияет на окно (например, усиление уже к 10:00) или если день спасает исключительно динамик/вечерний штиль — и тогда назови это прямо.
- Первые 1–2 часа окна — слабые узкие потоки, к peak_hour — самые мощные и рваные, в последний час окна термичка гаснет (вечерний штиль, ровный воздух — время спокойных полётов).
- Солнце движется: в hourly_daytime есть sun_az_deg (азимут), sun_elev_deg (высота) и slope_sun_index (0–1 — насколько прямо солнце бьёт в склон старта). Индекс падает к концу дня → склон уходит в тень, термичка гаснет раньше заката. Именно так и объясняй вечерний спад: «после HH:00 солнце уходит на запад, южный склон в тени». Если для старта важен утренний/вечерний прогрев — смотри, когда индекс растёт и когда падает.
- Ветер у земли до начала окна — это ночной сток/градиент, а не рабочий бриз; днём его сменяет термический ветер вдоль склона."""

# Full analysis — used by BOTH the fast and the deep button. They differ in the DATA
# they get (deep adds surrounding points + the previous day) and in the depth of
# reasoning that data unlocks — NOT in length.
_ANALYSIS = _REFERENCE + """

Дай разбор для пилота — по делу, без воды, БЕЗ приветствий и прощаний. Цель ~1100 знаков.
Структура, короткими блоками (каждый 1–3 строки, с эмодзи):
- Вердикт (✅/⚠️/❌ + суть).
- Лётное окно по часам — внутри thermal_window; если часть окна выбивает ветер или дождь, сузь его и скажи почему.
- Ветер: сила у земли и как поворачивает направление в окне (в лоб/в спину для экспозиции старта). По высотам — если это меняет решение.
- Термичка и потолок — 1–2 фразы: когда включится, когда пик, когда погаснет (со ссылкой на уход солнца со склона).
- Риски с привязкой к часам ВНУТРИ окна (роторы при ветре в спину, рваные порывы на пике, мокрый старт).
Для обзора нескольких дней структура другая: лучший день и почему, нелётные дни и главная причина, по дню — 1 строка (в каждом дне есть свой thermal_window).
Не пересказывай все числа подряд — приводи только те, что влияют на решение. Без markdown-таблиц. В конце — одна строка-оговорка (высота по гриду, пересними за 1–2 суток)."""

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

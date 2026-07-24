"""Weather analysis via Google Gemini.

The LLM's job is ANALYSIS, not fabrication: it receives REAL open-meteo numbers
(extracted by engine.facts_*) and interprets them into a paragliding assessment.
It must not invent numbers.

Two modes:
  detail=False (default) — SHORT interpretation (the factual card is shown
                           separately by the bot, so no need to repeat numbers).
  detail=True            — full, thorough analysis on request.

If Gemini is unavailable (no key / error), the caller falls back to the
deterministic rule-based text from engine.report_*.

Free tier: Gemini Flash. Key: https://aistudio.google.com/apikey
"""
import json
import os

from google import genai
from google.genai import types

_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
_client = None


def available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def model_name() -> str:
    return _MODEL


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
- Диапазоны T и ветра уже посчитаны за светлое время."""

_BRIEF = _REFERENCE + """

Дай КОРОТКИЙ разбор — 2–4 предложения, только интерпретация:
- одна фраза-вердикт (✅/⚠️/❌ + суть),
- лётное окно и главный риск.
Числовую сводку НЕ повторяй (она уже показана пользователю отдельно). Обычный текст с эмодзи, без markdown-таблиц. Для обзора нескольких дней — коротко выдели лучший день и одной строкой почему."""

_DETAIL = _REFERENCE + """

Дай ПОДРОБНЫЙ разбор для пилота: вердикт, лётное окно по часам, ветер и его поворот в течение дня, ветер по высотам (если есть wind_profile), термичку и потолок, конкретные риски (роторы при ветре в спину, рваные порывы, мокрый старт после дождя) с привязкой к часам. Если в данных есть контекст (предыдущий день, точки вокруг старта) — обязательно учти его: тренд воздушной массы, влажность склона, пространственную неоднородность ветра.
Обычный текст с эмодзи, без markdown-таблиц, но развёрнуто. В конце — короткая оговорка: высота старта по гриду, прогноз далеко вперёд (пересними за 1–2 суток)."""


def analyze(facts: dict, rng: str, detail: bool = False) -> str:
    """Return Telegram-ready analysis text. Raises on Gemini failure (caller falls back)."""
    guidance = _DETAIL if detail else _BRIEF
    prompt = (
        f"{guidance}\n\n"
        f"Тип запроса: {'один день' if rng == '1d' else 'обзор нескольких дней'}.\n"
        f"Данные (JSON):\n{json.dumps(facts, ensure_ascii=False)}"
    )
    resp = _get_client().models.generate_content(
        model=_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.3),
    )
    text = (resp.text or "").strip()
    if not text:
        raise RuntimeError("пустой ответ Gemini")
    return text

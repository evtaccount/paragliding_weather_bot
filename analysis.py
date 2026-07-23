"""Weather analysis via Google Gemini.

The LLM's job is ANALYSIS, not fabrication: it receives REAL open-meteo numbers
(extracted by engine.facts_*) and interprets them into a paragliding assessment —
verdict, flyable window, hazards, best day. It must not invent numbers.

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


def _get_client():
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY не задан")
        _client = genai.Client(api_key=key)
    return _client


_GUIDANCE = """Ты — опытный метеоролог и парапланерный гид. Тебе дают РЕАЛЬНЫЕ данные прогноза (open-meteo) по конкретному старту в JSON. Твоя задача — ПРОАНАЛИЗИРОВАТЬ их и дать лётную оценку.

Жёсткое правило: НЕ придумывай числа. Используй только значения из JSON. Если чего-то нет — так и скажи.

Парапланерные ориентиры (ветер в м/с):
- Ветер у земли: ≤5 комфортно, 5–7 маргинально, >7 не летаем. Порывы: тревога >8, явно нет >11. Большой отрыв порыв−ветер = рваный воздух.
- Дождь (precip_mm > 0.2 за день) — нелётный день.
- Направление в рабочее окно сравнивай с экспозицией старта (site.aspect / aspect_deg): в лоб склону (±80°) — хорошо; в спину (≥110°) — опасно; сбоку — с оговоркой.
- Термичка: смотри cape, инсоляцию (sunshine_h) и высоту пограничного слоя (thermal_ceiling). blue_thermals=true — «голубой» день, потоки без облаков-маркеров, читать сложнее.
- Низкий потолок над стартом (thermal_ceiling_m_agl мал) → слабый набор и XC.
- Диапазоны T и ветра уже посчитаны за светлое время (hourly_daytime / days_daytime).

Формат для Telegram: обычный текст с эмодзи, БЕЗ markdown и без таблиц, компактно и по делу.
- Один день: строка-вердикт (✅/⚠️/❌ + суть), лётное окно по часам, ветер/термичка/потолок, риски-оговорки.
- Несколько дней: по строке на день (эмодзи + ключевое) и ОТДЕЛЬНО выдели 🏆 лучший день с обоснованием.
В конце — короткая оговорка: высота старта по гриду, прогноз далеко вперёд (пересними за 1–2 суток)."""


def analyze(facts: dict, rng: str) -> str:
    """Return Telegram-ready analysis text. Raises on Gemini failure (caller falls back)."""
    prompt = (
        f"{_GUIDANCE}\n\n"
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

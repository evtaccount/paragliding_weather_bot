"""analyze() tries the model chain in order, falling through on failure/empty response.

Второй блок — защита от расхождения промпта с расчётом: пороги в промпте должны
ГЕНЕРИРОВАТЬСЯ из criteria, а не быть переписанными руками. Раньше они были
вписаны в _REFERENCE текстом и молча расходились с engine при любой правке.
"""
import pytest

import analysis
import criteria


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, behavior):
        self.behavior = behavior  # model -> text str (or "" empty), or an Exception to raise
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        b = self.behavior.get(model, RuntimeError("not configured"))
        if isinstance(b, Exception):
            raise b
        return _FakeResp(b)


class _FakeClient:
    def __init__(self, behavior):
        self.models = _FakeModels(behavior)


def _patch(monkeypatch, behavior):
    client = _FakeClient(behavior)
    monkeypatch.setattr(analysis, "_get_client", lambda: client)
    monkeypatch.setenv("GEMINI_MODELS", "m1,m2,m3")  # deterministic chain for the test
    return client


def test_first_working_model_wins(monkeypatch):
    client = _patch(monkeypatch, {"m1": RuntimeError("404 not found"), "m2": "РАЗБОР", "m3": "unused"})
    out = analysis.analyze({"x": 1}, "1d")
    assert out == "РАЗБОР"
    assert client.models.calls == ["m1", "m2"]  # stopped at the first success


def test_empty_response_is_a_failure(monkeypatch):
    client = _patch(monkeypatch, {"m1": "", "m2": "ОК", "m3": "unused"})
    out = analysis.analyze({"x": 1}, "1d")
    assert out == "ОК"
    assert client.models.calls == ["m1", "m2"]


def test_all_models_fail_raises(monkeypatch):
    _patch(monkeypatch, {"m1": RuntimeError("a"), "m2": RuntimeError("b"), "m3": RuntimeError("c")})
    with pytest.raises(RuntimeError):
        analysis.analyze({"x": 1}, "1d")


def test_model_chain_env_override(monkeypatch):
    monkeypatch.setenv("GEMINI_MODELS", "x,y")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert analysis._model_chain() == ["x", "y"]


def test_model_chain_legacy_single_first(monkeypatch):
    monkeypatch.delenv("GEMINI_MODELS", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")
    chain = analysis._model_chain()
    assert chain[0] == "gemini-3.5-flash"                 # .env model tried first
    assert len(chain) == len(analysis._DEFAULT_MODELS)    # deduped, defaults follow as fallback


def test_model_chain_default_when_unset(monkeypatch):
    monkeypatch.delenv("GEMINI_MODELS", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert analysis._model_chain() == analysis._DEFAULT_MODELS


# ---------------------------------------------------------------- защита от расхождения
def test_prompt_embeds_the_generated_threshold_block():
    assert criteria.reference_text() in analysis._REFERENCE


def test_prompt_carries_the_real_numbers():
    """Если кто-то снова впишет пороги руками, тест упадёт на первой же правке таблицы."""
    text = analysis._ANALYSIS
    assert str(criteria.TRIM_MS) in text                     # 10.6 — вето по ветру
    assert "1.70" in text or "1.7" in text                   # порог порывистости
    assert f"{criteria.GROUPS['wind'].weight:.2f}" in text   # 0.22 — вес группы ветра
    # Промпт разбирает СТАРТ, поэтому сверяется с вето профиля старта: три
    # маршрутных вето к нему не относятся и в блок порогов не идут.
    for rule in criteria.VETOES:
        if rule.key not in criteria.TAKEOFF.vetoes:
            continue
        assert rule.label in text, f"вето «{rule.label}» пропало из промпта"


def test_prompt_forbids_overriding_the_deterministic_score():
    text = analysis._ANALYSIS
    assert "источник истины" in text
    assert "unchecked_vetoes" in text
    assert "ОЦЕНКА" in text, "W* должен быть назван оценкой, а не измерением"


def test_prompt_does_not_hardcode_the_refresh_hint():
    """Оговорку «пересними за 1–2 суток» решает домен, а не промпт.

    Она печаталась ВСЕГДА, потому что стояла в промпте текстом: пилот открывал
    разбор на сегодня и читал совет переснять прогноз за сутки до вылета,
    который уже наступил. Теперь строка приходит в caveats (engine.day_caveats)
    и только когда срок позволяет — а промпт обязан её пересказывать, а не
    держать свою копию, иначе модель напишет её и на сегодняшнем дне.
    """
    text = analysis._ANALYSIS
    assert "пересними за 1–2 суток" not in text
    assert "caveats" in text


def test_prompt_forbids_risks_above_the_working_ceiling():
    """Без этого правила модель выносила ветер на 500 гПа (5–6 км) в риски дня."""
    text = analysis._REFERENCE
    assert "thermal_ceiling_m_msl" in text
    assert "lcl_m_agl" in text
    assert "wind_profile_peak_hour" in text


def test_analyze_sends_the_reference_block(monkeypatch):
    captured = {}

    class _Models:
        def generate_content(self, model, contents, config):
            captured["prompt"] = contents
            return _FakeResp("ОК")

    class _Client:
        models = _Models()

    monkeypatch.setattr(analysis, "_get_client", lambda: _Client())
    monkeypatch.setenv("GEMINI_MODELS", "m1")
    analysis.analyze({"assessment": {"score": 70}}, "1d")
    assert criteria.reference_text() in captured["prompt"]


def test_reference_text_is_generated_per_profile():
    launch = criteria.reference_text(criteria.TAKEOFF)
    enroute = criteria.reference_text(criteria.ENROUTE)
    assert "направление к склону" in launch
    assert "направление к склону" not in enroute
    assert "ветер вдоль курса" in enroute
    assert f"{criteria.ROUTE_GROUPS['wind_along'].weight:.2f}" in enroute


def test_default_reference_text_is_still_the_launch_one():
    assert criteria.reference_text() == criteria.reference_text(criteria.TAKEOFF)

"""analyze() tries the model chain in order, falling through on failure/empty response."""
import pytest

import analysis


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

"""Маршрутный промпт: пороги генерируются, а не переписываются руками."""
import pytest

import analysis
import criteria


def test_thresholds_come_from_the_tables_not_from_the_prompt():
    """Написанный руками блок порогов уже разъезжался с расчётом молча —
    поэтому он генерируется из criteria."""
    assert criteria.reference_text(criteria.ENROUTE) in analysis._ROUTE_PROMPT


def test_the_prompt_states_the_sign_conventions():
    for token in ("wind_along", "попутн", "встречн", "wind_cross", "time_margin"):
        assert token in analysis._ROUTE_PROMPT


def test_the_prompt_forbids_recomputing():
    assert "computed" in analysis._ROUTE_PROMPT
    assert "пересчит" in analysis._ROUTE_PROMPT.lower()


def test_the_prompt_names_all_three_roles():
    for role in ("takeoff", "enroute", "goal"):
        assert role in analysis._ROUTE_PROMPT


def test_the_schema_asks_only_for_text():
    """Числа модель не присылает — портить нечего."""
    props = analysis._ROUTE_SCHEMA["properties"]
    assert set(props) == {"points", "summary"}
    assert set(props["points"]["items"]["properties"]) == {"km", "comment"}
    assert set(props["summary"]["properties"]) == {
        "verdict", "bottleneck_note", "tactical_note"}


def test_the_schema_has_no_score_or_feasibility():
    text = str(analysis._ROUTE_SCHEMA)
    for forbidden in ("score", "feasibility", "eta", "veto", "category"):
        assert forbidden not in text


def test_answer_json_survives_a_code_fence():
    """Часть моделей всё равно оборачивает JSON в ```json, несмотря на схему."""
    assert analysis._loads('```json\n{"points": []}\n```') == {"points": []}


def test_plain_json_is_read():
    assert analysis._loads('{"points": [{"km": 1}]}')["points"][0]["km"] == 1


def test_a_non_object_answer_is_an_error():
    with pytest.raises(ValueError):
        analysis._loads("[1, 2, 3]")


def test_garbage_is_an_error():
    with pytest.raises(ValueError):
        analysis._loads("это не json")

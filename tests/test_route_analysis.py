"""Проверки ответа модели перед показом пилоту."""
import analysis


def profile():
    return {"points": [
        {"km": 0.0, "wind_along_kmh": 5.2},      # попутный
        {"km": 40.0, "wind_along_kmh": -8.4},    # встречный
        {"km": 78.0, "wind_along_kmh": None},    # знак неизвестен
    ]}


def answer(points, **summary):
    base = {"verdict": "вердикт", "bottleneck_note": "", "tactical_note": ""}
    base.update(summary)
    return {"points": points, "summary": base}


def check(points, **summary):
    return analysis.check_route_answer(answer(points, **summary), profile())


def test_a_clean_answer_passes_through():
    clean, flags = check([{"km": 40.0, "comment": "перевал держит оценку"}])
    assert clean["points"] == [{"km": 40.0, "comment": "перевал держит оценку"}]
    assert flags == []


def test_an_unknown_kilometre_is_dropped():
    """Модель схлопывает соседние точки или добавляет промежуточную."""
    clean, flags = check([{"km": 55.0, "comment": "откуда-то взялась"}])
    assert clean["points"] == []
    assert "llm_unknown_km" in flags


def test_a_non_numeric_kilometre_is_dropped():
    clean, flags = check([{"km": "сорок", "comment": "текст"}])
    assert clean["points"] == []
    assert "llm_unknown_km" in flags


def test_a_tailwind_claim_on_a_headwind_point_is_dropped():
    """Совет, противоположный правильному, опаснее отсутствия совета."""
    clean, flags = check([{"km": 40.0, "comment": "попутный поможет добить плечо"}])
    assert clean["points"] == []
    assert "llm_wind_sign_error" in flags


def test_a_headwind_claim_on_a_tailwind_point_is_dropped():
    clean, flags = check([{"km": 0.0, "comment": "встречный съест скорость"}])
    assert clean["points"] == []
    assert "llm_wind_sign_error" in flags


def test_the_right_sign_survives():
    clean, flags = check([{"km": 40.0, "comment": "встречный съест скорость"},
                          {"km": 0.0, "comment": "попутный помогает"}])
    assert len(clean["points"]) == 2
    assert flags == []


def test_a_point_without_wind_data_is_not_judged():
    """Знак неизвестен — проверять нечем, и выбрасывать текст не за что."""
    clean, flags = check([{"km": 78.0, "comment": "попутный и встречный сразу"}])
    assert len(clean["points"]) == 1
    assert flags == []


def test_one_bad_comment_does_not_take_the_good_ones_with_it():
    clean, _flags = check([{"km": 40.0, "comment": "попутный поможет"},
                           {"km": 0.0, "comment": "старт чистый"}])
    assert [c["km"] for c in clean["points"]] == [0.0]


def test_comments_come_out_sorted_by_kilometre():
    clean, _flags = check([{"km": 40.0, "comment": "второй"},
                           {"km": 0.0, "comment": "первый"}])
    assert [c["km"] for c in clean["points"]] == [0.0, 40.0]


def test_an_empty_comment_is_dropped_quietly():
    clean, flags = check([{"km": 40.0, "comment": "   "}])
    assert clean["points"] == []
    assert flags == []


def test_empty_summary_fields_become_none():
    clean, _flags = check([], bottleneck_note="", tactical_note="  ")
    assert clean["summary"]["bottleneck_note"] is None
    assert clean["summary"]["tactical_note"] is None
    assert clean["summary"]["verdict"] == "вердикт"


def test_a_missing_summary_does_not_crash():
    clean, _flags = analysis.check_route_answer({"points": []}, profile())
    assert clean["summary"]["verdict"] is None


def test_a_missing_points_key_does_not_crash():
    clean, _flags = analysis.check_route_answer({"summary": {}}, profile())
    assert clean["points"] == []


def test_a_capitalised_claim_is_caught_too():
    """Регистр не должен спасать перевёрнутый знак."""
    clean, flags = check([{"km": 40.0, "comment": "Попутный ветер поможет"}])
    assert clean["points"] == []
    assert "llm_wind_sign_error" in flags

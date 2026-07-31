"""report_1day / facts_1day degrade gracefully when the model omits
boundary_layer_height and freezing_level_height (e.g. ECMWF)."""
import os
import tempfile

import engine
from fixtures import om_1day, om_null, site as _site


def _data(**overrides):
    """One complete day. Kept as a thin alias so the sun tests can import it."""
    return om_1day(**overrides)


def _null_data():
    """A ceiling-less model (ECMWF): no boundary layer, no freezing level."""
    return om_null(om_1day(), "boundary_layer_height", "freezing_level_height")


def test_report_1day_full_has_ceiling_and_chart():
    out = tempfile.mkdtemp()
    text, pngs, _card = engine.report_1day(_data(), _site(), out)
    assert "Потолок:" in text and "н/д" not in text
    assert any("ceiling" in os.path.basename(p) for p in pngs)  # 02_ceiling.png present


def test_report_1day_degrades_without_blh():
    out = tempfile.mkdtemp()
    text, pngs, _card = engine.report_1day(_null_data(), _site(), out)
    assert "Потолок: н/д" in text            # no crash, explicit н/д
    assert not any("ceiling" in os.path.basename(p) for p in pngs)  # ceiling chart skipped
    assert any("meteogram" in os.path.basename(p) for p in pngs)    # other charts still there
    assert any("windprofile" in os.path.basename(p) for p in pngs)


def test_facts_1day_nulls_missing_and_reports_model():
    f = engine.facts_1day(_null_data(), _site())
    assert f["thermal_ceiling_m_agl"] is None and f["thermal_ceiling_m_msl"] is None
    assert f["freezing_level_m"] is None
    assert f["site"]["model"]  # model label present


def test_facts_1day_full_keeps_ceiling():
    f = engine.facts_1day(_data(), _site())
    assert f["thermal_ceiling_m_agl"] is not None and f["freezing_level_m"] is not None


# ---------------------------------------------------------------- подпись модели


def test_model_note_reports_borrowed_ceiling():
    """Подпись должна признаваться, что потолок не от выбранной модели: иначе
    ИИ-разбор припишет число ECMWF, который его вообще не считает."""
    data = {"_model_key": "ecmwf", "_ceiling_model": "gfs"}
    assert engine._model_note(data) == "ECMWF (потолок GFS)"


def test_model_note_plain_when_ceiling_is_own():
    assert engine._model_note({"_model_key": "gfs", "_ceiling_model": "gfs"}) == "GFS"


def test_model_note_plain_without_splice():
    """Побочный запрос не удался — штампа нет, оговорки тоже."""
    assert engine._model_note({"_model_key": "ecmwf"}) == "ECMWF"


def test_model_note_falls_back_to_the_default_model():
    """Прямой вызов из CLI и старых тестов: данных без штампа быть не должно,
    но падать на них нельзя."""
    assert engine._model_note({}) == engine.model_label(engine.DEFAULT_MODEL_KEY)

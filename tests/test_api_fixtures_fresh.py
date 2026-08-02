"""Фикстуры фронтенда пересняты после правки домена.

Типы TypeScript и моки экранов описывают ЭТИ файлы. Домен поменял поле, файлы
остались старыми — фронтенд продолжает собираться и зеленеть на устаревшем
контракте, а ломается только в проде, у пилота.

Свежий снимок уходит во ВРЕМЕННЫЙ каталог (--out), а рабочее дерево только
читается. Раньше сторож звал скрипт без каталога — тот переписывал фикстуры на
диске, и сравнение «до» с «после» краснело ровно один раз: второй прогон
подряд, без единой правки, был уже зелёным (воспроизведено дважды: мутация
store `"saved"`→`"saved_at"` и «facts_1day теряет ceiling_model» — финальное
ревью ветки, круг 2, I1). Разработчик, который перезапустил прогон, получал
зелено и пересобранные фикстуры в `git status`, неотличимые от законной части
своей правки.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "webapp" / "test" / "fixtures"
SCRIPT = ROOT / "scripts" / "dump_api_fixtures.py"

# route.json и route_no_terrain.json сняты руками (forecast.get_route с мокнутой
# сетью — см. scripts/dump_api_fixtures.py docstring и task-3-report.md), а не
# этим скриптом: он их не пишет, и сравнивать их со собой же было бы тавтологией,
# а не проверкой.
HAND_COLLECTED = {"route.json", "route_no_terrain.json"}


def _stored() -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in FIX.glob("*.json")}


def test_fixtures_match_what_the_domain_returns_now(tmp_path):
    before = _stored()
    subprocess.run([sys.executable, str(SCRIPT), "--out", str(tmp_path)],
                   capture_output=True, text=True, check=True)
    # Проверка сторожа, а не домена: снятие обязано быть чтением рабочего
    # дерева, иначе первый же красный прогон чинит себя сам (см. docstring).
    assert _stored() == before, (
        "снятие фикстур переписало рабочее дерево — сторож лечит то, что проверяет")

    fresh = {p.name: json.loads(p.read_text(encoding="utf-8"))
             for p in tmp_path.glob("*.json") if p.name not in HAND_COLLECTED}
    stored = {name: json.loads(raw.decode("utf-8"))
              for name, raw in before.items() if name not in HAND_COLLECTED}
    stale = sorted(n for n in fresh if stored.get(n) != fresh[n])
    assert not stale, ("фикстуры устарели, переснимите: "
                       "python scripts/dump_api_fixtures.py — " + ", ".join(stale))

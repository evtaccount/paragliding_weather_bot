"""Фикстуры фронтенда пересняты после правки домена.

Типы TypeScript и моки экранов описывают ЭТИ файлы. Домен поменял поле, файлы
остались старыми — фронтенд продолжает собираться и зеленеть на устаревшем
контракте, а ломается только в проде, у пилота.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "webapp" / "test" / "fixtures"

# route.json и route_no_terrain.json сняты руками (forecast.get_route с мокнутой
# сетью — см. scripts/dump_api_fixtures.py docstring и task-3-report.md), а не
# этим скриптом: он их не пишет, и сравнивать их со собой же было бы тавтологией,
# а не проверкой.
HAND_COLLECTED = {"route.json", "route_no_terrain.json"}


def test_fixtures_match_what_the_domain_returns_now(tmp_path):
    before = {p.name: json.loads(p.read_text(encoding="utf-8"))
              for p in FIX.glob("*.json") if p.name not in HAND_COLLECTED}
    subprocess.run([sys.executable, str(ROOT / "scripts" / "dump_api_fixtures.py")],
                   capture_output=True, text=True, check=True)
    after = {p.name: json.loads(p.read_text(encoding="utf-8"))
             for p in FIX.glob("*.json") if p.name not in HAND_COLLECTED}
    stale = sorted(n for n in after if before.get(n) != after[n])
    assert not stale, ("фикстуры устарели, переснимите: "
                       "python scripts/dump_api_fixtures.py — " + ", ".join(stale))

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


def _stamps() -> dict[str, int]:
    """Моменты последней записи файлов фикстур.

    Факт перезаписи ловится ими, а не сравнением содержимого: при целом домене
    генератор пишет ПОБАЙТОВО ТО ЖЕ САМОЕ, и проверка по содержимому не
    срабатывает вовсе — то есть сторожа над сторожем не существует ровно до
    того дня, когда он понадобится.
    """
    return {p.name: p.stat().st_mtime_ns for p in FIX.glob("*.json")}


def test_fixtures_match_what_the_domain_returns_now(tmp_path):
    before = _stored()
    stamps = _stamps()
    try:
        subprocess.run([sys.executable, str(SCRIPT), "--out", str(tmp_path)],
                       capture_output=True, text=True, check=True)
        touched = sorted(n for n, ns in _stamps().items() if stamps.get(n) != ns)
    finally:
        # Восстановление ОБЯЗАТЕЛЬНО и обязательно в finally: без него первый
        # же красный прогон оставляет на диске пересобранные файлы, второй
        # прогон сравнивает их сами с собой и зеленеет, а `git status`
        # показывает правку, неотличимую от законной. Это и есть тот самый
        # отказ, который проверяет строка ниже, — сторож не должен уметь
        # разоружить себя даже собственным срабатыванием.
        for name, raw in before.items():
            path = FIX / name
            if not path.exists() or path.read_bytes() != raw:
                path.write_bytes(raw)
        for path in FIX.glob("*.json"):
            if path.name not in before:
                path.unlink()

    # Проверка сторожа, а не домена: снятие обязано быть чтением рабочего
    # дерева, иначе первый же красный прогон чинит себя сам (см. docstring).
    assert not touched, (
        "снятие фикстур переписало рабочее дерево — сторож лечит то, что "
        "проверяет: " + ", ".join(touched))

    fresh = {p.name: json.loads(p.read_text(encoding="utf-8"))
             for p in tmp_path.glob("*.json") if p.name not in HAND_COLLECTED}
    stored = {name: json.loads(raw.decode("utf-8"))
              for name, raw in before.items() if name not in HAND_COLLECTED}
    stale = sorted(n for n in fresh if stored.get(n) != fresh[n])
    assert not stale, ("фикстуры устарели, переснимите: "
                       "python scripts/dump_api_fixtures.py — " + ", ".join(stale))


def test_the_snapshot_does_not_depend_on_the_day_it_is_taken(tmp_path):
    """Содержимое фикстур не зависит от того, когда их сняли.

    Часть домена смотрит на сегодняшнюю дату: engine._far_ahead решает, писать
    ли в оговорки «пересними за 1–2 суток», по сроку до дня карточки. Без
    замороженных часов (scripts/dump_api_fixtures._StoppedClock) снимок менялся
    бы сам собой в некоторый день, и сторож выше покраснел бы, ничего про домен
    не сообщая, — а разработчик, переснявший фикстуры «чтобы позеленело»,
    зафиксировал бы в них состояние своего календаря.

    Проверяется наблюдаемым свойством, а не наличием заморозки: часы домена
    подменяются НАРУЖУ скрипта на далёкое будущее, и снимок обязан совпасть
    побайтово со снимком без подмены.
    """
    import datetime as dt
    import os
    from unittest import mock

    # Скрипт на импорте НАВСЕГДА переставляет DB_PATH в окружении процесса (он
    # рассчитан на запуск отдельным процессом), а тесты, перезагружающие store,
    # читают переменную заново — и подхватили бы служебную базу снятия. Значение
    # возвращается сразу после импорта: сам снимок работает на своей базе через
    # подмену store.DB_PATH ниже.
    db_path_before = os.environ.get("DB_PATH")
    sys.path.insert(0, str(ROOT / "scripts"))
    import dump_api_fixtures as dump  # noqa: E402
    if db_path_before is not None:
        os.environ["DB_PATH"] = db_path_before

    import engine

    class _Later:
        timezone = dt.timezone
        datetime = dt.datetime

        class date:
            @staticmethod
            def today():
                return dt.date(2099, 1, 1)

            @staticmethod
            def fromisoformat(s):
                return dt.date.fromisoformat(s)

    import store

    def snapshot(out: pathlib.Path, clock=None) -> None:
        # Своя база на прогон: скрипт заводит старт настоящим store.add_site
        # (иначе sites.json снова стал бы литералом), а второй заход в том же
        # процессе упёрся бы в «старт уже есть».
        with mock.patch.object(store, "DB_PATH", str(out) + ".db"):
            if clock is None:
                dump.main(out)
            else:
                with mock.patch.object(engine, "dt", clock):
                    dump.main(out)

    plain, later = tmp_path / "plain", tmp_path / "later"
    snapshot(plain)
    snapshot(later, _Later)

    differing = sorted(p.name for p in plain.glob("*.json")
                       if p.read_bytes() != (later / p.name).read_bytes())
    assert not differing, (
        "снимок зависит от календаря машины: " + ", ".join(differing))

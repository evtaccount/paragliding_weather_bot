"""Текстовые контракты деплойных файлов.

Caddyfile/Dockerfile/docker-compose.yml/Makefile никто не исполняет в тестах —
их роняет только ручной прогон `docker compose up` или `make check`. Здесь
проверяется то, что видно из текста: комментарий не расходится с кодом,
healthcheck существует и упомянут в обоих файлах, порт driven из одной
переменной, а не трёх независимых копий.
"""
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _dockerfile_instructions() -> list[str]:
    """Инструкции Dockerfile: без комментариев и с раскрытыми переносами строк.

    Поиск подстрок по всему тексту файла проверять раскладку образа не может:
    комментарии в этом же Dockerfile объясняют, зачем нужны `npm ci` и
    `webapp/dist`, поэтому обе подстроки остаются на месте и после удаления
    самих инструкций.
    """
    out: list[str] = []
    for raw in _read("Dockerfile").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if out and out[-1].endswith("\\"):
            out[-1] = out[-1][:-1].rstrip() + " " + line
        else:
            out.append(line)
    return out


def _marked_block(name: str, marker: str) -> str:
    """Кусок шелл-скрипта между строками `# >>> marker` и `# <<< marker`.

    Скрипт целиком в тестах не запустить (создаёт venv и ставит зависимости),
    но отдельная проверка внутри него исполняется за миллисекунды и ничего от
    окружения не требует — её и вырезаем, чтобы проверять ПОВЕДЕНИЕ, а не
    форму записи.

    Границы заданы явными маркерами, а не «от `if` до `fi`»: вырезание по
    ключевым словам снова привязало бы тест к форме — переписывание проверки
    на `[ -f … ] || echo …` роняло бы его при полностью сохранном поведении.
    """
    lines = _read(name).splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f"# >>> {marker}")
    end = next(i for i in range(start, len(lines))
               if lines[i].strip() == f"# <<< {marker}")
    return "\n".join(lines[start + 1:end]) + "\n"


def test_caddyfile_comment_matches_the_directive_it_uses():
    """Комментарий называл handle_path, а код — handle. handle_path срезает
    префикс пути из URL; «починка» кода под комментарий отдавала бы 404 на
    каждый запрос к /api/*. Само слово упоминать можно (контраст поясняет
    выбор) — нельзя приписывать его директиве, которая реально стоит в блоке."""
    text = _read("Caddyfile")
    assert "handle_path для /api/*" not in text
    assert "handle /api/* {" in text


def test_makefile_check_uses_the_project_venv():
    """app.py требует Python 3.11+ (asyncio.TaskGroup). Системный `python3`
    может оказаться старше и падать по причине, не имеющей отношения к
    реальному синтаксису кода."""
    for line in _read("Makefile").splitlines():
        if "py_compile" in line:
            assert ".venv/bin/python" in line, line


def test_dockerfile_declares_a_healthcheck_against_the_api():
    text = _read("Dockerfile")
    assert "HEALTHCHECK" in text
    assert "/api/health" in text


def test_compose_caddy_waits_for_pgbot_to_report_healthy():
    text = _read("docker-compose.yml")
    assert "service_healthy" in text


def test_api_port_is_driven_from_a_single_source():
    """.env.example документирует API_PORT, но compose раньше жёстко прописывал
    8080 в environment — env_file .env его не мог переопределить (позже
    значение в environment: побеждает), и правка .env ничего не меняла."""
    compose = _read("docker-compose.yml")
    caddyfile = _read("Caddyfile")
    assert compose.count("${API_PORT:-8080}") >= 3  # pgbot env, expose, caddy env
    assert "{$API_PORT" in caddyfile


def test_caddyfile_default_port_syntax_has_no_hyphen():
    """Docker Compose пишет умолчания как ${VAR:-default} (с дефисом), у Caddy
    свой синтаксис — {$VAR:default}, БЕЗ дефиса: плейсхолдер режется по
    первому двоеточию, и {$API_PORT:-8080} превращается в литеральную строку
    "-8080". `caddy adapt` на файле без API_PORT в окружении падает:
    'parsing upstream "pgbot:-8080": invalid start port'. Конфиг не
    загружается вообще — ни TLS, ни статика, ни прокси."""
    text = _read("Caddyfile")
    assert "{$API_PORT:-8080}" not in text
    assert "{$API_PORT:8080}" in text


def test_base_caddyfile_leaves_tls_to_caddy():
    """Умолчание — автоматический Let's Encrypt, то есть ОТСУТСТВИЕ директивы
    tls: ключевого слова «выпусти сам» у Caddy нет, автоматика включается
    именно молчанием. Прописанный в базовом файле путь к сертификату означал
    бы, что раскатка без своего сертификата невозможна без правки файла под
    git — а правка под git ломает `git pull` на сервере конфликтом."""
    text = _read("Caddyfile")
    assert "tls /certs/" not in text
    assert "import /etc/caddy/tls/*.caddy" in text


def test_base_compose_does_not_mount_a_certificate_directory():
    """`- ${TLS_CERT_DIR}:/certs:ro` в базовом файле делал переменную
    обязательной: при пустой compose отказывался разбирать том и не поднимал
    вообще ничего. Автоматический режим не должен требовать значений."""
    assert "TLS_CERT_DIR" not in _read("docker-compose.yml")


def test_own_cert_overlay_mounts_the_snippet_and_the_certificates_together():
    """Своему сертификату нужны ДВЕ вещи: директива tls (её вносит сниппет) и
    сами файлы (их вносит том). Порознь они бессмысленны — сниппет без файлов
    роняет Caddy на старте, файлы без сниппета молча уходят в никуда, и Caddy
    выпускает Let's Encrypt, будто своего сертификата нет. Поэтому обе строки
    живут в одном оверлее и включаются одной строкой COMPOSE_FILE."""
    text = _read("docker-compose.own-cert.yml")
    assert "./deploy/caddy/own-cert:/etc/caddy/tls:ro" in text
    assert "${TLS_CERT_DIR}:/certs:ro" in text


def test_own_cert_snippet_points_at_the_path_the_overlay_mounts():
    """Пути внутри сниппета и точка монтирования тома — одно знание в двух
    файлах. Разъедутся — Caddy упадёт на старте с «no such file», уже после
    того, как compose отчитается об успешном запуске."""
    snippet = _read("deploy/caddy/own-cert/tls.caddy")
    overlay = _read("docker-compose.own-cert.yml")
    mount = overlay.split("${TLS_CERT_DIR}:")[1].split(":")[0]
    assert f"tls {mount}/fullchain.pem {mount}/privkey.pem" in snippet


def test_compose_sets_api_host_to_all_interfaces_for_pgbot():
    """app.py по умолчанию слушает 127.0.0.1 (верно для bare metal, см.
    tests/test_app_entry.py). В Docker pgbot и caddy — разные контейнеры с
    разными сетевыми пространствами: loopback внутри pgbot снаружи контейнера
    не виден, и Caddy получил бы ECONNREFUSED (502) на каждый /api/* запрос.
    Это безопасно ТОЛЬКО потому, что pgbot публикует порт через `expose:` без
    `ports:` — границу держит сеть compose, а не бинд. Без этой строки
    пропуск остаётся зелёным: healthcheck стучится в 127.0.0.1 изнутри самого
    контейнера pgbot и не видит, что снаружи (для caddy) порт недостижим —
    так что регрессию тесты app.py/test_app_entry.py не ловят, только этот."""
    text = _read("docker-compose.yml")
    pgbot_block = text.split("\n  caddy:")[0]  # услуги идут по порядку: pgbot, затем caddy
    assert "API_HOST=0.0.0.0" in pgbot_block


def test_image_builds_the_webapp():
    """Собранное приложение попадает в образ отдельным этапом на Node. Без
    этого контейнер поднимется и будет отдавать 500 на корне — молча:
    healthcheck стучится в /api/health, где сборка не нужна, контейнер
    объявляется healthy, caddy стартует и выпускает сертификат, а пилот
    получает ошибку на каждом открытии приложения.

    Проверяются ИНСТРУКЦИИ, а не подстроки в тексте файла: на подстроках тест
    оставался зелёным при удалении одной только строки `COPY --from=webapp`
    (и одной только `RUN npm ci`) — слова находились в комментариях этого же
    Dockerfile."""
    instructions = _dockerfile_instructions()
    stages = [i for i in instructions if i.startswith("FROM ")]
    assert any(i.startswith("FROM node:22") and " AS webapp" in i
               for i in stages), instructions
    assert any(i.startswith("RUN ") and "npm ci" in i for i in instructions), instructions
    assert any(i.startswith("RUN ") and "npm run build" in i
               for i in instructions), instructions
    # источник проверяется наравне с назначением: `COPY --from=webapp /build`
    # вместо `/build/dist` собирает образ без единой ошибки, но index.html
    # уезжает уровнем глубже — каталог на месте, healthcheck 200, / → 404.
    copied = [i for i in instructions
              if i.split()[:2] == ["COPY", "--from=webapp"]
              and i.split()[2:] == ["/build/dist", "./webapp/dist"]]
    assert copied, instructions
    # копирование должно попасть в ФИНАЛЬНЫЙ этап: строка выше последнего FROM
    # собрала бы приложение внутрь самого сборочного этапа и наружу не вынесла.
    assert instructions.index(copied[0]) > instructions.index(stages[-1]), instructions


def test_deploy_script_warns_exactly_when_the_webapp_is_not_built(tmp_path):
    """`deploy.sh` (раскатка без Docker) обязан сказать про `make webapp-build`.

    webapp/dist — артефакт сборки, в git его нет, а npm скрипт не запускает.
    Оператор проходит все шаги, которые скрипт печатает сам, получает рабочий
    чат и 200 на /api/health — и вечные 500 на кнопке Web App, с
    `RuntimeError: StaticFiles directory ... does not exist` в логе и без
    единого намёка, что не хватает сборки. В Docker-раскатке этого отказа нет:
    там сборку делает сам Dockerfile.

    Блок ВЫПОЛНЯЕТСЯ в двух состояниях каталога, а не разбирается как текст.
    Проверки формы записи здесь мало: они одновременно краснеют на безобидном
    переписывании (`[ -f … ] || echo …` вместо `if`) и молчат на потере
    одного символа `!`, которая переворачивает смысл — предупреждение начинает
    печататься ровно тогда, когда сборка есть, а нужному оператору не
    достаётся ничего."""
    block = tmp_path / "block.sh"
    block.write_text(_marked_block("deploy.sh", "webapp-build check"),
                     encoding="utf-8")
    workdir = tmp_path / "checkout"
    workdir.mkdir()

    def run() -> str:
        done = subprocess.run(["bash", str(block)], cwd=workdir,
                              capture_output=True, text=True, check=True)
        return done.stdout

    not_built = run()
    assert "make webapp-build" in not_built, not_built

    (workdir / "webapp" / "dist").mkdir(parents=True)
    (workdir / "webapp" / "dist" / "index.html").write_text("<html>", encoding="utf-8")
    assert run().strip() == "", run()


def test_compose_no_longer_mounts_static_into_caddy():
    """Статику отдаёт pgbot: смонтированный в caddy каталог был вторым путём к
    тому же месту и расходился бы с образом при первой же пересборке."""
    assert "/srv/www" not in _read("docker-compose.yml")


def test_caddy_sends_everything_but_tiles_to_pgbot():
    """Собранное приложение лежит внутри образа pgbot (Dockerfile, этап
    webapp), и отдаёт его сам pgbot — api.py монтирует webapp/dist на "/".
    Оставленная в Caddy отдача файлов означала бы том с тем же каталогом:
    второй путь к тому же артефакту, показывающий старую сборку после первой
    же пересборки образа."""
    text = _read("Caddyfile")
    assert "file_server" not in text
    assert text.count("reverse_proxy pgbot:") >= 1


def test_tiles_are_proxied_through_our_own_domain():
    """Клиент ходит за тайлами только к своему домену: прямые запросы к
    tile.openstreetmap.org показали бы чужому сервису адрес каждого пилота и
    район, куда он смотрит. Ради этого прокси и заводился."""
    text = _read("Caddyfile")
    assert "handle /tiles/*" in text
    assert "tile.openstreetmap.org" in text


def test_tile_proxy_names_the_application_in_user_agent():
    """Правила использования тайлов OpenStreetMap требуют, чтобы клиент себя
    называл. Безымянный поток запросов там блокируют."""
    text = _read("Caddyfile")
    assert "header_up User-Agent" in text


def test_tile_proxy_strips_the_tiles_prefix_before_the_upstream():
    """Клиент шлёт /tiles/{z}/{x}/{y}.png (см. webapp/src/map/MapView.tsx),
    а OpenStreetMap отдаёт тайлы по /{z}/{x}/{y}.png, БЕЗ префикса /tiles —
    канонический шаблон виден в самом Leaflet, уже лежащем в проекте
    (webapp/node_modules/leaflet/src/layer/tile/TileLayer.js). Без явного
    среза наверх уходил бы буквально /tiles/10/637/380.png, и апстрим отвечал
    бы 404 на каждый тайл — карта не показала бы ни одной картинки, при этом
    caddy adapt и все остальные тесты остаются зелёными (они не смотрят,
    что реально доезжает до чужого сервера). Симметрично истории с /api/*
    выше (test_caddyfile_comment_matches_the_directive_it_uses) — там
    handle_path срезал бы префикс, который бэкенду был нужен; здесь handle
    префикс, наоборот, сохраняет, поэтому срез сделан явной директивой uri
    strip_prefix внутри блока, а не сменой handle на handle_path."""
    text = _read("Caddyfile")
    tiles_block = text.split("handle /tiles/*")[1].split("\n\thandle {")[0]
    assert "uri strip_prefix /tiles" in tiles_block

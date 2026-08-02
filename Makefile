# Paragliding forecast bot — dev & deploy tasks.
# Remote deploy needs SERVER (and optionally REMOTE_DIR):
#   make deploy SERVER=user@host

SERVER      ?=
REMOTE_DIR  ?= paragliding-bot
COMPOSE     ?= docker compose
# node_modules — ~106 МБ, которые на сервере всё равно не используются: образ
# ставит зависимости сам (npm ci в этапе webapp), а bare-metal-сборка идёт
# через make webapp-install там же на месте.
RSYNC_EXCL   = --exclude .git --exclude .venv --exclude .env --exclude __pycache__ \
               --exclude node_modules

.DEFAULT_GOAL := help
.PHONY: help install run check test e2e webapp-install webapp-build secrets clean \
        docker-build docker-up docker-down docker-restart docker-logs docker-ps \
        deploy deploy-restart deploy-logs

help:               ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --- local dev ---
install:            ## create venv and install deps
	python3 -m venv .venv && .venv/bin/pip install -U pip -r requirements.txt

run:                ## run bot + API locally (needs .env)
	.venv/bin/python app.py

check:              ## byte-compile all modules (quick syntax check)
	.venv/bin/python -m py_compile *.py && echo "SYNTAX OK"

test:               ## run python + webapp test suites
	.venv/bin/python -m pytest -q
	npm --prefix webapp run test -- --run

# Сквозные сценарии в `test` не входят намеренно: им нужен настоящий браузер,
# запущенный рядом app.py и поход в open-meteo — всего того, чего у обычного
# прогона тестов нет. Подготовка описана в README, раздел «Сквозные сценарии».
#
# Проверка занятости порта стоит ДО запуска ради текста в терминале. Playwright
# на занятом порту советует «set reuseExistingServer: true», а этот совет ровно
# противоположен тому, зачем там false: переиспользованный предпросмотр отдаёт
# вчерашнюю сборку, и восемь сценариев зеленеют, не увидев правки (разбор — в
# webapp/playwright.config.ts). Разработчик читает терминал, а не комментарий в
# конфигурации, поэтому возражение должно быть в терминале.
# Порт продублирован из webapp/playwright.config.ts (PREVIEW_PORT).
# lsof на машине может не оказаться — тогда проверка молча пропускается и
# остаётся прежнее поведение, то есть сообщение самого Playwright.
E2E_PORT ?= 4173

e2e:                ## run end-to-end tests (needs a running app.py and DEV_INIT_DATA)
	@if lsof -ti tcp:$(E2E_PORT) >/dev/null 2>&1; then \
	  echo "порт $(E2E_PORT) занят — погасите свой 'npm run preview' и повторите."; \
	  echo "НЕ ставьте reuseExistingServer: true (это посоветует сам Playwright):"; \
	  echo "тогда сценарии пойдут по СТАРОЙ сборке и не увидят вашей правки."; \
	  exit 1; \
	fi
	npm --prefix webapp run e2e

webapp-install:     ## install webapp dependencies
	npm --prefix webapp ci

webapp-build:       ## build the webapp into webapp/dist
	npm --prefix webapp run build

secrets:            ## create .env from example and lock it down (chmod 600)
	@test -f .env || cp .env.example .env
	@chmod 600 .env
	@echo "edit .env and set BOT_TOKEN"

clean:              ## remove venv and python caches
	rm -rf .venv __pycache__ */__pycache__

# --- docker (local or on the server) ---
docker-build:       ## build the image
	$(COMPOSE) build

docker-up:          ## build and start in the background
	$(COMPOSE) up -d --build

docker-down:        ## stop and remove the stack
	$(COMPOSE) down

docker-restart:     ## restart without rebuild (e.g. after editing sites.json)
	$(COMPOSE) restart

docker-logs:        ## follow container logs
	$(COMPOSE) logs -f

docker-ps:          ## show container status
	$(COMPOSE) ps

# --- remote deploy (set SERVER=user@host) ---
deploy:             ## rsync code to SERVER, then rebuild+start the container
	@test -n "$(SERVER)" || { echo "usage: make deploy SERVER=user@host"; exit 1; }
	rsync -av $(RSYNC_EXCL) ./ $(SERVER):$(REMOTE_DIR)/
	ssh $(SERVER) 'cd $(REMOTE_DIR) && docker compose up -d --build'

deploy-restart:     ## restart the remote container without rebuild
	@test -n "$(SERVER)" || { echo "usage: make deploy-restart SERVER=user@host"; exit 1; }
	ssh $(SERVER) 'cd $(REMOTE_DIR) && docker compose restart'

deploy-logs:        ## follow logs on the remote container
	@test -n "$(SERVER)" || { echo "usage: make deploy-logs SERVER=user@host"; exit 1; }
	ssh $(SERVER) 'cd $(REMOTE_DIR) && docker compose logs -f'

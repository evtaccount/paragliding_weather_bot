# Paragliding forecast bot — dev & deploy tasks.
# Remote deploy needs SERVER (and optionally REMOTE_DIR):
#   make deploy SERVER=user@host

SERVER      ?=
REMOTE_DIR  ?= paragliding-bot
COMPOSE     ?= docker compose
RSYNC_EXCL   = --exclude .git --exclude .venv --exclude .env --exclude __pycache__

.DEFAULT_GOAL := help
.PHONY: help install run check test secrets clean \
        docker-build docker-up docker-down docker-restart docker-logs docker-ps \
        deploy deploy-restart deploy-logs

help:               ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --- local dev ---
install:            ## create venv and install deps
	python3 -m venv .venv && .venv/bin/pip install -U pip -r requirements.txt

run:                ## run the bot locally (needs .env)
	.venv/bin/python bot.py

check:              ## byte-compile all modules (quick syntax check)
	python3 -m py_compile bot.py forecast.py engine.py charts.py && echo "SYNTAX OK"

test:               ## run the dialog test suite (needs requirements-dev.txt installed)
	.venv/bin/python -m pytest -q

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

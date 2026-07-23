.PHONY: install run docker-up docker-down docker-logs

install:            ## create venv and install deps
	python3 -m venv .venv && .venv/bin/pip install -U pip -r requirements.txt

run:                ## run the bot locally (needs .env)
	.venv/bin/python bot.py

docker-up:          ## build and start via docker compose
	docker compose up -d --build

docker-down:        ## stop the compose stack
	docker compose down

docker-logs:        ## follow container logs
	docker compose logs -f

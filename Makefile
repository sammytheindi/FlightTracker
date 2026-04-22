SERVER ?= flight-tracker-server

# ── Local dev ────────────────────────────────────────────────────────────────

install:
	pip install -r requirements.txt
	playwright install chromium

test:
	venv/bin/pytest tests/ -v --tb=short

check-selectors:
	python scripts/check_selectors.py

search:
	python main.py search

matrix:
	python main.py matrix

history:
	python main.py history

watch:
	python main.py watch

# ── Server deployment ────────────────────────────────────────────────────────

deploy:
	ssh $(SERVER) "apt-get update -qq && apt-get install -y -qq docker.io docker-compose-v2 git"
	ssh $(SERVER) "[ -d /app ] && git -C /app pull || git clone https://github.com/sammytheindi/FlightTracker /app"
	scp -r jobs/prod $(SERVER):/app/jobs/prod
	ssh $(SERVER) "cd /app && docker compose up -d --build"

update:
	ssh $(SERVER) "cd /app && git pull && docker compose up -d --build"

push-jobs:
	scp -r jobs/prod $(SERVER):/app/jobs/prod
	ssh $(SERVER) "cd /app && docker compose restart"

logs:
	ssh $(SERVER) "cd /app && docker compose logs -f"

.PHONY: install test check-selectors search matrix history watch deploy update push-jobs logs

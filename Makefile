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

.PHONY: install test check-selectors search matrix history watch

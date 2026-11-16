.PHONY: install check lint format types test pack

install:   ## the development tools (ruff, ty), with uv
	uv sync

check: lint types test   ## everything CI runs

lint:
	uv run ruff check
	uv run ruff format --check

format:
	uv run ruff check --fix
	uv run ruff format

types:
	uv run ty check . plugins/agentic-review/bin/ar-*

test:
	uv run python -m unittest discover -s plugins/agentic-review/tests

pack:   ## dist/agentic-review-<version>.zip
	uv run python scripts/pack.py

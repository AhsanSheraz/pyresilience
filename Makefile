.PHONY: install dev test lint format fix-code typecheck build publish clean docs

install:
	uv pip install .

dev:
	uv pip install -e ".[dev]"

test:
	pytest -v

test-cov:
	pytest -v --cov=pyresilience --cov-branch --cov-report=term-missing --cov-fail-under=95

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

format:
	ruff format src/ tests/

fix-code:
	ruff check --fix src/ tests/
	ruff format src/ tests/

typecheck:
	mypy src/pyresilience

build:
	uv build

publish:
	uv publish

clean:
	rm -rf dist/ build/ *.egg-info src/*.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +

docs:
	mkdocs serve

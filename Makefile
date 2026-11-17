# Agent-friendly entrypoints. On Windows use `python -m cqa ...` directly.
.PHONY: bootstrap build test test-py test-ts lint typecheck contracts docker analyze clean

bootstrap:
	npm ci
	pip install -e ".[dev]"

build:
	npm run build

test: test-py test-ts

test-py:
	pytest

test-ts:
	npm run test:ts

lint:
	ruff check src tests/python
	npm run typecheck

typecheck:
	mypy src/cqa
	npm run typecheck

contracts:
	python -m cqa version --format json > /dev/null

docker:
	docker build -f Dockerfile -t cqa:local .

analyze:
	python -m cqa analyze . --format table --fail-on high

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache packages/*/dist dist

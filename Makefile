.PHONY: help clean test coverage docs servedocs install bump publish release
.DEFAULT_GOAL := help
SHELL := /bin/bash

define BROWSER_PYSCRIPT
import os, webbrowser, sys

from urllib.request import pathname2url

rel_current_path = sys.argv[1]
abs_current_path = os.path.abspath(rel_current_path)
uri = "file://" + pathname2url(abs_current_path)

webbrowser.open(uri)
endef

export BROWSER_PYSCRIPT

define PRINT_HELP_PYSCRIPT
import re, sys

regex_pattern = r'^([a-zA-Z_-]+):.*?## (.*)$$'

for line in sys.stdin:
	match = re.match(regex_pattern, line)
	if match:
		target, help = match.groups()
		print("%-20s %s" % (target, help))
endef

export PRINT_HELP_PYSCRIPT

BROWSER := python3 -c "$$BROWSER_PYSCRIPT"
DO_DOCS_HTML := $(MAKE) -C clean-docs && $(MAKE) -C docs html
SPHINXBUILD   = python3 -msphinx

PACKAGE_NAME = "queuack"
PACKAGE_VERSION := $(shell python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])")

COVERAGE_IGNORE_PATHS = "examples/,tests/,queuack/__init__.py"

help:
	@python -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

clean-build: # remove build artifacts
	rm -fr build/ dist/ .eggs/
	find . -name '*.egg-info' -o -name '*.egg' -exec rm -fr {} +

clean-pyc: # remove Python file artifacts
	find . -name '*.pyc' -o -name '*.pyo' -o -name '*~' -exec rm -rf {} +

clean-test: # remove test and coverage artifacts
	rm -fr .tox/ .coverage coverage.* htmlcov/ .pytest_cache

clean-cache: # remove test and coverage artifacts
	find . -name '*pycache*' -exec rm -rf {} +

clean: clean-build clean-pyc clean-test clean-cache ## remove all build, test, coverage, Python artifacts, cache and docs
	@echo "Cleaned all artifacts! 🧹"

test: ## run tests quickly with the default Python
	PYTHONPATH=$$(pwd) python3 -m pytest
	@echo "Tests completed! ✅"

cov: clean ## check code coverage quickly with the default Python
	uv run pytest --cov=queuack --cov-report=term-missing --durations=10
	@echo "Coverage tests completed! ✅"

watch: ## run tests on watchdog mode
	PYTHONPATH=$$(pwd) ptw queuack tests -- --maxfail=1 -q --disable-warnings

lint: clean ## perform inplace lint fixes
	uv run ruff check --fix .
	@echo "Linting completed! ✅"

format: ## format code with ruff
	uv run ruff format .
	@echo "Code formatted! ✅"

type: clean ## perform type checking
	uv run ty check .
	@echo "Type checking completed! ✅"

check: clean lint type ## run all code quality checks
	make lint
	make type
	@echo "All checks passed! ✅"

env: ## Creates a virtual environment. Usage: make env
	uv venv

show-version: ## Display the current package version
	@echo "Current package version: $(PACKAGE_VERSION)"

what: ## List all commits made since last version bump
	git log --oneline "$$(git rev-list -n 1 "v$$(PACKAGE_VERSION)")..$$(git rev-parse HEAD)"

check-bump: # check if bump version is valid
	@if [ "$(v)" != "patch" ] && [ "$(v)" != "minor" ] && [ "$(v)" != "major" ]; then \
		echo "Invalid version bump '$(v)'. Use 'patch', 'minor', or 'major'.";
		exit 1; \
	fi; \

bump: ## bump version to user-provided {patch|minor|major} semantic
	@$(MAKE) check-bump v=$(v)
	python3 -c "import tomllib, sys, re; data = tomllib.load(open('pyproject.toml', 'rb')); parts = list(map(int, data['project']['version'].split('.'))); idx = {'patch': 2, 'minor': 1, 'major': 0}[sys.argv[1]]; parts[idx] += 1; parts[idx+1:] = [0] * (2 - idx); new_version = '.'.join(map(str, parts)); content = open('pyproject.toml').read(); updated = re.sub(r'version\s*=\s*\"[0-9]+\.[0-9]+\.[0-9]+\"', f'version = \"{new_version}\"', content); open('pyproject.toml', 'w').write(updated)" $(v)
	git add pyproject.toml
	git commit -m "release/ tag v$(PACKAGE_VERSION)"
	git tag "v$(PACKAGE_VERSION)"
	git push
	git push --tags

publish: clean ## build source and publish package
	uv build
	uv publish

release: ## release package on PyPI
	$(MAKE) bump v=$(v)
	$(MAKE) publish

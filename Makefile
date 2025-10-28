.PHONY: help clean test coverage docs servedocs install bump publish release examples
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

test: clean ## run tests quickly with the default Python
	PYTHONPATH=$$(pwd) python3 -m pytest -n auto --dist=loadscope --durations=30 --durations-min=1;
	@echo "Tests completed! ✅"

cov: clean ## check code coverage quickly with the default Python
	# Run coverage with pytest-xdist (if available) and generate XML for CI. Fallback to plain pytest when xdist missing.
	PYTHONPATH=$$(pwd) python3 -m pytest -n auto --dist=loadscope --cov=queuack --cov-report=term-missing --durations=30 --durations-min=1;
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

examples: ## run the examples interactive mode (access all commands)
	PYTHONPATH=$$(pwd) python3 scripts/run_examples.py interactive
	@echo "Examples completed! 🦆"

env: ## Creates a virtual environment. Usage: make env
	uv venv

show-version: ## Display the current package version
	@echo "Current package version: $(PACKAGE_VERSION)"

what: ## List all commits made since last version bump
	git log --oneline "$$(git rev-list -n 1 "v$$(PACKAGE_VERSION)")..$$(git rev-parse HEAD)"

bump: ## bump version to user-provided {patch|minor|major} semantic
	@if [ "$(v)" != "patch" ] && [ "$(v)" != "minor" ] && [ "$(v)" != "major" ]; then \
		echo "Invalid version bump '$(v)'. Use 'patch', 'minor', or 'major'."; \
		exit 1; \
	fi; \
	python3 -c "import tomllib, sys, re; data = tomllib.load(open('pyproject.toml', 'rb')); parts = list(map(int, data['project']['version'].split('.'))); idx = {'patch': 2, 'minor': 1, 'major': 0}[sys.argv[1]]; parts[idx] += 1; parts[idx+1:] = [0] * (2 - idx); new_version = '.'.join(map(str, parts)); content = open('pyproject.toml').read(); updated = re.sub(r'version\s*=\s*\"[0-9]+\.[0-9]+\.[0-9]+\"', f'version = \"{new_version}\"', content); open('pyproject.toml', 'w').write(updated)" $(v)
	@echo "Bumped version to $(PACKAGE_VERSION)! 🎉"

gen-release-notes: ## generate release notes for current version using AI
	PYTHONPATH=$$(pwd) python3 scripts/generate_release_notes_ai.py --version "$(PACKAGE_VERSION)" --range "$(git rev-list -n 1 "v$(PACKAGE_VERSION)")..$(git rev-parse HEAD)"
	@echo "Generated release notes for version $(PACKAGE_VERSION)! 📝"

tag: ## create git tag for current version
	git add pyproject.toml
	git commit -m "release: tag v$(PACKAGE_VERSION)"
	git tag -a "v$(PACKAGE_VERSION)" -f "RELEASE_NOTES/v$(PACKAGE_VERSION).md"	
	git push
	git push --tags
	@echo "Created git tag v$(PACKAGE_VERSION)! 🏷️"

pre-release: bump gen-release-notes tag ## prepare a new release
	@echo "Pre-release steps completed for version $(PACKAGE_VERSION)! 🚀"

release: ## release package on PyPI
	gh workflow run release.yml -ref main --field publish=true 
	@echo "Released version $(PACKAGE_VERSION) to PyPI! 🚀"

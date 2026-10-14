PY ?= python
MMDC ?=

.PHONY: help install lint test cov audit baselines docs docs-check diagrams report mock-e2e check clean docker

help:
	@echo "targets: install lint test cov audit baselines docs docs-check diagrams report mock-e2e check clean docker"

install:
	$(PY) -m pip install -e ".[dev]"

lint:
	ruff check .

test:
	$(PY) -m pytest -q

cov:
	$(PY) -m pytest -q --cov --cov-report=term --cov-fail-under=90

audit:
	trialgauntlet audit

baselines:
	bash scripts/regenerate_results.sh

docs:
	$(PY) -m trialgauntlet.docgen

docs-check:
	$(PY) -m trialgauntlet.docgen --check

diagrams:
	MMDC="$(MMDC)" bash scripts/render_diagrams.sh

report:
	trialgauntlet report results --out-dir report

mock-e2e:
	bash scripts/mock_e2e.sh

check: lint cov docs-check

clean:
	rm -rf .pytest_cache .ruff_cache .coverage coverage.xml htmlcov build dist src/*.egg-info report runs
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

docker:
	docker build -t trialgauntlet .

.PHONY: install-all test lint run-verify run-explore clean fmt

PY := python3
PIP := pip
ROOT := $(CURDIR)
GAIA_ROOT ?= /path/to/Gaia
DZ_HYPERGRAPH_ROOT ?=

install-all:
	$(PIP) install -e $(GAIA_ROOT)
	@if [ -n "$(DZ_HYPERGRAPH_ROOT)" ]; then $(PIP) install -e "$(DZ_HYPERGRAPH_ROOT)"; fi
	$(PIP) install -e $(ROOT)[dev]

test:
	cd $(ROOT) && $(PY) -m pytest -q

test-unit:
	cd $(ROOT) && $(PY) -m pytest -q -m "not e2e and not claude_cli and not llm and not lean"

test-e2e:
	cd $(ROOT) && $(PY) -m pytest -q -m e2e

lint:
	cd $(ROOT) && ruff check src tests

fmt:
	cd $(ROOT) && ruff format src tests

run-verify:
	cd $(ROOT) && $(PY) -m gd.cli verify-server --port 8092

run-explore:
	@echo "用法: cd projects/<problem_id> && gd explore --max-iter 8"

doctor:
	cd $(ROOT) && $(PY) -m gd.cli doctor

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf build dist *.egg-info

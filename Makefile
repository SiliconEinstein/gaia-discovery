.PHONY: install-all test test-unit test-e2e lint fmt run-verify doctor clean

PY := python3
PIP := pip
ROOT := /root/gaia-discovery

install-all:
	$(PIP) install -e /root/Gaia
	$(PIP) install -e /root/gaia-discovery/packages/dz-hypergraph
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

doctor:
	cd $(ROOT) && $(PY) -m gd.cli doctor

# Note: there is no `gd explore` CLI command. The main agent runs the
# §4 Procedure in AGENTS.md by walking gd inquiry / dispatch / run-cycle
# itself. To trigger a session interactively, use the /gaia:explore slash
# command (see commands/gaia-explore.md).

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf build dist *.egg-info

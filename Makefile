SHELL := /bin/bash
PYTHON := python
ENVLOAD := source envloader &&

.PHONY: lint fmt test coverage ui env

lint:
	$(ENVLOAD) ruff check .

fmt:
	$(ENVLOAD) black .

test:
	$(ENVLOAD) pytest

coverage:
	$(ENVLOAD) pytest --cov=elo_app --cov=tests --cov-report=term-missing --cov-fail-under=100

ui:
	$(ENVLOAD) streamlit run elo_app/ui/streamlit_app.py

env:
	$(ENVLOAD) $(PYTHON) -V

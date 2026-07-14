.PHONY: schema ingest cluster knowledge materialize fdc-import flow check test test-int lint
schema:
	python -m nutriscrape schema
flow:
	python -m nutriscrape.orchestration.flows
fdc-import:
	python -m nutriscrape fdc-import
ingest:
	python -m nutriscrape ingest
cluster:
	python -m nutriscrape cluster
knowledge:
	python -m nutriscrape knowledge
materialize:
	python -m nutriscrape materialize
lint:
	ruff check src && mypy src
test:
	pytest tests/unit tests/clinical
test-int:
	pytest tests/integration
check: lint test

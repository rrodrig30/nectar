.PHONY: schema ingest cluster knowledge materialize check test test-int lint
schema:
	python -m nutriscrape schema
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

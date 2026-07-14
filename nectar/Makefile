.PHONY: api web check test test-int lint
api:
	uvicorn nectar.api.app:app --reload --port 8000
web:
	cd web && npm run dev
lint:
	ruff check src && mypy src
test:
	pytest tests/unit tests/clinical
test-int:
	pytest tests/integration
check: lint test

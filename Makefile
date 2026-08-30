.PHONY: help install db-up db-down db-logs db-shell migrate run test lint fmt clean

help:
	@echo "Retryable - developer commands"
	@echo ""
	@echo "  make install   install python dependencies"
	@echo "  make db-up     start postgres and block until it is healthy"
	@echo "  make db-down   stop postgres (data is preserved in the volume)"
	@echo "  make db-shell  open a psql prompt against the running database"
	@echo "  make migrate   apply alembic migrations up to head"
	@echo "  make run       run the API server on :8000"
	@echo "  make test      run the test suite"
	@echo "  make lint      lint and format check"
	@echo ""
	@echo "  make demo / make eval are added in Stage 6."

install:
	pip install -r requirements.txt

db-up:
	docker compose up -d db
	@echo "waiting for postgres to accept connections..."
	@until docker compose exec -T db pg_isready -U retryable -d retryable > /dev/null 2>&1; do sleep 1; done
	@echo "postgres ready on localhost:5432"

db-down:
	docker compose down

db-logs:
	docker compose logs -f db

db-shell:
	docker compose exec db psql -U retryable -d retryable

migrate:
	alembic upgrade head

run:
	uvicorn src.api.main:app --reload --port 8000

test:
	pytest -q

lint:
	ruff check src tests
	ruff format --check src tests

fmt:
	ruff format src tests

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +

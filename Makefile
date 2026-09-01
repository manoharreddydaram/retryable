.PHONY: help install web-install db-up db-down db-logs db-shell migrate run web test lint fmt clean dispatch verify-razorpay eval diagnose detect

help:
	@echo "Retryable - developer commands"
	@echo ""
	@echo "  make install          install python dependencies"
	@echo "  make web-install      install frontend dependencies (web/)"
	@echo "  make db-up            start postgres and block until it is healthy"
	@echo "  make db-down          stop postgres (data is preserved in the volume)"
	@echo "  make db-shell         open a psql prompt against the running database"
	@echo "  make migrate          apply alembic migrations up to head"
	@echo "  make run              run the API server on :8000"
	@echo "  make web              run the UI dev server on :5173 (needs make run alongside)"
	@echo "  make dispatch         run the outbox dispatcher once"
	@echo "  make diagnose         run the long-tail LLM diagnosis pass once"
	@echo "  make detect           run the statistical degradation detector once"
	@echo "  make verify-razorpay  one-off check that real .env credentials actually work"
	@echo "  make eval             run the evaluation harness against the real Razorpay API"
	@echo "  make test             run the test suite"
	@echo "  make lint             lint and format check"
	@echo ""
	@echo "  make demo is added in Stage 10."

install:
	pip install -r requirements.txt

web-install:
	cd web && npm install

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

dispatch:
	python scripts/run_dispatcher.py

diagnose:
	python scripts/run_diagnose.py

detect:
	python scripts/run_detect.py

verify-razorpay:
	python scripts/verify_razorpay_connection.py

eval:
	python -m eval.run_eval

run:
	uvicorn src.api.main:app --reload --port 8000

web:
	cd web && npm run dev

test:
	pytest -q

lint:
	ruff check src tests migrations scripts eval
	ruff format --check src tests migrations scripts eval

fmt:
	ruff format src tests migrations scripts eval

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +

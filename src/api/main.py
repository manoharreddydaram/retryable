"""FastAPI application entrypoint."""

from fastapi import FastAPI

from src.api.webhooks import router as webhooks_router

app = FastAPI(
    title="Retryable",
    description="Payment failure triage and bounded recovery engine.",
    version="0.1.0",
)

app.include_router(webhooks_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe. Does not touch the database."""
    return {"status": "ok", "service": "retryable", "stage": "2"}

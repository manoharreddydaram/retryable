"""FastAPI application entrypoint.

Stage 0: a health endpoint only, so that `make run` is verifiable from the
first commit onward. Routes are added from Stage 2.
"""

from fastapi import FastAPI

app = FastAPI(
    title="Retryable",
    description="Payment failure triage and bounded recovery engine.",
    version="0.1.0",
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe. Does not touch the database."""
    return {"status": "ok", "service": "retryable", "stage": "0"}

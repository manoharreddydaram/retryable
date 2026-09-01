"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.decisions import router as decisions_router
from src.api.ledger import router as ledger_router
from src.api.results import router as results_router
from src.api.triage import router as triage_router
from src.api.webhooks import router as webhooks_router

app = FastAPI(
    title="Retryable",
    description="Payment failure triage and bounded recovery engine.",
    version="0.1.0",
)

# The Stage 9 UI is a separate Vite dev server (localhost:5173) calling this
# API (localhost:8000) -- restricted to localhost dev origins, and to GET,
# since every Stage 9 route only ever reads. This project runs on a
# developer's or judge's own machine, never anywhere CORS needs to be wider.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(webhooks_router)
app.include_router(triage_router)
app.include_router(decisions_router)
app.include_router(ledger_router)
app.include_router(results_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe. Does not touch the database."""
    return {"status": "ok", "service": "retryable", "stage": "9"}

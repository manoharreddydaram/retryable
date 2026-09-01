"""GET /api/results/latest -- serves the committed eval harness output
(eval/results/latest_run.json) as-is. This endpoint never runs an
evaluation itself -- only `make eval` does that, and only on request -- so
loading the Results screen can never silently spend against the real
Razorpay test-mode API.
"""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.api.schemas import EvalResultsResponse

router = APIRouter()

_RESULTS_PATH = (
    Path(__file__).resolve().parent.parent.parent / "eval" / "results" / "latest_run.json"
)


@router.get("/api/results/latest", response_model=EvalResultsResponse)
def get_latest_results() -> EvalResultsResponse:
    if not _RESULTS_PATH.exists():
        raise HTTPException(status_code=404, detail="no_eval_results_yet")
    raw = json.loads(_RESULTS_PATH.read_text(encoding="utf-8"))
    return EvalResultsResponse.model_validate(raw)

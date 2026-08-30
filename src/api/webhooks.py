"""The Razorpay webhook endpoint.

Signature verification happens before anything else touches the body -- an
unverified payload isn't trusted enough to even parse. Razorpay retries any
delivery that doesn't get a 2xx within 5 seconds, for up to 24 hours, so
duplicate and out-of-order delivery are documented, expected behaviour here,
not edge cases to shrug off.
"""

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from src.config import get_settings
from src.db.base import get_db
from src.ingest.service import ingest_webhook
from src.ingest.signature import verify_signature
from src.ledger.writer import append_entry

router = APIRouter()


@router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(default=""),
    x_razorpay_event_id: str = Header(default=""),
    session: Session = Depends(get_db),  # noqa: B008 -- this is FastAPI's DI mechanism, not a mutable default
) -> dict:
    raw_body = await request.body()
    settings = get_settings()

    if not verify_signature(raw_body, x_razorpay_signature, settings.razorpay_webhook_secret):
        append_entry(
            session,
            entity_type="webhook",
            entity_id="unknown",
            event_type="webhook.signature_invalid",
            actor="system:ingest",
            payload={
                "body_length": len(raw_body),
                "had_signature_header": bool(x_razorpay_signature),
            },
        )
        session.commit()
        raise HTTPException(status_code=400, detail="invalid_signature")

    if not x_razorpay_event_id:
        raise HTTPException(status_code=400, detail="missing_event_id_header")

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc

    result = ingest_webhook(session, event_id=x_razorpay_event_id, raw_body=body)
    session.commit()

    return {"status": "ok", "outcome": result.outcome}

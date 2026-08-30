"""Canonical serialisation and hashing for the ledger's hash chain.

Every entry's hash covers its own fields plus the previous entry's hash, so
changing any field of any past entry — or reordering, or deleting one — breaks
the chain from that point forward. `verify_chain()` in `verify.py` walks the
table and recomputes every hash to prove (or disprove) that nothing moved.
"""

import hashlib
import json
from datetime import datetime
from typing import Any

GENESIS_HASH = "0" * 64


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"not JSON serialisable in a ledger entry: {type(value)!r}")


def canonical_json(fields: dict[str, Any]) -> bytes:
    """Deterministic byte encoding: sorted keys, no incidental whitespace."""
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), default=_json_default).encode(
        "utf-8"
    )


def compute_hash(prev_hash: str, fields: dict[str, Any]) -> str:
    return hashlib.sha256(prev_hash.encode("utf-8") + canonical_json(fields)).hexdigest()

"""Pure unit tests for the hash function. No database involved."""

from datetime import UTC, datetime

from src.ledger.hashing import GENESIS_HASH, canonical_json, compute_hash


def _fields() -> dict:
    return {
        "entity_type": "payment",
        "entity_id": "pay_test123",
        "event_type": "payment.failed",
        "actor": "system",
        "payload": {"reason": "insufficient_funds"},
        "created_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
    }


def test_canonical_json_is_stable_under_key_order() -> None:
    a = {"b": 1, "a": 2}
    b = {"a": 2, "b": 1}
    assert canonical_json(a) == canonical_json(b)


def test_compute_hash_is_deterministic() -> None:
    fields = _fields()
    assert compute_hash(GENESIS_HASH, fields) == compute_hash(GENESIS_HASH, fields)


def test_compute_hash_changes_with_prev_hash() -> None:
    fields = _fields()
    first = compute_hash(GENESIS_HASH, fields)
    second = compute_hash("a" * 64, fields)
    assert first != second


def test_compute_hash_changes_when_payload_changes() -> None:
    fields = _fields()
    original = compute_hash(GENESIS_HASH, fields)

    tampered = dict(fields)
    tampered["payload"] = {"reason": "card_blocked"}
    assert compute_hash(GENESIS_HASH, tampered) != original

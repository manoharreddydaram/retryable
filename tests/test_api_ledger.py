"""Tests for GET /api/ledger and GET /api/ledger/verify."""

from src.ledger.writer import append_entry


def test_ledger_lists_entries_newest_first(api_client, db_session) -> None:
    append_entry(
        db_session,
        entity_type="payment",
        entity_id="stage9_p1",
        event_type="test.one",
        actor="system:test",
        payload={},
    )
    append_entry(
        db_session,
        entity_type="payment",
        entity_id="stage9_p2",
        event_type="test.two",
        actor="system:test",
        payload={},
    )

    response = api_client.get("/api/ledger", params={"limit": 2})
    entries = response.json()["entries"]

    assert response.status_code == 200
    assert len(entries) == 2
    assert entries[0]["seq"] > entries[1]["seq"]


def test_ledger_pagination_cursor_moves_backward(api_client, db_session) -> None:
    for i in range(3):
        append_entry(
            db_session,
            entity_type="payment",
            entity_id=f"stage9_page_{i}",
            event_type="test.paged",
            actor="system:test",
            payload={"i": i},
        )

    first_page = api_client.get("/api/ledger", params={"limit": 1}).json()
    assert len(first_page["entries"]) == 1
    assert first_page["next_before_seq"] == first_page["entries"][0]["seq"]

    second_page = api_client.get(
        "/api/ledger", params={"limit": 1, "before_seq": first_page["next_before_seq"]}
    ).json()
    assert second_page["entries"][0]["seq"] < first_page["entries"][0]["seq"]


def test_ledger_verify_reports_the_chain_as_valid(api_client, db_session) -> None:
    append_entry(
        db_session,
        entity_type="payment",
        entity_id="stage9_v1",
        event_type="test.verify",
        actor="system:test",
        payload={},
    )

    response = api_client.get("/api/ledger/verify")
    body = response.json()

    assert response.status_code == 200
    assert body["valid"] is True
    assert body["first_broken_seq"] is None

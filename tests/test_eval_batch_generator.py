"""Pure tests for the synthetic batch generator. No database."""

from eval.batch_generator import generate_batch, split_arms
from src.classify.taxonomy import FailureCategory
from src.ingest.schemas import RazorpayWebhookEnvelope


def test_batch_has_the_requested_size() -> None:
    assert len(generate_batch(50, seed=1)) == 50


def test_same_seed_produces_an_identical_batch() -> None:
    first = generate_batch(30, seed=7)
    second = generate_batch(30, seed=7)
    assert [f.order_id for f in first] == [f.order_id for f in second]
    assert [f.true_category for f in first] == [f.true_category for f in second]
    assert [f.amount_paise for f in first] == [f.amount_paise for f in second]


def test_different_seeds_produce_different_batches() -> None:
    first = generate_batch(30, seed=1)
    second = generate_batch(30, seed=2)
    assert [f.true_category for f in first] != [f.true_category for f in second]


def test_every_taxonomy_category_can_appear_in_a_large_batch() -> None:
    batch = generate_batch(500, seed=3)
    seen = {f.true_category for f in batch}
    assert seen == {c.value for c in FailureCategory}


def test_amounts_are_within_the_clamped_band() -> None:
    for f in generate_batch(200, seed=4):
        assert 9_900 <= f.amount_paise <= 1_500_000


def test_some_payers_repeat_within_a_batch() -> None:
    contacts = [f.payer_contact for f in generate_batch(200, seed=5, repeat_payer_rate=0.5)]
    assert len(set(contacts)) < len(contacts)


def test_zero_repeat_rate_gives_all_unique_payers() -> None:
    contacts = [f.payer_contact for f in generate_batch(50, seed=6, repeat_payer_rate=0.0)]
    assert len(set(contacts)) == len(contacts)


def test_split_arms_respects_the_treatment_share() -> None:
    batch = generate_batch(1000, seed=8)
    treatment, control = split_arms(batch, seed=8, treatment_share=0.7)
    assert len(treatment) + len(control) == len(batch)
    assert abs(len(treatment) / len(batch) - 0.7) < 0.02


def test_split_arms_is_reproducible() -> None:
    batch = generate_batch(100, seed=9)
    t1, c1 = split_arms(batch, seed=9)
    t2, c2 = split_arms(batch, seed=9)
    assert [f.order_id for f in t1] == [f.order_id for f in t2]
    assert [f.order_id for f in c1] == [f.order_id for f in c2]


def test_webhook_envelope_round_trips_through_the_real_schema() -> None:
    failure = generate_batch(1, seed=10)[0]
    envelope = RazorpayWebhookEnvelope.model_validate(failure.to_webhook_envelope())
    entity = envelope.payment_entity()
    assert entity is not None
    assert entity.id == failure.payment_id
    assert entity.amount == failure.amount_paise
    assert entity.error_reason == failure.error_reason

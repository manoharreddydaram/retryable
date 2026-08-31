"""Pure tests for the prompt template loader/renderer. No database."""

from src.classify.taxonomy import FailureCategory
from src.diagnose.evidence import EvidenceBundle, EvidenceItem
from src.diagnose.prompts import prompt_hash, render_prompt
from src.policy.catalog import Intervention

_BUNDLE = EvidenceBundle(items=[EvidenceItem("E1", "a very specific evidence string")])


def test_prompt_hash_is_stable_across_calls() -> None:
    assert prompt_hash() == prompt_hash()


def test_prompt_hash_is_a_sha256_hex_digest() -> None:
    digest = prompt_hash()
    assert len(digest) == 64
    int(digest, 16)  # raises ValueError if not valid hex


def test_rendered_prompt_includes_every_real_category() -> None:
    rendered = render_prompt(_BUNDLE)
    for category in FailureCategory:
        assert category.value in rendered


def test_rendered_prompt_includes_every_real_intervention() -> None:
    rendered = render_prompt(_BUNDLE)
    for intervention in Intervention:
        assert intervention.value in rendered


def test_rendered_prompt_includes_the_evidence() -> None:
    rendered = render_prompt(_BUNDLE)
    assert "[E1] a very specific evidence string" in rendered

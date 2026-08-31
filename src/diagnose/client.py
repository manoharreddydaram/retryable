"""Calls Claude to diagnose one long-tail payment failure.

Any failure -- network, malformed output, a hallucinated citation -- raises
DiagnosisFailed rather than propagating. The caller (service.py) treats
that exactly like the deterministic classifier returning UNKNOWN with
confidence 0.0: the system degrades to the deterministic path, never to
nothing.

CLAUDE.md's original design called for temperature 0, written before this
model generation existed. Verified directly against the installed SDK
(anthropic 1.2.0): `messages.parse()`'s signature has no temperature
parameter at all on Claude Opus 5 -- it and the other current-generation
models replaced manual sampling controls with adaptive thinking, and
passing temperature is rejected outright, not merely ignored. This
project's actual determinism guarantees live elsewhere and don't depend on
it: category and suggested_intervention are schema-constrained to the real
enums (the model cannot name a value that doesn't exist), the policy engine
handles whatever comes back with 100% deterministic logic regardless of the
LLM's exact wording, and every call -- success or failure -- is durably
recorded with its full evidence bundle and prompt hash. The one thing that
was never going to be bit-for-bit reproducible is the model's prose, and
temperature 0 on the old API only ever reduced that variance, never
eliminated it.
"""

import anthropic

from src.config import Settings
from src.diagnose.evidence import EvidenceBundle
from src.diagnose.prompts import prompt_hash, render_prompt
from src.diagnose.schemas import DiagnosisOutput

_MAX_TOKENS = 1024


class DiagnosisFailed(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def call_llm(
    bundle: EvidenceBundle, settings: Settings, client: anthropic.Anthropic | None = None
) -> tuple[DiagnosisOutput, str, dict]:
    """Returns (parsed output, the prompt_hash used, raw response as a dict).
    Raises DiagnosisFailed on any failure -- never returns a partial or
    best-effort result.

    client is injectable so tests can pass one built on a mocked transport
    (httpx2.MockTransport) instead of hitting the real API -- the same
    pattern src/execute/razorpay_client.py uses for the same reason."""
    if not settings.anthropic_api_key:
        raise DiagnosisFailed("no_api_key")

    prompt_text = render_prompt(bundle)
    client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)

    try:
        response = client.messages.parse(
            model=settings.anthropic_model,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt_text}],
            output_format=DiagnosisOutput,
        )
    except anthropic.AuthenticationError as exc:
        raise DiagnosisFailed("authentication_error") from exc
    except anthropic.PermissionDeniedError as exc:
        raise DiagnosisFailed("permission_denied") from exc
    except anthropic.NotFoundError as exc:
        raise DiagnosisFailed("model_not_found") from exc
    except anthropic.RateLimitError as exc:
        raise DiagnosisFailed("rate_limited") from exc
    except anthropic.APIConnectionError as exc:
        raise DiagnosisFailed("connection_error") from exc
    except anthropic.APIStatusError as exc:
        raise DiagnosisFailed(f"api_error_{exc.status_code}") from exc
    except Exception as exc:  # anything else must still degrade, never propagate
        raise DiagnosisFailed(f"unexpected_error:{type(exc).__name__}") from exc

    parsed = response.parsed_output
    if parsed is None:
        raise DiagnosisFailed("no_parsed_output")

    if not set(parsed.cited_evidence_ids).issubset(bundle.valid_ids()):
        raise DiagnosisFailed("hallucinated_citation")

    # Built explicitly rather than response.to_dict(): that method reconstructs
    # the full untyped Message shape, which doesn't know about the parsed
    # content block .parse() actually returns and emits a wall of pydantic
    # "unexpected value" warnings for every union member it isn't. The audit
    # trail only ever needs these fields anyway.
    raw_response = {
        "id": response.id,
        "model": response.model,
        "stop_reason": response.stop_reason,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
        "parsed_output": parsed.model_dump(mode="json"),
    }
    return parsed, prompt_hash(), raw_response

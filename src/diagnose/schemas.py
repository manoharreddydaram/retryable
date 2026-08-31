"""The LLM's structured output contract.

category and suggested_intervention are typed as the real closed enums, not
free strings, so the Messages API's schema-constrained decoding makes it
structurally impossible for a response to name a category or intervention
that doesn't exist -- not just checked after the fact.

Even so, a schema-valid combination can still be wrong in context (a
correctly-identified infra_outage paired with send_payment_link, say) --
that's what the policy engine's contextual gates are for, unchanged from
Stage 4. This schema prevents nonsense; it does not and should not decide
what's appropriate.
"""

from pydantic import BaseModel, Field

from src.classify.taxonomy import FailureCategory
from src.policy.catalog import Intervention


class DiagnosisOutput(BaseModel):
    category: FailureCategory
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    cited_evidence_ids: list[str]
    suggested_intervention: Intervention

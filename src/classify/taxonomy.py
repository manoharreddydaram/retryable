"""The canonical failure taxonomy.

Nine categories, each with different recovery semantics. Values and their
profiles are defined once in error_taxonomy.yaml; this enum exists so the
rest of the codebase gets static typing and IDE completion instead of bare
strings. tests/test_taxonomy.py asserts the two never drift apart.
"""

from enum import StrEnum


class FailureCategory(StrEnum):
    INSUFFICIENT_FUNDS = "insufficient_funds"
    AUTH_ABANDONED = "auth_abandoned"
    INPUT_ERROR_RETRIABLE = "input_error_retriable"
    INSTRUMENT_BLOCKED = "instrument_blocked"
    ISSUER_DECLINED = "issuer_declined"
    INFRA_OUTAGE = "infra_outage"
    AMBIGUOUS_VERIFY_BEFORE_ACTING = "ambiguous_verify_before_acting"
    MERCHANT_CONFIG_ERROR = "merchant_config_error"
    UNKNOWN = "unknown"

"""Typed application settings, loaded from `.env`.

One object mirrors every field already declared in `.env.example`. Nothing
here is invented — this module exists so the rest of the codebase reads
config through validated fields instead of `os.environ.get(...)` scattered
across modules.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    anthropic_api_key: str = ""
    # claude-opus-5 is Anthropic's current top-tier model. Which model to
    # spend real money on for a given workload is the merchant's decision,
    # not one to hardcode -- this stays overridable via .env.
    anthropic_model: str = "claude-opus-5"

    # Safety limits — enforced by the policy engine from Stage 4 onward.
    kill_switch_enabled: bool = False
    max_interventions_per_batch: int = 200
    max_touches_per_payer_7d: int = 3
    quiet_hours_start: int = 21
    quiet_hours_end: int = 9
    min_diagnosis_confidence: float = 0.7
    human_approval_threshold_paise: int = 2_500_000
    intervention_cost_paise: int = 50

    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_cooldown_seconds: int = 60

    # Degradation detector (Stage 8) -- see src/detect/service.py.
    detector_window_minutes: int = 60
    # Designed failure #4: never test a sample smaller than this, regardless
    # of how extreme it looks. See significance.py's own docstring for why
    # the significance test alone can't be trusted to reject a tiny sample.
    detector_min_sample_size: int = 20
    detector_confidence_threshold: float = 0.99
    detector_ewma_alpha: float = 0.3
    # How many pseudo-observations of confidence the EWMA baseline is worth,
    # when treated as a Beta prior. Fixed rather than growing with
    # `observations` so a long-running baseline never becomes so falsely
    # certain that ordinary noise starts looking like degradation.
    detector_baseline_strength: float = 50.0

    @field_validator("razorpay_key_id")
    @classmethod
    def _key_must_be_test_mode(cls, value: str) -> str:
        if value and not value.startswith("rzp_test_"):
            raise ValueError(
                "RAZORPAY_KEY_ID must start with 'rzp_test_' — this project is test-mode only"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

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

    # Safety limits — enforced by the policy engine from Stage 4 onward.
    kill_switch_enabled: bool = False
    max_interventions_per_batch: int = 200
    max_touches_per_payer_7d: int = 3
    quiet_hours_start: int = 21
    quiet_hours_end: int = 9
    min_diagnosis_confidence: float = 0.7
    human_approval_threshold_paise: int = 2_500_000
    intervention_cost_paise: int = 50

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

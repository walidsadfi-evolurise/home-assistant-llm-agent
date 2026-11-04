from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HA_AGENT_", env_file=".env", extra="ignore")

    ha_url: str = "http://homeassistant.local:8123"
    ha_token: str = ""
    policy_file: str = "policy.yaml"
    audit_file: str = "data/audit.jsonl"
    planner: str = "rules"  # rules | anthropic | openai
    llm_model: str = "claude-haiku-4-5"
    llm_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    api_token: str | None = None
    dry_run: bool = False
    verify_delay: float = 1.0

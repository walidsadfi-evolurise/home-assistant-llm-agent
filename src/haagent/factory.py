from __future__ import annotations

from pathlib import Path

from haagent.agent import Agent
from haagent.config import Settings
from haagent.ha import HomeAssistant
from haagent.llm import AnthropicLLM, OpenAICompatibleLLM
from haagent.planner import LLMPlanner, Planner, RuleBasedPlanner
from haagent.policy import Policy


def make_planner(s: Settings) -> Planner:
    if s.planner == "rules":
        return RuleBasedPlanner()
    if s.planner == "anthropic":
        if not s.anthropic_api_key:
            raise ValueError("HA_AGENT_ANTHROPIC_API_KEY is required")
        return LLMPlanner(AnthropicLLM(s.llm_model, s.anthropic_api_key))
    if s.planner == "openai":
        return LLMPlanner(OpenAICompatibleLLM(s.llm_model, s.llm_base_url, s.openai_api_key))
    raise ValueError(f"unknown planner {s.planner}")


def make_agent(s: Settings | None = None) -> Agent:
    s = s or Settings()
    if not s.ha_token:
        raise ValueError(
            "HA_AGENT_HA_TOKEN is required (Home Assistant → profile → long-lived access tokens)"
        )
    return Agent(
        HomeAssistant(s.ha_url, s.ha_token),
        make_planner(s),
        Policy.load(Path(s.policy_file)),
        audit_file=Path(s.audit_file),
        dry_run=s.dry_run,
        verify_delay=s.verify_delay,
    )

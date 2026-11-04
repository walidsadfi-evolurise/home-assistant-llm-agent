from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from haagent.agent import Agent
from haagent.ha import HomeAssistant
from haagent.planner import RuleBasedPlanner
from haagent.policy import Policy
from tests.mock_ha import TOKEN, MockHA

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def mock() -> Iterator[MockHA]:
    m = MockHA()
    yield m
    m.close()


@pytest.fixture
def policy() -> Policy:
    return Policy.load(ROOT / "policy.yaml")


@pytest.fixture
def agent(mock: MockHA, policy: Policy, tmp_path: Path) -> Agent:
    return Agent(
        HomeAssistant(mock.url, TOKEN),
        RuleBasedPlanner(),
        policy,
        audit_file=tmp_path / "audit.jsonl",
        verify_delay=0,
    )

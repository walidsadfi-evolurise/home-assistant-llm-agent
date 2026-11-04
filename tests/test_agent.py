from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from haagent.agent import Agent
from haagent.ha import HomeAssistant
from haagent.llm import FakeLLM
from haagent.planner import LLMPlanner
from haagent.policy import Policy
from tests.mock_ha import TOKEN, MockHA


def test_simple_action_is_executed_and_verified(agent: Agent, mock: MockHA, tmp_path: Path) -> None:
    out = agent.handle("allume la lumière du salon")
    assert out.status == "done"
    assert mock.states["light.salon"]["state"] == "on"
    ex = out.executions[0]
    assert ex.ok and ex.verified and ex.before == "off" and ex.after == "on"
    log = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert log[0]["status"] == "done" and log[0]["executions"][0]["action"]["entity_id"] == "light.salon"


def test_denied_entity_is_refused_without_calling_ha(agent: Agent, mock: MockHA) -> None:
    # the planner cannot even see the boiler, so "chaudière" is unknown to it
    out = agent.handle("éteins la chaudière")
    assert out.status in ("clarify", "nothing") and mock.calls == []
    assert mock.states["switch.boiler_main"]["state"] == "on"


def test_risky_action_needs_confirmation_then_runs(agent: Agent, mock: MockHA) -> None:
    out = agent.handle("déverrouille la porte d'entrée")
    assert out.status == "pending_confirmation" and out.confirmation_id
    assert mock.states["lock.porte_entree"]["state"] == "locked" and mock.calls == []
    assert len(agent.pending()) == 1

    done = agent.confirm(out.confirmation_id)
    assert done.status == "done" and mock.states["lock.porte_entree"]["state"] == "unlocked"
    assert done.executions[0].verified is True
    assert agent.pending() == []


def test_confirm_flag_skips_the_question(agent: Agent, mock: MockHA) -> None:
    out = agent.handle("verrouille la porte d'entrée", confirm=True)
    assert out.status == "done" and mock.states["lock.porte_entree"]["state"] == "locked"


def test_unknown_confirmation_id(agent: Agent) -> None:
    try:
        agent.confirm("nope")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


def test_temperature_outside_limits_requires_confirmation(agent: Agent, mock: MockHA) -> None:
    ok = agent.handle("mets le chauffage à 21")
    assert ok.status == "done" and mock.states["climate.thermostat"]["attributes"]["temperature"] == 21.0
    hot = agent.handle("mets le chauffage à 28")
    assert hot.status == "pending_confirmation" and "outside" in hot.reply


def test_quiet_hours_apply_to_media(agent: Agent) -> None:
    night = agent.handle("allume la TV salon", now=datetime(2026, 1, 1, 23, 45))
    assert night.status == "pending_confirmation" and "quiet hours" in night.reply
    day = agent.handle("allume la TV salon", now=datetime(2026, 1, 1, 15, 0))
    assert day.status == "done"


def test_dry_run_never_calls_home_assistant(mock: MockHA, policy: Policy, tmp_path: Path) -> None:
    from haagent.planner import RuleBasedPlanner

    agent = Agent(HomeAssistant(mock.url, TOKEN), RuleBasedPlanner(), policy, dry_run=True, verify_delay=0)
    out = agent.handle("éteins tout")
    assert out.status == "dry_run" and len(out.verdicts) == 4 and mock.calls == []


def test_failed_service_call_and_unverified_state_are_reported(agent: Agent, mock: MockHA) -> None:
    mock.fail_services.add("light.turn_on")
    out = agent.handle("allume la chambre")
    assert out.status == "done" and not out.executions[0].ok and "échoué" in out.reply
    mock.fail_services.clear()
    mock.flaky_entities.add("light.chambre")
    out = agent.handle("allume la chambre")
    assert out.executions[0].ok and out.executions[0].verified is False and "non confirmé" in out.reply


def test_too_many_actions_is_refused(mock: MockHA, policy: Policy) -> None:
    from haagent.planner import RuleBasedPlanner

    policy.max_actions_per_request = 2
    agent = Agent(HomeAssistant(mock.url, TOKEN), RuleBasedPlanner(), policy, verify_delay=0)
    out = agent.handle("éteins tout")
    assert out.status == "refused" and mock.calls == []


def test_llm_planner_only_sees_visible_entities_and_drops_hallucinations(
    mock: MockHA, policy: Policy
) -> None:
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "actions": [
                        {"domain": "light", "service": "turn_off", "entity_id": "light.cuisine"},
                        {
                            "domain": "switch",
                            "service": "turn_off",
                            "entity_id": "switch.boiler_main",
                        },  # not visible → dropped
                        {
                            "domain": "light",
                            "service": "turn_off",
                            "entity_id": "light.ghost",
                        },  # hallucinated → dropped
                    ],
                    "reply": "J'éteins la cuisine.",
                }
            )
        ]
    )
    agent = Agent(HomeAssistant(mock.url, TOKEN), LLMPlanner(llm), policy, verify_delay=0)
    out = agent.handle("éteins la cuisine et la chaudière")
    assert "camera.entree" not in llm.calls[0][1] and "switch.boiler_main" not in llm.calls[0][1]
    assert [a.entity_id for a in out.plan.actions] == ["light.cuisine"]
    assert "ignoré" in out.reply and out.status == "done"
    assert mock.states["switch.boiler_main"]["state"] == "on"


def test_llm_planner_bad_json_asks_to_rephrase(mock: MockHA, policy: Policy) -> None:
    planner = LLMPlanner(FakeLLM(["sure thing!"]))
    agent = Agent(HomeAssistant(mock.url, TOKEN), planner, policy, verify_delay=0)
    out = agent.handle("blah")
    assert out.status == "clarify" and planner.last_error and mock.calls == []


def test_wrong_token_is_a_clear_error(mock: MockHA) -> None:
    from haagent.ha import HAError

    try:
        HomeAssistant(mock.url, "wrong").states()
    except HAError as e:
        assert "401" in str(e)
    else:
        raise AssertionError("expected HAError")

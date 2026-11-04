from __future__ import annotations

from datetime import time

from haagent.models import Action, Entity
from haagent.planner import RuleBasedPlanner
from haagent.policy import Policy


def _a(domain: str, service: str, eid: str, **data: object) -> Action:
    return Action(domain=domain, service=service, entity_id=eid, data=dict(data))


def test_allow_deny_and_visibility(policy: Policy) -> None:
    assert policy.entity_allowed("light.salon")
    assert not policy.entity_allowed("camera.entree")
    assert not policy.entity_allowed("switch.boiler_main")
    ents = [
        Entity(entity_id=e, state="x", name=e)
        for e in ("light.salon", "camera.entree", "sensor.temp", "switch.boiler_main")
    ]
    assert [e.entity_id for e in policy.visible(ents)] == ["light.salon", "sensor.temp"]


def test_verdicts(policy: Policy) -> None:
    ok = policy.judge(_a("light", "turn_on", "light.salon"))
    assert ok.allowed and not ok.requires_confirmation and ok.reasons == []

    lock = policy.judge(_a("lock", "unlock", "lock.porte_entree"))
    assert lock.allowed and lock.requires_confirmation and "service requires confirmation" in lock.reasons

    denied = policy.judge(_a("switch", "turn_off", "switch.boiler_main"))
    assert not denied.allowed and not denied.requires_confirmation

    wrong_service = policy.judge(_a("light", "set_temperature", "light.salon"))
    assert not wrong_service.allowed

    mismatch = policy.judge(_a("light", "turn_on", "switch.machine_a_laver"))
    assert not mismatch.allowed

    unknown_domain = policy.judge(_a("shell_command", "turn_on", "shell_command.rm"))
    assert not unknown_domain.allowed

    hot = policy.judge(_a("climate", "set_temperature", "climate.thermostat", temperature=28))
    assert hot.allowed and hot.requires_confirmation
    fine = policy.judge(_a("climate", "set_temperature", "climate.thermostat", temperature=21))
    assert fine.allowed and not fine.requires_confirmation
    bad = policy.judge(_a("climate", "set_temperature", "climate.thermostat", temperature="warm"))
    assert not bad.allowed

    loud = policy.judge(_a("media_player", "volume_set", "media_player.salon_tv", volume_level=0.9))
    assert loud.requires_confirmation

    night = policy.judge(_a("media_player", "media_play", "media_player.salon_tv"), now=time(23, 30))
    assert night.requires_confirmation and "quiet hours" in night.reasons
    day = policy.judge(_a("media_player", "media_play", "media_player.salon_tv"), now=time(14, 0))
    assert not day.requires_confirmation


def test_default_policy_is_conservative() -> None:
    p = Policy()
    assert p.judge(
        _a("alarm_control_panel", "alarm_disarm", "alarm_control_panel.home")
    ).requires_confirmation
    assert not p.entity_allowed("camera.front")
    assert p.judge(_a("script", "turn_on", "script.leave_home")).requires_confirmation


ENTS = [
    Entity(entity_id="light.salon", state="off", name="Lumière salon"),
    Entity(entity_id="light.cuisine", state="on", name="Lumière cuisine"),
    Entity(entity_id="cover.volet_salon", state="open", name="Volet salon"),
    Entity(
        entity_id="climate.thermostat",
        state="heat",
        name="Thermostat",
        attributes={"current_temperature": 18.4},
    ),
    Entity(entity_id="lock.porte_entree", state="locked", name="Porte d'entrée"),
    Entity(entity_id="media_player.salon_tv", state="playing", name="TV salon"),
    Entity(entity_id="switch.machine_a_laver", state="off", name="Lave-linge"),
]


def test_rule_planner_french_and_english() -> None:
    p = RuleBasedPlanner()
    on = p.plan("Allume la lumière du salon", ENTS)
    assert [a.describe() for a in on.actions] == ["light.turn_on → light.salon"]
    assert on.reply.startswith("J'allume")

    off = p.plan("turn off the kitchen light", ENTS)
    assert (
        off.actions == [] or off.needs_clarification
    )  # "kitchen" is not in the French names: must not guess

    off_fr = p.plan("éteins la cuisine", ENTS)
    assert [a.entity_id for a in off_fr.actions] == ["light.cuisine"]

    cover = p.plan("ferme le volet du salon", ENTS)
    assert cover.actions[0].service == "close_cover"

    temp = p.plan("mets le chauffage à 21,5", ENTS)
    assert temp.actions[0].data == {"temperature": 21.5}

    lock = p.plan("verrouille la porte d'entrée", ENTS)
    assert lock.actions[0].service == "lock"
    unlock = p.plan("unlock the front door", ENTS)
    assert unlock.actions[0].service == "unlock"

    washer = p.plan("lance le lave-linge", ENTS)
    assert [a.describe() for a in washer.actions] == ["switch.turn_on → switch.machine_a_laver"]

    everything = p.plan("éteins tout", ENTS)
    assert {a.entity_id for a in everything.actions} == {
        "light.salon",
        "light.cuisine",
        "media_player.salon_tv",
    }

    q = p.plan("est-ce que la porte d'entrée est verrouillée ?", ENTS)
    assert q.actions == [] and "locked" in q.reply

    unknown = p.plan("fais un café", ENTS)
    assert unknown.needs_clarification and unknown.actions == []

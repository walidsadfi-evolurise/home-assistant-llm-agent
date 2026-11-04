"""Turn a sentence into a Plan.

The LLM planner sees only the entities the policy lets it see, and may only
return service calls — never arbitrary code. Its JSON is validated; anything
else is a clarification request. The rule-based planner covers the frequent
commands offline (and is what the tests run against).
"""

from __future__ import annotations

import json
import re
import unicodedata
from abc import ABC, abstractmethod

from pydantic import ValidationError

from haagent.llm import LLM
from haagent.models import Action, Entity, Plan
from haagent.policy import valid_entity_id

SYSTEM_PROMPT = """You control a home through Home Assistant service calls.
You receive the list of entities you may use (entity_id | name | state | attributes) and a request.
Return ONLY a JSON object:
{"actions": [{"domain": "light", "service": "turn_on", "entity_id": "light.salon", "data": {}}],
 "reply": "one short sentence in the user's language", "needs_clarification": false}
Rules:
- Use only entity_ids from the list. Never invent one. If the request is ambiguous (several matching
  entities, missing value), return no actions, needs_clarification=true and ask in `reply`.
- Only these services: light/switch/fan: turn_on, turn_off, toggle; cover: open_cover, close_cover,
  set_cover_position; climate: set_temperature (data.temperature), set_hvac_mode; media_player: media_play,
  media_pause, volume_set (data.volume_level 0..1); scene/script: turn_on; vacuum: start, return_to_base;
  lock: lock, unlock; alarm_control_panel: alarm_arm_home, alarm_arm_away, alarm_disarm.
- Questions about the home ("is the door locked?") → no actions, answer from the states in `reply`.
- Be literal. "Turn off everything" means every light and media_player in the list, nothing else."""


class Planner(ABC):
    name: str = "base"

    @abstractmethod
    def plan(self, request: str, entities: list[Entity]) -> Plan: ...


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


class RuleBasedPlanner(Planner):
    """Handles on/off/toggle, open/close, temperature, lock/unlock, scenes and simple questions, FR + EN."""

    name = "rules"

    _ON = (
        "allume",
        "allumer",
        "turn on",
        "switch on",
        "mets en route",
        "demarre",
        "start",
        "lance",
        "ouvre",
        "open",
        "monte",
    )
    _OFF = (
        "eteins",
        "eteindre",
        "turn off",
        "switch off",
        "coupe",
        "arrete",
        "stop",
        "ferme",
        "close",
        "baisse",
        "descends",
    )
    _LOCK = ("verrouille", "lock", "ferme a cle")
    _UNLOCK = ("deverrouille", "unlock", "ouvre la serrure")
    _TEMP = re.compile(r"(\d{1,2}(?:[.,]\d)?)\s*(?:°|degres|degrees|deg|c\b)?")
    _QUESTION = ("est-ce", "est ce", "is the", "are the", "quelle est", "what is", "combien", "how", "?")

    def plan(self, request: str, entities: list[Entity]) -> Plan:
        q = _norm(request)
        targets = self._match(q, entities)

        if any(k in q for k in self._QUESTION) and not any(k in q for k in self._ON + self._OFF):
            if not targets:
                return Plan(
                    reply="Je ne trouve pas cet équipement." if _is_fr(q) else "I can't find that device.",
                    needs_clarification=True,
                )
            lines = [
                f"{e.name}: {e.state}"
                + (
                    f" ({e.attributes['current_temperature']}°)"
                    if "current_temperature" in e.attributes
                    else ""
                )
                for e in targets[:5]
            ]
            return Plan(reply="; ".join(lines))

        if (
            "climate" in {e.domain for e in targets}
            or "chauffage" in q
            or "heating" in q
            or "thermostat" in q
        ):
            m = self._TEMP.search(q)
            clim = [e for e in targets if e.domain == "climate"] or [
                e for e in entities if e.domain == "climate"
            ]
            if m and clim:
                temp = float(m.group(1).replace(",", "."))
                return Plan(
                    actions=[
                        Action(
                            domain="climate",
                            service="set_temperature",
                            entity_id=e.entity_id,
                            data={"temperature": temp},
                        )
                        for e in clim[:1]
                    ],
                    reply=(
                        f"Je règle {clim[0].name} sur {temp:g}°."
                        if _is_fr(q)
                        else f"Setting {clim[0].name} to {temp:g}°."
                    ),
                )

        if any(k in q for k in self._UNLOCK) or any(k in q for k in self._LOCK):
            locks = [e for e in targets if e.domain == "lock"] or [e for e in entities if e.domain == "lock"]
            if not locks:
                return Plan(
                    reply="Aucune serrure trouvée." if _is_fr(q) else "No lock found.",
                    needs_clarification=True,
                )
            service = "unlock" if any(k in q for k in self._UNLOCK) else "lock"
            return Plan(
                actions=[Action(domain="lock", service=service, entity_id=e.entity_id) for e in locks],
                reply=(
                    ("Je déverrouille " if service == "unlock" else "Je verrouille ")
                    + ", ".join(e.name for e in locks)
                    + "."
                )
                if _is_fr(q)
                else (
                    ("Unlocking " if service == "unlock" else "Locking ")
                    + ", ".join(e.name for e in locks)
                    + "."
                ),
            )

        on = any(k in q for k in self._ON)
        off = any(k in q for k in self._OFF)
        if not (on or off):
            return Plan(
                reply="Je n'ai pas compris la demande." if _is_fr(q) else "I didn't understand the request.",
                needs_clarification=True,
            )
        if "tout" in q.split() or "everything" in q or "all the" in q or "toutes les" in q:
            targets = targets if targets else [e for e in entities if e.domain in {"light", "media_player"}]
        if not targets:
            return Plan(reply="Quel équipement ?" if _is_fr(q) else "Which device?", needs_clarification=True)

        actions: list[Action] = []
        for e in targets:
            if e.domain in {"light", "switch", "fan", "media_player"}:
                actions.append(
                    Action(
                        domain=e.domain,
                        service="turn_on" if on and not off else "turn_off",
                        entity_id=e.entity_id,
                    )
                )
            elif e.domain == "cover":
                actions.append(
                    Action(
                        domain="cover",
                        service="open_cover" if on and not off else "close_cover",
                        entity_id=e.entity_id,
                    )
                )
            elif e.domain in {"scene", "script"}:
                actions.append(Action(domain=e.domain, service="turn_on", entity_id=e.entity_id))
            elif e.domain == "vacuum":
                actions.append(
                    Action(
                        domain="vacuum",
                        service="start" if on and not off else "return_to_base",
                        entity_id=e.entity_id,
                    )
                )
        names = ", ".join(e.name for e in targets)
        verb = (
            ("J'allume " if on and not off else "J'éteins ")
            if _is_fr(q)
            else ("Turning on " if on and not off else "Turning off ")
        )
        return Plan(actions=actions, reply=f"{verb}{names}.")

    _DOMAIN_HINTS = {
        "light": ("lumiere", "lumieres", "lampe", "lampes", "light", "lights", "eclairage"),
        "cover": (
            "volet",
            "volets",
            "store",
            "stores",
            "shutter",
            "shutters",
            "blind",
            "blinds",
            "garage",
            "portail",
            "gate",
        ),
        "media_player": ("tv", "tele", "television", "musique", "music", "enceinte", "speaker", "radio"),
        "lock": ("serrure", "verrou", "lock"),
        "climate": ("chauffage", "thermostat", "heating", "clim", "climatisation"),
        "vacuum": ("aspirateur", "vacuum", "robot"),
        "switch": ("prise", "plug", "lave", "machine", "washer"),
    }

    @classmethod
    def _match(cls, q: str, entities: list[Entity]) -> list[Entity]:
        words = set(re.findall(r"[a-z0-9]+", q))
        hinted = {d for d, hints in cls._DOMAIN_HINTS.items() if words & set(hints)}
        if hinted:
            pool = [e for e in entities if e.domain in hinted]
            entities = pool or entities
        scored: list[tuple[int, Entity]] = []
        for e in entities:
            name_words = set(re.findall(r"[a-z0-9]+", _norm(e.name))) | set(
                e.entity_id.split(".", 1)[1].split("_")
            )
            name_words -= {
                "the",
                "le",
                "la",
                "les",
                "du",
                "de",
                "des",
                "light",
                "lumiere",
                "lampe",
                "switch",
                "a",
            }
            hit = len(words & name_words)
            if hit:
                scored.append((hit, e))
        if not scored:
            return []
        best = max(h for h, _ in scored)
        return [e for h, e in scored if h == best]


def _is_fr(q: str) -> bool:
    return any(
        w in f" {q} "
        for w in (
            " le ",
            " la ",
            " les ",
            " allume",
            " eteins",
            " ferme",
            " ouvre",
            " regle",
            " mets ",
            " est-ce",
            " quelle ",
        )
    )


class LLMPlanner(Planner):
    name = "llm"

    def __init__(self, llm: LLM) -> None:
        self.llm = llm
        self.last_error: str | None = None

    def plan(self, request: str, entities: list[Entity]) -> Plan:
        self.last_error = None
        known = {e.entity_id for e in entities}
        user = "Entities:\n" + "\n".join(e.brief() for e in entities) + f"\n\nRequest: {request}"
        try:
            raw = self.llm.complete(SYSTEM_PROMPT, user)
            m = re.search(r"\{.*\}", raw, re.S)
            if not m:
                raise ValueError("no JSON in model output")
            plan = Plan.model_validate(json.loads(m.group(0)))
        except (ValueError, ValidationError, json.JSONDecodeError) as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return Plan(reply="Je n'ai pas compris, pouvez-vous reformuler ?", needs_clarification=True)
        except Exception as e:  # provider / network
            self.last_error = f"{type(e).__name__}: {e}"
            return Plan(reply="L'assistant est indisponible pour le moment.", needs_clarification=True)

        # Hallucinated or malformed entity ids are dropped, and the user is told.
        bad = [
            a.entity_id for a in plan.actions if a.entity_id not in known or not valid_entity_id(a.entity_id)
        ]
        if bad:
            plan.actions = [a for a in plan.actions if a.entity_id not in bad]
            plan.reply += f" (ignoré : {', '.join(bad)})"
            if not plan.actions:
                plan.needs_clarification = True
        return plan

"""What the agent may touch, and what needs a human to say yes first.

Defaults are conservative on purpose: locks, alarms, garage doors and anything
that heats or pumps need confirmation; cameras and anything not allowlisted are
off limits. The YAML policy file overrides these for a given home.
"""

from __future__ import annotations

import re
from datetime import time
from fnmatch import fnmatch
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from haagent.models import Action, Entity, Verdict


class ClimateLimits(BaseModel):
    min_temperature: float = 15.0
    max_temperature: float = 24.0


class QuietHours(BaseModel):
    start: time = time(22, 30)
    end: time = time(7, 0)
    # During quiet hours these domains need confirmation (e.g. don't blast the speakers at 3 am).
    confirm_domains: list[str] = Field(default_factory=lambda: ["media_player", "vacuum", "siren"])


class Policy(BaseModel):
    # Globs on entity_id. Empty allow = everything in the allowed domains.
    allow: list[str] = Field(
        default_factory=lambda: [
            "light.*",
            "switch.*",
            "cover.*",
            "climate.*",
            "media_player.*",
            "fan.*",
            "scene.*",
            "script.*",
            "vacuum.*",
            "lock.*",
            "alarm_control_panel.*",
        ]
    )
    deny: list[str] = Field(
        default_factory=lambda: [
            "camera.*",
            "person.*",
            "device_tracker.*",
            "switch.*boiler*",
            "switch.*pump*",
            "switch.*server*",
        ]
    )
    # Always need a human yes.
    confirm: list[str] = Field(
        default_factory=lambda: [
            "lock.*",
            "alarm_control_panel.*",
            "cover.*garage*",
            "cover.*gate*",
            "switch.*heater*",
            "switch.*oven*",
            "script.*",
            "siren.*",
        ]
    )
    confirm_services: list[str] = Field(
        default_factory=lambda: [
            "lock.unlock",
            "alarm_control_panel.alarm_disarm",
            "homeassistant.restart",
            "homeassistant.stop",
        ]
    )
    climate: ClimateLimits = Field(default_factory=ClimateLimits)
    quiet_hours: QuietHours | None = Field(default_factory=QuietHours)
    max_actions_per_request: int = 8
    allowed_services: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "light": ["turn_on", "turn_off", "toggle"],
            "switch": ["turn_on", "turn_off", "toggle"],
            "fan": ["turn_on", "turn_off", "set_percentage"],
            "cover": ["open_cover", "close_cover", "stop_cover", "set_cover_position"],
            "climate": ["set_temperature", "set_hvac_mode", "turn_on", "turn_off"],
            "media_player": ["media_play", "media_pause", "media_stop", "volume_set", "turn_off", "turn_on"],
            "scene": ["turn_on"],
            "script": ["turn_on"],
            "vacuum": ["start", "return_to_base", "stop"],
            "lock": ["lock", "unlock"],
            "alarm_control_panel": ["alarm_arm_home", "alarm_arm_away", "alarm_disarm"],
        }
    )

    @classmethod
    def load(cls, path: Path | None) -> Policy:
        if path is None or not path.exists():
            return cls()
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    # ------------------------------------------------------------------
    def entity_allowed(self, entity_id: str) -> bool:
        if any(fnmatch(entity_id, g) for g in self.deny):
            return False
        return not self.allow or any(fnmatch(entity_id, g) for g in self.allow)

    def visible(self, entities: list[Entity]) -> list[Entity]:
        """Entities the planner is allowed to know about (controllable ones + sensors for context)."""
        return [
            e
            for e in entities
            if self.entity_allowed(e.entity_id) or e.domain in {"sensor", "binary_sensor", "weather", "sun"}
        ]

    def judge(self, action: Action, now: time | None = None) -> Verdict:
        reasons: list[str] = []
        allowed = True
        confirm = False

        if not self.entity_allowed(action.entity_id):
            allowed = False
            reasons.append(f"{action.entity_id} is not in the allowlist")
        if action.domain != action.entity_id.split(".", 1)[0] and action.domain != "homeassistant":
            allowed = False
            reasons.append(f"service domain {action.domain} does not match entity {action.entity_id}")
        services = self.allowed_services.get(action.domain)
        if services is not None and action.service not in services:
            allowed = False
            reasons.append(f"{action.domain}.{action.service} is not an allowed service")
        if services is None and action.domain != "homeassistant":
            allowed = False
            reasons.append(f"domain {action.domain} has no allowed services")

        if any(fnmatch(action.entity_id, g) for g in self.confirm):
            confirm = True
            reasons.append("entity requires confirmation")
        if f"{action.domain}.{action.service}" in self.confirm_services:
            confirm = True
            reasons.append("service requires confirmation")
        if action.domain == "climate" and action.service == "set_temperature":
            t = action.data.get("temperature")
            if not isinstance(t, int | float):
                allowed = False
                reasons.append("set_temperature needs a numeric temperature")
            elif not self.climate.min_temperature <= float(t) <= self.climate.max_temperature:
                confirm = True
                reasons.append(
                    f"temperature {t} outside {self.climate.min_temperature}–{self.climate.max_temperature}"
                )
        quiet = self.quiet_hours and now is not None and _in_quiet_hours(now, self.quiet_hours)
        if quiet and self.quiet_hours and action.domain in self.quiet_hours.confirm_domains:
            confirm = True
            reasons.append("quiet hours")
        if action.domain == "media_player" and action.service == "volume_set":
            v = action.data.get("volume_level", 0)
            if isinstance(v, int | float) and float(v) > 0.6:
                confirm = True
                reasons.append("volume above 60 %")
        return Verdict(
            action=action, allowed=allowed, requires_confirmation=confirm and allowed, reasons=reasons
        )


def _in_quiet_hours(now: time, q: QuietHours) -> bool:
    return now >= q.start or now < q.end if q.start > q.end else q.start <= now < q.end


_SAFE_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def valid_entity_id(entity_id: str) -> bool:
    return bool(_SAFE_ID.match(entity_id))

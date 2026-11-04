from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Entity(BaseModel):
    entity_id: str
    state: str
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]

    def brief(self) -> str:
        """One line for the planner prompt: keep tokens down, keep what matters."""
        keep = (
            "brightness",
            "temperature",
            "current_temperature",
            "hvac_mode",
            "position",
            "unit_of_measurement",
        )
        attrs = ", ".join(f"{k}={self.attributes[k]}" for k in keep if k in self.attributes)
        return f"{self.entity_id} | {self.name} | {self.state}" + (f" | {attrs}" if attrs else "")


class Action(BaseModel):
    domain: str
    service: str
    entity_id: str
    data: dict[str, Any] = Field(default_factory=dict)

    def describe(self) -> str:
        extra = f" {self.data}" if self.data else ""
        return f"{self.domain}.{self.service} → {self.entity_id}{extra}"


class Plan(BaseModel):
    """What the planner (LLM or rules) proposes for one request."""

    actions: list[Action] = Field(default_factory=list)
    reply: str = Field(description="Short answer for the user, in their language")
    needs_clarification: bool = False


class Verdict(BaseModel):
    action: Action
    allowed: bool
    requires_confirmation: bool
    reasons: list[str] = Field(default_factory=list)


class Execution(BaseModel):
    action: Action
    ok: bool
    verified: bool | None = Field(
        default=None, description="State read back matched the intent (None = not checked)"
    )
    before: str | None = None
    after: str | None = None
    error: str | None = None


class Outcome(BaseModel):
    request: str
    plan: Plan
    verdicts: list[Verdict]
    status: Literal["done", "pending_confirmation", "refused", "clarify", "dry_run", "nothing"]
    confirmation_id: str | None = None
    executions: list[Execution] = Field(default_factory=list)
    reply: str
    planner: str
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))

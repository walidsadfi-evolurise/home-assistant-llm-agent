"""request → plan → policy verdicts → (confirmation) → execute → verify → audit."""

from __future__ import annotations

import json
import secrets
import time as _time
from datetime import datetime
from pathlib import Path

from haagent.ha import HAError, HomeAssistant
from haagent.models import Action, Entity, Execution, Outcome, Plan, Verdict
from haagent.planner import Planner
from haagent.policy import Policy

# Service → (expected state after, or None when not verifiable from state alone)
EXPECTED_STATE: dict[str, str | None] = {
    "light.turn_on": "on",
    "light.turn_off": "off",
    "switch.turn_on": "on",
    "switch.turn_off": "off",
    "fan.turn_on": "on",
    "fan.turn_off": "off",
    "cover.open_cover": "open",
    "cover.close_cover": "closed",
    "lock.lock": "locked",
    "lock.unlock": "unlocked",
    "media_player.media_pause": "paused",
    "media_player.media_play": "playing",
    "vacuum.start": "cleaning",
    "vacuum.return_to_base": "returning",
    "alarm_control_panel.alarm_arm_home": "armed_home",
    "alarm_control_panel.alarm_arm_away": "armed_away",
    "alarm_control_panel.alarm_disarm": "disarmed",
}


class Agent:
    def __init__(
        self,
        ha: HomeAssistant,
        planner: Planner,
        policy: Policy,
        audit_file: Path | None = None,
        dry_run: bool = False,
        verify_delay: float = 1.0,
    ) -> None:
        self.ha = ha
        self.planner = planner
        self.policy = policy
        self.audit_file = audit_file
        self.dry_run = dry_run
        self.verify_delay = verify_delay
        self._pending: dict[str, tuple[Outcome, float]] = {}

    # ------------------------------------------------------------------ public
    def handle(self, request: str, now: datetime | None = None, confirm: bool = False) -> Outcome:
        now = now or datetime.now()
        entities = self.policy.visible(self.ha.states())
        plan = self.planner.plan(request, entities)
        verdicts = [self.policy.judge(a, now.time()) for a in plan.actions]

        if plan.needs_clarification or (not plan.actions and not verdicts):
            return self._finish(
                Outcome(
                    request=request,
                    plan=plan,
                    verdicts=verdicts,
                    status="clarify" if plan.needs_clarification else "nothing",
                    reply=plan.reply,
                    planner=self.planner.name,
                )
            )

        if len(plan.actions) > self.policy.max_actions_per_request:
            cap = self.policy.max_actions_per_request
            reply = f"Refusé : {len(plan.actions)} actions demandées, maximum {cap}."
            return self._finish(
                Outcome(
                    request=request,
                    plan=plan,
                    verdicts=verdicts,
                    status="refused",
                    reply=reply,
                    planner=self.planner.name,
                )
            )

        refused = [v for v in verdicts if not v.allowed]
        if refused:
            why = "; ".join(f"{v.action.entity_id}: {', '.join(v.reasons)}" for v in refused)
            return self._finish(
                Outcome(
                    request=request,
                    plan=plan,
                    verdicts=verdicts,
                    status="refused",
                    reply=f"Refusé — {why}",
                    planner=self.planner.name,
                )
            )

        if self.dry_run:
            return self._finish(
                Outcome(
                    request=request,
                    plan=plan,
                    verdicts=verdicts,
                    status="dry_run",
                    reply=f"[dry-run] {plan.reply}",
                    planner=self.planner.name,
                )
            )

        if any(v.requires_confirmation for v in verdicts) and not confirm:
            cid = secrets.token_hex(4)
            needing = [
                f"{v.action.describe()} ({'; '.join(v.reasons)})" for v in verdicts if v.requires_confirmation
            ]
            outcome = Outcome(
                request=request,
                plan=plan,
                verdicts=verdicts,
                status="pending_confirmation",
                confirmation_id=cid,
                reply="Confirmation requise pour : "
                + " | ".join(needing)
                + f". Confirmez avec l'identifiant {cid}.",
                planner=self.planner.name,
            )
            self._pending[cid] = (outcome, _time.time())
            return self._finish(outcome)

        executions = self._execute(plan.actions, entities)
        ok = all(e.ok for e in executions)
        unverified = [e.action.entity_id for e in executions if e.ok and e.verified is False]
        reply = (
            plan.reply
            if ok
            else "Certaines actions ont échoué : "
            + "; ".join(f"{e.action.entity_id}: {e.error}" for e in executions if not e.ok)
        )
        if unverified:
            reply += " (état non confirmé pour " + ", ".join(unverified) + ")"
        return self._finish(
            Outcome(
                request=request,
                plan=plan,
                verdicts=verdicts,
                status="done",
                executions=executions,
                reply=reply,
                planner=self.planner.name,
            )
        )

    def confirm(self, confirmation_id: str, ttl_seconds: int = 300) -> Outcome:
        item = self._pending.pop(confirmation_id, None)
        if item is None:
            raise KeyError(f"unknown confirmation id {confirmation_id}")
        outcome, created = item
        if _time.time() - created > ttl_seconds:
            return self._finish(
                outcome.model_copy(update={"status": "refused", "reply": "Confirmation expirée, redemandez."})
            )
        entities = self.policy.visible(self.ha.states())
        executions = self._execute(outcome.plan.actions, entities)
        ok = all(e.ok for e in executions)
        reply = (
            outcome.plan.reply
            if ok
            else "Certaines actions ont échoué : "
            + "; ".join(f"{e.action.entity_id}: {e.error}" for e in executions if not e.ok)
        )
        return self._finish(
            outcome.model_copy(
                update={
                    "status": "done",
                    "executions": executions,
                    "reply": reply,
                    "confirmation_id": confirmation_id,
                }
            )
        )

    def pending(self) -> list[Outcome]:
        return [o for o, _ in self._pending.values()]

    # ----------------------------------------------------------------- internals
    def _execute(self, actions: list[Action], entities: list[Entity]) -> list[Execution]:
        before = {e.entity_id: e.state for e in entities}
        out: list[Execution] = []
        for a in actions:
            try:
                self.ha.call_service(a.domain, a.service, a.entity_id, a.data)
            except HAError as e:
                out.append(Execution(action=a, ok=False, before=before.get(a.entity_id), error=str(e)))
                continue
            expected = EXPECTED_STATE.get(f"{a.domain}.{a.service}")
            verified: bool | None = None
            after: str | None = None
            if expected is not None:
                _time.sleep(self.verify_delay)
                try:
                    after = self.ha.state(a.entity_id).state
                    verified = after == expected
                except HAError:
                    verified = False
            out.append(
                Execution(action=a, ok=True, verified=verified, before=before.get(a.entity_id), after=after)
            )
        return out

    def _finish(self, outcome: Outcome) -> Outcome:
        if self.audit_file:
            self.audit_file.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(outcome.model_dump(mode="json"), ensure_ascii=False) + "\n")
        return outcome


def summarize_verdicts(verdicts: list[Verdict]) -> str:
    return "\n".join(
        f"{'✗' if not v.allowed else '?' if v.requires_confirmation else '✓'} {v.action.describe()}"
        + (f"  — {', '.join(v.reasons)}" if v.reasons else "")
        for v in verdicts
    )


__all__ = ["Agent", "Plan", "summarize_verdicts"]

"""Minimal Home Assistant REST client (long-lived access token)."""

from __future__ import annotations

from typing import Any

import httpx

from haagent.models import Entity


class HAError(Exception):
    pass


class HomeAssistant:
    def __init__(
        self, url: str, token: str, timeout: float = 10.0, client: httpx.Client | None = None
    ) -> None:
        self.base = url.rstrip("/")
        self.client = client or httpx.Client(
            base_url=self.base, timeout=timeout, headers={"authorization": f"Bearer {token}"}
        )

    def _check(self, r: httpx.Response) -> Any:
        if r.status_code == 401:
            raise HAError("Home Assistant rejected the token (401)")
        if r.status_code >= 400:
            raise HAError(f"Home Assistant returned {r.status_code} for {r.request.url.path}: {r.text[:200]}")
        return r.json() if r.content else None

    def ping(self) -> str:
        data = self._check(self.client.get("/api/"))
        return str(data.get("message", "ok"))

    def states(self) -> list[Entity]:
        data = self._check(self.client.get("/api/states"))
        return [
            Entity(
                entity_id=s["entity_id"],
                state=s["state"],
                name=s.get("attributes", {}).get("friendly_name") or s["entity_id"],
                attributes=s.get("attributes", {}),
            )
            for s in data
        ]

    def state(self, entity_id: str) -> Entity:
        s = self._check(self.client.get(f"/api/states/{entity_id}"))
        return Entity(
            entity_id=s["entity_id"],
            state=s["state"],
            name=s.get("attributes", {}).get("friendly_name") or s["entity_id"],
            attributes=s.get("attributes", {}),
        )

    def call_service(
        self, domain: str, service: str, entity_id: str, data: dict[str, Any] | None = None
    ) -> None:
        payload = {"entity_id": entity_id, **(data or {})}
        self._check(self.client.post(f"/api/services/{domain}/{service}", json=payload))

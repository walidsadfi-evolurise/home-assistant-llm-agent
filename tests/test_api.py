from __future__ import annotations

from fastapi.testclient import TestClient

from haagent import api
from haagent.agent import Agent
from tests.mock_ha import MockHA


def test_api_ask_confirm_pending(agent: Agent, mock: MockHA, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("HA_AGENT_API_TOKEN", "secret")
    api.get_agent.cache_clear()
    api.get_agent = lambda: agent  # type: ignore[assignment]
    c = TestClient(api.app)
    assert c.get("/healthz").json()["home_assistant"] == "API running."
    assert c.post("/ask", json={"text": "x"}).status_code == 401
    h = {"authorization": "Bearer secret"}
    r = c.post("/ask", json={"text": "ouvre la porte garage"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "pending_confirmation"
    cid = r.json()["confirmation_id"]
    assert len(c.get("/pending", headers=h).json()) == 1
    assert c.post("/confirm/zzzz", headers=h).status_code == 404
    r = c.post(f"/confirm/{cid}", headers=h)
    assert r.json()["status"] == "done" and mock.states["cover.garage_door"]["state"] == "open"

"""HTTP surface for a chat UI, a Telegram bot or a HA conversation agent: POST /ask, POST /confirm/{id}."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from haagent.agent import Agent
from haagent.config import Settings
from haagent.factory import make_agent
from haagent.models import Outcome

app = FastAPI(title="home-assistant-llm-agent", version="0.1.0")


@lru_cache(maxsize=1)
def get_agent() -> Agent:
    return make_agent()


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    token = Settings().api_token
    if token and authorization != f"Bearer {token}":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing bearer token")


class AskRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    a = get_agent()
    return {"status": "ok", "home_assistant": a.ha.ping(), "planner": a.planner.name}


@app.post("/ask", response_model=Outcome, dependencies=[Depends(require_token)])
def ask(req: AskRequest) -> Outcome:
    return get_agent().handle(req.text)


@app.post("/confirm/{confirmation_id}", response_model=Outcome, dependencies=[Depends(require_token)])
def confirm(confirmation_id: str) -> Outcome:
    try:
        return get_agent().confirm(confirmation_id)
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e


@app.get("/pending", response_model=list[Outcome], dependencies=[Depends(require_token)])
def pending() -> list[Outcome]:
    return get_agent().pending()

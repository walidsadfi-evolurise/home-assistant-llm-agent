"""Chat-completion clients; only `complete` is needed. See lead-triage-agent for the same pattern."""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx


class LLM(ABC):
    name: str = "base"

    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = 500, temperature: float = 0.0) -> str: ...


class FakeLLM(LLM):
    name = "fake"

    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, max_tokens: int = 500, temperature: float = 0.0) -> str:
        self.calls.append((system, user))
        return self.replies.pop(0) if self.replies else "{}"


class AnthropicLLM(LLM):
    name = "anthropic"

    def __init__(
        self, model: str, api_key: str, base_url: str = "https://api.anthropic.com", timeout: float = 60.0
    ) -> None:
        self.model = model
        self.client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        )

    def complete(self, system: str, user: str, max_tokens: int = 500, temperature: float = 0.0) -> str:
        r = self.client.post(
            "/v1/messages",
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")


class OpenAICompatibleLLM(LLM):
    """OpenAI, Mistral, Groq, vLLM, Ollama (/v1)… anything speaking /chat/completions."""

    name = "openai"

    def __init__(self, model: str, base_url: str, api_key: str | None = None, timeout: float = 60.0) -> None:
        self.model = model
        headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, headers=headers)

    def complete(self, system: str, user: str, max_tokens: int = 500, temperature: float = 0.0) -> str:
        r = self.client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            },
        )
        r.raise_for_status()
        return str(r.json()["choices"][0]["message"]["content"])

from __future__ import annotations

import json
import os
import sys
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass

from django.conf import settings

import httpx


class LLMConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str


def _message_to_payload(message: LLMMessage) -> dict[str, str]:
    return {"role": message.role, "content": message.content}


class LLMHttpClient(ABC):
    @abstractmethod
    def complete(self, path: str, payload: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def acomplete(self, path: str, payload: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    def stream(self, path: str, payload: dict) -> Iterable[dict]:
        raise NotImplementedError

    @abstractmethod
    async def astream(self, path: str, payload: dict) -> AsyncIterator[dict]:
        raise NotImplementedError


class HttpxLLMHttpClient(LLMHttpClient):
    def __init__(
        self,
        base_url: str,
        timeout: int = 60,
        sync_client: httpx.Client | None = None,
        async_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.sync_client = sync_client or httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
        )
        self.async_client = async_client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def complete(self, path: str, payload: dict) -> dict:
        response = self.sync_client.post(
            path,
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def acomplete(self, path: str, payload: dict) -> dict:
        response = await self.async_client.post(
            path,
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def stream(self, path: str, payload: dict) -> Iterable[dict]:
        with self.sync_client.stream(
            "POST",
            path,
            json=payload,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                yield json.loads(line)

    async def astream(self, path: str, payload: dict) -> AsyncIterator[dict]:

        async with self.async_client.stream(
            "POST",
            path,
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                yield json.loads(line)


class LLMClient(ABC):
    @abstractmethod
    def complete(self, messages: Sequence[LLMMessage]) -> str:
        raise NotImplementedError

    @abstractmethod
    async def acomplete(self, messages: Sequence[LLMMessage]) -> str:
        raise NotImplementedError

    @abstractmethod
    async def astream(
        self, messages: Sequence[LLMMessage]
    ) -> AsyncIterator[str]:
        raise NotImplementedError


class OllamaLLMClient(LLMClient):
    def __init__(
        self,
        http_client: LLMHttpClient | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        if http_client is None:
            if base_url is None or model is None:
                raise LLMConfigurationError(
                    "Ollama client requires base_url and model configuration"
                )
            http_client = HttpxLLMHttpClient(
                base_url=base_url,
                timeout=timeout or 60,
            )

        self.http_client = http_client
        self.model = model

    def _payload(self, messages: Sequence[LLMMessage], stream: bool) -> dict:
        return {
            "model": self.model,
            "messages": [_message_to_payload(message) for message in messages],
            "stream": stream,
        }

    def complete(self, messages: Sequence[LLMMessage]) -> str:
        payload = self._payload(messages, stream=False)
        response = self.http_client.complete("/api/chat", payload)
        return response.get("message", {}).get("content", "")

    async def acomplete(self, messages: Sequence[LLMMessage]) -> str:
        payload = self._payload(messages, stream=False)
        response = await self.http_client.acomplete("/api/chat", payload)
        return response.get("message", {}).get("content", "")

    async def astream(
        self, messages: Sequence[LLMMessage]
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, stream=True)
        async for chunk in self.http_client.astream("/api/chat", payload):
            content = chunk.get("message", {}).get("content", "")
            if content:
                yield content


class TestLLMClient(LLMClient):
    def _render(self, messages: Sequence[LLMMessage]) -> str:
        user_message = ""
        for message in reversed(messages):
            if message.role == "user":
                user_message = message.content
                break
        if user_message:
            return f"test client response: {user_message}"
        return "test client response"

    def complete(self, messages: Sequence[LLMMessage]) -> str:
        return self._render(messages)

    async def acomplete(self, messages: Sequence[LLMMessage]) -> str:
        return self._render(messages)

    async def astream(
        self, messages: Sequence[LLMMessage]
    ) -> AsyncIterator[str]:
        yield self._render(messages)


def get_client() -> LLMClient:
    mode = settings.LLM_MODE

    if mode == "test_client":
        if not settings.IS_RUNNING_PYTESTS:
            raise LLMConfigurationError(
                "LLM_MODE=test_client is only supported during tests"
            )
        return TestLLMClient()

    if mode == "local":
        return TestLLMClient()

    if mode == "ollama":
        return get_ollama_client()

    else:
        raise LLMConfigurationError(
            f"Unsupported LLM_MODE '{mode}'. Only 'local', 'ollama' are supported"
        )


def get_ollama_client() -> OllamaLLMClient:
    base_url = settings.LLM_OLLAMA_URL
    model = settings.LLM_OLLAMA_MODEL
    timeout = settings.LLM_OLLAMA_TIMEOUT

    if not base_url or not model:
        raise LLMConfigurationError(
            "LLM_MODE=ollama requires LLM_OLLAMA_URL and LLM_OLLAMA_MODEL"
        )

    return OllamaLLMClient(
        base_url=base_url,
        model=model,
        timeout=timeout,
    )


RequestsLLMHttpClient = HttpxLLMHttpClient

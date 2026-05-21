from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Callable

from django.conf import settings

import httpx


class LLMConfigurationError(RuntimeError):
    pass


class UnexpectedLLMOutputError(RuntimeError):
    # Typically raised by business-logic
    # More frequent for dumber LLMS
    # used to trigger retry logic
    pass


class ClientFailureError(RuntimeError):
    # Raised when the client fails to complete the request
    # e.g. network error, invalid response, etc.
    # usually is not retried
    # although a circuit breaker pattern might help with this
    pass


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LLMClientSpec:
    mode: str
    label: str
    is_real: bool
    factory: Callable[[], "LLMClient"]


def _message_to_payload(message: LLMMessage) -> dict[str, str]:
    return {"role": message.role, "content": message.content}


class LLMHttpClient(ABC):
    @abstractmethod
    def complete(self, path: str, payload: dict) -> dict:
        raise NotImplementedError


class HttpxLLMHttpClient(LLMHttpClient):
    def __init__(
        self,
        base_url: str,
        timeout: int = 60,
        sync_client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.sync_client = sync_client or httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
        )

    def complete(self, path: str, payload: dict) -> dict:
        try:
            response = self.sync_client.post(
                path,
                json=payload,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise ClientFailureError(
                f"LLM client request failed for {path}"
            ) from exc
        except ValueError as exc:
            raise ClientFailureError(
                f"LLM client returned invalid JSON for {path}"
            ) from exc


class LLMClient(ABC):
    def _prompt_messages(self, prompt: str) -> Sequence[LLMMessage]:
        return [LLMMessage(role="user", content=prompt)]

    def complete_prompt(self, prompt: str) -> str:
        # Convenience method for simple prompt-based interactions
        return self.complete(self._prompt_messages(prompt))

    @abstractmethod
    def complete(self, messages: Sequence[LLMMessage]) -> str:
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

    def _payload(self, messages: Sequence[LLMMessage]) -> dict:
        return {
            "model": self.model,
            "messages": [_message_to_payload(message) for message in messages],
            "stream": False,
        }

    def complete(self, messages: Sequence[LLMMessage]) -> str:
        payload = self._payload(messages)
        response = self.http_client.complete("/api/chat", payload)
        return response.get("message", {}).get("content", "")


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


def _build_test_client() -> LLMClient:
    return TestLLMClient()


def _build_ollama_client() -> LLMClient:
    return get_ollama_client()


LLM_CLIENT_SPECS: dict[str, LLMClientSpec] = {
    "local": LLMClientSpec(
        mode="local",
        label="dummy local client",
        is_real=False,
        factory=_build_test_client,
    ),
    "test_client": LLMClientSpec(
        mode="test_client",
        label="test client",
        is_real=False,
        factory=_build_test_client,
    ),
    "ollama": LLMClientSpec(
        mode="ollama",
        label="ollama",
        is_real=True,
        factory=_build_ollama_client,
    ),
}


def get_client_spec(mode: str) -> LLMClientSpec:
    try:
        return LLM_CLIENT_SPECS[mode]
    except KeyError as exc:
        available_modes = ", ".join(sorted(LLM_CLIENT_SPECS))
        raise LLMConfigurationError(
            f"Unsupported LLM_MODE '{mode}'. Supported modes are: {available_modes}"
        ) from exc


def get_real_client_modes() -> tuple[str, ...]:
    return tuple(
        spec.mode for spec in LLM_CLIENT_SPECS.values() if spec.is_real
    )


def is_real_client_mode(mode: str) -> bool:
    return get_client_spec(mode).is_real


def get_client() -> LLMClient:
    mode = settings.LLM_MODE

    if mode == "test_client":
        if not settings.IS_RUNNING_PYTESTS:
            raise LLMConfigurationError(
                "LLM_MODE=test_client is only supported during tests"
            )
    spec = get_client_spec(mode)
    return spec.factory()


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

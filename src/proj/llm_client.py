from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import BinaryIO, Callable

from django.conf import settings

import httpx
import pydantic
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

from shortcuts import logger


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


class LanguageModelSpec(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(from_attributes=True)

    key: str
    deployment: str
    has_multimodal: bool = False


@dataclass(frozen=True)
class LLMClientSpec:
    mode: str
    label: str
    is_real: bool
    factory: Callable[[], "LLMClient"]


def _message_to_payload(message: LLMMessage) -> dict[str, str]:
    return {"role": message.role, "content": message.content}


def _file_to_base64(file: bytes | BinaryIO) -> str:
    if isinstance(file, bytes):
        file_bytes = file
    else:
        if hasattr(file, "open") and getattr(file, "closed", False):
            file.open("rb")

        original_position = None
        if hasattr(file, "tell"):
            original_position = file.tell()

        file_bytes = file.read()

        if original_position is not None and hasattr(file, "seek"):
            file.seek(original_position)

    return base64.b64encode(file_bytes).decode("ascii")


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
            logger.exception(exc)
            raise ClientFailureError(
                f"LLM client request failed for {path}"
            ) from exc
        except ValueError as exc:
            logger.exception(exc)
            raise ClientFailureError(
                f"LLM client returned invalid JSON for {path}"
            ) from exc


class LLMClient(ABC):
    def _prompt_messages(self, prompt: str) -> Sequence[LLMMessage]:
        return [LLMMessage(role="user", content=prompt)]

    def complete_prompt(self, prompt: str, model: LanguageModelSpec) -> str:
        return self.complete(self._prompt_messages(prompt), model)

    def complete_multimodal_prompt(
        self,
        prompt: str,
        files: Sequence[bytes | BinaryIO],
        model: LanguageModelSpec,
    ) -> str:
        model_spec = LanguageModelSpec.model_validate(model)
        if not model_spec.has_multimodal:
            raise LLMConfigurationError(
                f"Language model '{model_spec.key}' does not support multimodal input"
            )
        return self._complete_multimodal_prompt(prompt, files, model_spec)

    @abstractmethod
    def _complete_multimodal_prompt(
        self,
        prompt: str,
        files: Sequence[bytes | BinaryIO],
        model: LanguageModelSpec,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def complete(
        self, messages: Sequence[LLMMessage], model: LanguageModelSpec
    ) -> str:
        raise NotImplementedError


class OllamaLLMClient(LLMClient):
    def __init__(
        self,
        http_client: LLMHttpClient | None = None,
        *,
        base_url: str | None = None,
        timeout: int | None = None,
    ):
        if http_client is None:
            if base_url is None:
                raise LLMConfigurationError(
                    "Ollama client requires base_url configuration"
                )
            http_client = HttpxLLMHttpClient(
                base_url=base_url,
                timeout=timeout or 60,
            )

        self.http_client = http_client

    def _payload(
        self, messages: Sequence[LLMMessage], model: LanguageModelSpec
    ) -> dict:
        return {
            "model": model.key,
            "messages": [_message_to_payload(message) for message in messages],
            "stream": False,
        }

    def _multimodal_payload(
        self,
        prompt: str,
        files: Sequence[bytes | BinaryIO],
        model: LanguageModelSpec,
    ) -> dict:
        return {
            "model": model.key,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [_file_to_base64(file) for file in files],
                }
            ],
            "stream": False,
        }

    def complete(
        self, messages: Sequence[LLMMessage], model: LanguageModelSpec
    ) -> str:
        model_spec = LanguageModelSpec.model_validate(model)
        payload = self._payload(messages, model_spec)
        response = self.http_client.complete("/api/chat", payload)
        return response.get("message", {}).get("content", "")

    def _complete_multimodal_prompt(
        self,
        prompt: str,
        files: Sequence[bytes | BinaryIO],
        model: LanguageModelSpec,
    ) -> str:
        payload = self._multimodal_payload(prompt, files, model)
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

    def complete(
        self, messages: Sequence[LLMMessage], model: LanguageModelSpec
    ) -> str:
        return self._render(messages)

    def _complete_multimodal_prompt(
        self,
        prompt: str,
        files: Sequence[bytes | BinaryIO],
        model: LanguageModelSpec,
    ) -> str:
        return f"{self._render(self._prompt_messages(prompt))} ({len(files)} files)"


class AzureLLMClient(LLMClient):
    def __init__(self, client: AzureOpenAI):
        self.client = client

    def _create_completion(
        self, messages: list[dict], model: LanguageModelSpec
    ):
        try:
            return self.client.chat.completions.create(
                model=model.deployment,
                messages=messages,
            )
        except Exception as exc:
            logger.exception(exc)
            raise ClientFailureError("Azure OpenAI request failed") from exc

    def complete(
        self, messages: Sequence[LLMMessage], model: LanguageModelSpec
    ) -> str:
        model_spec = LanguageModelSpec.model_validate(model)
        response = self._create_completion(
            [_message_to_payload(message) for message in messages], model_spec
        )
        return response.choices[0].message.content or ""

    def _complete_multimodal_prompt(
        self,
        prompt: str,
        files: Sequence[bytes | BinaryIO],
        model: LanguageModelSpec,
    ) -> str:
        content = [{"type": "text", "text": prompt}]
        content.extend(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{_file_to_base64(file)}"
                },
            }
            for file in files
        )
        response = self._create_completion(
            [{"role": "user", "content": content}], model
        )
        return response.choices[0].message.content or ""


def _build_test_client() -> LLMClient:
    return TestLLMClient()


def _build_ollama_client() -> LLMClient:
    return get_ollama_client()


def _build_azure_client() -> LLMClient:
    return get_azure_client()


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
    "azure": LLMClientSpec(
        mode="azure",
        label="Azure OpenAI",
        is_real=True,
        factory=_build_azure_client,
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
    timeout = settings.LLM_OLLAMA_TIMEOUT

    if not base_url:
        raise LLMConfigurationError("LLM_MODE=ollama requires LLM_OLLAMA_URL")

    return OllamaLLMClient(
        base_url=base_url,
        timeout=timeout,
    )


def get_azure_client() -> AzureLLMClient:
    endpoint = settings.AZURE_OPENAI_ENDPOINT
    auth_mode = settings.AZURE_OPENAI_MODE

    if not endpoint:
        raise LLMConfigurationError(
            "LLM_MODE=azure requires AZURE_OPENAI_ENDPOINT"
        )

    client_kwargs = {
        "azure_endpoint": endpoint,
        "api_version": "2025-04-01-preview",
    }
    if auth_mode == "key":
        if not settings.AZURE_OPENAI_API_KEY:
            raise LLMConfigurationError(
                "AZURE_OPENAI_API_KEY is required for key-based auth"
            )
        client_kwargs["api_key"] = settings.AZURE_OPENAI_API_KEY
    elif auth_mode == "entra":
        client_kwargs["azure_ad_token_provider"] = get_bearer_token_provider(
            DefaultAzureCredential(),
            "https://cognitiveservices.azure.com/.default",
        )
    else:
        raise LLMConfigurationError(
            f"Unsupported AZURE_OPENAI_MODE: {auth_mode}. Must be 'key' or 'entra'"
        )

    return AzureLLMClient(AzureOpenAI(**client_kwargs))


RequestsLLMHttpClient = HttpxLLMHttpClient

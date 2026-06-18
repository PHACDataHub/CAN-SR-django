import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import override_settings

import httpx
import pytest

from proj.llm_client import (
    AzureLLMClient,
    ClientFailureError,
    HttpxLLMHttpClient,
    LanguageModelSpec,
    LLMConfigurationError,
    LLMMessage,
    OllamaLLMClient,
    TestLLMClient,
    get_client,
)

pytestmark = pytest.mark.backend


TEXT_MODEL = LanguageModelSpec(
    key="demo", deployment="demo-deployment", has_multimodal=False
)
MULTIMODAL_MODEL = LanguageModelSpec(
    key="demo", deployment="demo-deployment", has_multimodal=True
)


def build_httpx_clients(response_factory):
    transport = httpx.MockTransport(response_factory)
    sync_client = httpx.Client(
        base_url="http://ollama.example",
        transport=transport,
    )
    return sync_client


def test_requests_http_client_posts_expected_payload():
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(200, json={"message": {"content": "hello"}})

    sync_client = build_httpx_clients(handler)
    client = HttpxLLMHttpClient(
        "http://ollama.example", sync_client=sync_client
    )

    payload = {
        "model": "demo",
        "messages": [{"role": "user", "content": "hi"}],
    }
    data = client.complete("/api/chat", payload)

    assert data["message"]["content"] == "hello"
    assert seen["request"].method == "POST"
    assert seen["request"].url.path == "/api/chat"
    assert json.loads(seen["request"].content) == payload


def test_ollama_client_uses_transport_for_complete():
    def handler(request):
        return httpx.Response(200, json={"message": {"content": "reply"}})

    sync_client = build_httpx_clients(handler)
    http_client = HttpxLLMHttpClient(
        "http://ollama.example", sync_client=sync_client
    )
    client = OllamaLLMClient(http_client=http_client)

    result = client.complete(
        [LLMMessage(role="user", content="hello")], TEXT_MODEL
    )

    assert result == "reply"


def test_ollama_client_complete_prompt_uses_single_user_message():
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(200, json={"message": {"content": "reply"}})

    sync_client = build_httpx_clients(handler)
    http_client = HttpxLLMHttpClient(
        "http://ollama.example", sync_client=sync_client
    )
    client = OllamaLLMClient(http_client=http_client)

    result = client.complete_prompt("hello", TEXT_MODEL)

    assert result == "reply"
    assert json.loads(seen["request"].content) == {
        "model": "demo",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": False,
    }


def test_ollama_client_complete_multimodal_prompt_adds_base64_images():
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(200, json={"message": {"content": "reply"}})

    sync_client = build_httpx_clients(handler)
    http_client = HttpxLLMHttpClient(
        "http://ollama.example", sync_client=sync_client
    )
    client = OllamaLLMClient(http_client=http_client)

    result = client.complete_multimodal_prompt(
        "hello", files=[b"image bytes"], model=MULTIMODAL_MODEL
    )

    assert result == "reply"
    assert json.loads(seen["request"].content) == {
        "model": "demo",
        "messages": [
            {
                "role": "user",
                "content": "hello",
                "images": ["aW1hZ2UgYnl0ZXM="],
            }
        ],
        "stream": False,
    }


def test_test_client_complete_multimodal_prompt_reports_file_count():
    client = TestLLMClient()

    result = client.complete_multimodal_prompt(
        "hello", files=[b"1", b"2"], model=MULTIMODAL_MODEL
    )

    assert result == "test client response: hello (2 files)"


def test_multimodal_completion_rejects_text_only_model():
    client = TestLLMClient()

    with pytest.raises(
        LLMConfigurationError, match="does not support multimodal"
    ):
        client.complete_multimodal_prompt(
            "hello", files=[b"1"], model=TEXT_MODEL
        )


def test_requests_http_client_wraps_status_errors():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    sync_client = build_httpx_clients(handler)
    client = HttpxLLMHttpClient(
        "http://ollama.example", sync_client=sync_client
    )

    with pytest.raises(ClientFailureError, match="request failed"):
        client.complete(
            "/api/chat",
            {
                "model": "demo",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )


def test_requests_http_client_wraps_timeout_errors():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    sync_client = build_httpx_clients(handler)
    client = HttpxLLMHttpClient(
        "http://ollama.example", sync_client=sync_client
    )

    with pytest.raises(ClientFailureError, match="request failed"):
        client.complete(
            "/api/chat",
            {
                "model": "demo",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )


def test_get_client_returns_test_client_in_test_mode():
    with override_settings(LLM_MODE="test_client"):
        client = get_client()

    assert isinstance(client, TestLLMClient)


def test_get_client_returns_ollama_client_in_ollama_mode():
    with override_settings(
        LLM_MODE="ollama",
        LLM_OLLAMA_URL="http://ollama.example",
        LLM_OLLAMA_TIMEOUT=30,
    ):
        client = get_client()

    assert isinstance(client, OllamaLLMClient)


def test_get_client_rejects_test_client_mode_outside_pytest():
    # just chasing coverage here, not super useful

    with override_settings(LLM_MODE="test_client", IS_RUNNING_PYTESTS=False):
        try:
            get_client()
        except LLMConfigurationError as exc:
            assert "only supported during tests" in str(exc)
        else:
            raise AssertionError("Expected LLMConfigurationError")


def test_get_client_rejects_unknown_mode():
    with override_settings(LLM_MODE="cloud"):
        try:
            get_client()
        except LLMConfigurationError as exc:
            assert "Unsupported LLM_MODE" in str(exc)
        else:
            raise AssertionError("Expected LLMConfigurationError")


def test_get_ollama_client_requires_explicit_configuration():
    with override_settings(
        LLM_MODE="ollama",
        LLM_OLLAMA_URL="",
        LLM_OLLAMA_TIMEOUT=30,
    ):
        try:
            get_client()
        except LLMConfigurationError as exc:
            assert "requires LLM_OLLAMA_URL" in str(exc)
        else:
            raise AssertionError("Expected LLMConfigurationError")


def test_azure_client_uses_deployment_for_completion():
    sdk_client = MagicMock()
    sdk_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="reply"))]
    )
    client = AzureLLMClient(sdk_client)

    result = client.complete(
        [LLMMessage(role="user", content="hello")], TEXT_MODEL
    )

    assert result == "reply"
    sdk_client.chat.completions.create.assert_called_once_with(
        model="demo-deployment",
        messages=[{"role": "user", "content": "hello"}],
    )


def test_azure_client_builds_multimodal_content():
    sdk_client = MagicMock()
    sdk_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="reply"))]
    )
    client = AzureLLMClient(sdk_client)

    client.complete_multimodal_prompt(
        "describe", files=[b"image bytes"], model=MULTIMODAL_MODEL
    )

    sdk_client.chat.completions.create.assert_called_once_with(
        model="demo-deployment",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,aW1hZ2UgYnl0ZXM="
                        },
                    },
                ],
            }
        ],
    )


def test_get_client_builds_key_authenticated_azure_client():
    with (
        override_settings(
            LLM_MODE="azure",
            AZURE_OPENAI_MODE="key",
            AZURE_OPENAI_API_KEY="secret",
            AZURE_OPENAI_ENDPOINT="https://azure.example",
        ),
        patch("proj.llm_client.AzureOpenAI") as sdk_class,
    ):
        client = get_client()

    assert isinstance(client, AzureLLMClient)
    sdk_class.assert_called_once_with(
        azure_endpoint="https://azure.example",
        api_version="2025-04-01-preview",
        api_key="secret",
    )


def test_get_client_builds_entra_authenticated_azure_client():
    token_provider = object()
    with (
        override_settings(
            LLM_MODE="azure",
            AZURE_OPENAI_MODE="entra",
            AZURE_OPENAI_API_KEY="",
            AZURE_OPENAI_ENDPOINT="https://azure.example",
        ),
        patch("proj.llm_client.DefaultAzureCredential") as credential_class,
        patch(
            "proj.llm_client.get_bearer_token_provider",
            return_value=token_provider,
        ),
        patch("proj.llm_client.AzureOpenAI") as sdk_class,
    ):
        get_client()

    credential_class.assert_called_once_with()
    sdk_class.assert_called_once_with(
        azure_endpoint="https://azure.example",
        api_version="2025-04-01-preview",
        azure_ad_token_provider=token_provider,
    )


@pytest.mark.parametrize(
    ("settings_values", "error"),
    [
        (
            {
                "AZURE_OPENAI_MODE": "key",
                "AZURE_OPENAI_API_KEY": "secret",
                "AZURE_OPENAI_ENDPOINT": "",
            },
            "requires AZURE_OPENAI_ENDPOINT",
        ),
        (
            {
                "AZURE_OPENAI_MODE": "key",
                "AZURE_OPENAI_API_KEY": "",
                "AZURE_OPENAI_ENDPOINT": "https://azure.example",
            },
            "API_KEY is required",
        ),
        (
            {
                "AZURE_OPENAI_MODE": "invalid",
                "AZURE_OPENAI_API_KEY": "",
                "AZURE_OPENAI_ENDPOINT": "https://azure.example",
            },
            "Unsupported AZURE_OPENAI_MODE",
        ),
    ],
)
def test_get_azure_client_validates_configuration(settings_values, error):
    with override_settings(LLM_MODE="azure", **settings_values):
        with pytest.raises(LLMConfigurationError, match=error):
            get_client()

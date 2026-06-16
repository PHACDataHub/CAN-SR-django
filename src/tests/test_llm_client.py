import json

from django.test import override_settings

import httpx
import pytest

from proj.llm_client import (
    ClientFailureError,
    HttpxLLMHttpClient,
    LLMConfigurationError,
    LLMMessage,
    OllamaLLMClient,
    TestLLMClient,
    get_client,
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
    client = OllamaLLMClient(http_client=http_client, model="demo")

    result = client.complete([LLMMessage(role="user", content="hello")])

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
    client = OllamaLLMClient(http_client=http_client, model="demo")

    result = client.complete_prompt("hello")

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
    client = OllamaLLMClient(http_client=http_client, model="demo")

    result = client.complete_multimodal_prompt("hello", files=[b"image bytes"])

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

    result = client.complete_multimodal_prompt("hello", files=[b"1", b"2"])

    assert result == "test client response: hello (2 files)"


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
        LLM_OLLAMA_MODEL="demo",
        LLM_OLLAMA_TIMEOUT=30,
    ):
        client = get_client()

    assert isinstance(client, OllamaLLMClient)
    assert client.model == "demo"


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
        LLM_OLLAMA_MODEL="",
        LLM_OLLAMA_TIMEOUT=30,
    ):
        try:
            get_client()
        except LLMConfigurationError as exc:
            assert "requires LLM_OLLAMA_URL and LLM_OLLAMA_MODEL" in str(exc)
        else:
            raise AssertionError("Expected LLMConfigurationError")

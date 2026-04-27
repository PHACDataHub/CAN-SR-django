import json

from django.test import override_settings

import httpx
from asgiref.sync import async_to_sync

from proj.llm_client import (
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
    async_client = httpx.AsyncClient(
        base_url="http://ollama.example",
        transport=transport,
    )
    return sync_client, async_client


def test_requests_http_client_posts_expected_payload():
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(200, json={"message": {"content": "hello"}})

    sync_client, async_client = build_httpx_clients(handler)
    client = HttpxLLMHttpClient(
        "http://ollama.example",
        sync_client=sync_client,
        async_client=async_client,
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


def test_requests_http_client_streams_json_chunks():
    body = b'{"message":{"content":"hel"}}\n{"message":{"content":"lo"}}\n'

    def handler(request):
        return httpx.Response(200, content=body)

    sync_client, async_client = build_httpx_clients(handler)
    client = HttpxLLMHttpClient(
        "http://ollama.example",
        sync_client=sync_client,
        async_client=async_client,
    )

    chunks = list(client.stream("/api/chat", {"model": "demo"}))

    assert chunks == [
        {"message": {"content": "hel"}},
        {"message": {"content": "lo"}},
    ]


def test_requests_http_client_async_streams_json_chunks():
    body = b'{"message":{"content":"hel"}}\n{"message":{"content":"lo"}}\n'

    def handler(request):
        return httpx.Response(200, content=body)

    sync_client, async_client = build_httpx_clients(handler)
    client = HttpxLLMHttpClient(
        "http://ollama.example",
        sync_client=sync_client,
        async_client=async_client,
    )

    async def consume():
        items = []
        async for item in client.astream("/api/chat", {"model": "demo"}):
            items.append(item)
        return items

    chunks = async_to_sync(consume)()

    assert chunks == [
        {"message": {"content": "hel"}},
        {"message": {"content": "lo"}},
    ]


def test_ollama_client_uses_transport_for_complete():
    def handler(request):
        return httpx.Response(200, json={"message": {"content": "reply"}})

    sync_client, async_client = build_httpx_clients(handler)
    http_client = HttpxLLMHttpClient(
        "http://ollama.example",
        sync_client=sync_client,
        async_client=async_client,
    )
    client = OllamaLLMClient(http_client=http_client, model="demo")

    result = client.complete([LLMMessage(role="user", content="hello")])

    assert result == "reply"


def test_ollama_client_async_complete_uses_transport():
    def handler(request):
        return httpx.Response(200, json={"message": {"content": "reply"}})

    sync_client, async_client = build_httpx_clients(handler)
    http_client = HttpxLLMHttpClient(
        "http://ollama.example",
        sync_client=sync_client,
        async_client=async_client,
    )
    client = OllamaLLMClient(http_client=http_client, model="demo")

    async def consume():
        return await client.acomplete(
            [LLMMessage(role="user", content="hello")]
        )

    assert async_to_sync(consume)() == "reply"


def test_ollama_client_streams_content():
    body = b'{"message":{"content":"hel"}}\n{"message":{"content":"lo"}}\n'

    def handler(request):
        return httpx.Response(200, content=body)

    sync_client, async_client = build_httpx_clients(handler)
    http_client = HttpxLLMHttpClient(
        "http://ollama.example",
        sync_client=sync_client,
        async_client=async_client,
    )
    client = OllamaLLMClient(http_client=http_client, model="demo")

    async def consume():
        items = []
        async for item in client.astream(
            [LLMMessage(role="user", content="hello")]
        ):
            items.append(item)
        return items

    assert async_to_sync(consume)() == ["hel", "lo"]


def test_get_client_returns_test_client_in_test_mode():
    with override_settings(LLM_MODE="test_client"):
        client = get_client()

    assert isinstance(client, TestLLMClient)


def test_get_client_returns_ollama_client_in_local_mode():
    with override_settings(
        LLM_MODE="local",
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

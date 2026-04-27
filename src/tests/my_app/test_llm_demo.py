from django.test import override_settings
from django.urls import reverse

from asgiref.sync import async_to_sync


def test_llm_demo_page_renders_form_and_shell(admin_client):
    response = admin_client.get(reverse("llm_demo"))

    assert response.status_code == 200

    content = response.content.decode()

    assert "LLM demo" in content
    assert "Stream response" in content
    assert reverse("llm_demo_shell") in content
    assert "llm-demo-shell" in content


def test_llm_demo_shell_view_returns_streaming_shell(admin_client):
    response = admin_client.get(reverse("llm_demo_shell"), {"prompt": "hello"})

    assert response.status_code == 200

    content = response.content.decode()

    assert "llm-demo-stream-shell" in content
    assert reverse("llm_demo_stream") in content
    assert "stream_shell.js" in content
    assert "hello" in content


def test_llm_demo_shell_view_without_prompt_returns_placeholder(admin_client):
    response = admin_client.get(reverse("llm_demo_shell"))

    assert response.status_code == 200
    assert "Submit a prompt" in response.content.decode()


@override_settings(LLM_MODE="test_client")
def test_llm_demo_stream_view_streams_sse_chunks(admin_client):
    response = admin_client.get(
        reverse("llm_demo_stream"), {"prompt": "hello"}
    )

    assert response.status_code == 200
    assert response.streaming
    assert response["Content-Type"].startswith("text/event-stream")

    async def collect():
        chunks = []
        async for chunk in response.streaming_content:
            chunks.append(chunk.decode())
        return chunks

    content = "".join(async_to_sync(collect)())

    assert "data: test client response: hello" in content
    assert "data: [DONE]" in content

import json
from io import StringIO
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import override_settings

from my_app.management.commands.check_llm import (
    EXPECTED_SELECTED,
    SMOKE_TEST_PROMPT,
)


def test_check_llm_rejects_dummy_client_mode():
    with override_settings(LLM_MODE="local"):
        try:
            call_command("check_llm", verbosity=0)
        except CommandError as exc:
            assert "requires a real client" in str(exc)
        else:
            raise AssertionError("Expected CommandError")


@override_settings(LLM_MODE="ollama")
def test_check_llm_runs_smoke_test_against_real_client():
    class FakeHttpxLLMHttpClient:
        def __init__(
            self,
            base_url,
            timeout=60,
            sync_client=None,
        ):
            self.base_url = base_url
            self.timeout = timeout
            self.sync_client = sync_client

        def complete(self, path, payload):
            assert path == "/api/chat"
            assert payload["model"] == "demo"
            assert payload["messages"] == [
                {"role": "user", "content": SMOKE_TEST_PROMPT}
            ]
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "selected": EXPECTED_SELECTED,
                            "explanation": "I can follow the JSON-only instructions.",
                            "confidence": 0.91,
                        }
                    )
                }
            }

    stdout = StringIO()

    with override_settings(
        LLM_MODE="ollama",
        LLM_OLLAMA_URL="http://ollama.example",
        LLM_OLLAMA_MODEL="demo",
        LLM_OLLAMA_TIMEOUT=30,
    ):
        with (
            patch(
                "proj.llm_client.HttpxLLMHttpClient",
                FakeHttpxLLMHttpClient,
            ),
        ):
            call_command("check_llm", stdout=stdout, verbosity=0)

    assert "LLM check passed for mode=ollama" in stdout.getvalue()


@override_settings(LLM_MODE="ollama")
def test_check_llm_rejects_unexpected_selected_option():
    class FakeHttpxLLMHttpClient:
        def __init__(
            self,
            base_url,
            timeout=60,
            sync_client=None,
        ):
            pass

        def complete(self, path, payload):
            assert payload["messages"] == [
                {"role": "user", "content": SMOKE_TEST_PROMPT}
            ]
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "selected": "Exclude",
                            "explanation": "The response is well-formed but not expected.",
                            "confidence": 0.22,
                        }
                    )
                }
            }

    with override_settings(
        LLM_MODE="ollama",
        LLM_OLLAMA_URL="http://ollama.example",
        LLM_OLLAMA_MODEL="demo",
        LLM_OLLAMA_TIMEOUT=30,
    ):
        with patch(
            "proj.llm_client.HttpxLLMHttpClient",
            FakeHttpxLLMHttpClient,
        ):
            try:
                call_command("check_llm", verbosity=0)
            except CommandError as exc:
                assert "unexpected answer" in str(exc)
            else:
                raise AssertionError("Expected CommandError")

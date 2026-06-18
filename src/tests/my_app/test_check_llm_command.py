import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import override_settings

import pytest

from my_app.management.commands.check_llm import (
    EXPECTED_SELECTED,
    SMOKE_TEST_PROMPT,
)

pytestmark = pytest.mark.backend


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
            assert payload["model"] == "qwen3:1.7b"
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
def test_check_llm_reports_azure_configuration_errors(settings_values, error):
    with override_settings(LLM_MODE="azure", **settings_values):
        with pytest.raises(CommandError, match=error):
            call_command("check_llm", verbosity=0)


def test_check_llm_runs_smoke_test_with_azure_key_authentication():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "selected": EXPECTED_SELECTED,
                            "explanation": "Valid JSON response.",
                            "confidence": 0.95,
                        }
                    )
                )
            )
        ]
    )
    stdout = StringIO()

    with (
        override_settings(
            LLM_MODE="azure",
            AZURE_OPENAI_MODE="key",
            AZURE_OPENAI_API_KEY="secret",
            AZURE_OPENAI_ENDPOINT="https://azure.example",
        ),
        patch("proj.llm_client.AzureOpenAI") as sdk_class,
    ):
        sdk_class.return_value.chat.completions.create.return_value = response
        call_command("check_llm", stdout=stdout, verbosity=0)

    assert "LLM check passed for mode=azure" in stdout.getvalue()
    sdk_class.return_value.chat.completions.create.assert_called_once_with(
        model="gpt-5-mini",
        messages=[{"role": "user", "content": SMOKE_TEST_PROMPT}],
    )

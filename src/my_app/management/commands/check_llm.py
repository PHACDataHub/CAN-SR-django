"""
This command doubles as 2 checks in one
1. checking configuration and connection
2. checking capability (stronger check)
    - some dumber local models will pass/fail this inconsistently, you can try several times

Most of the time you're just checking config and connection. A failure
"""

from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import pydantic

from proj.llm_client import (
    LLMConfigurationError,
    get_client,
    get_client_spec,
    get_real_client_modes,
)

from my_app.models import LanguageModel
from shortcuts import logger

SMOKE_TEST_PROMPT = """
You are a strict capability check for an LLM client.

Return only a raw JSON object with these keys:
- "selected": choose exactly one of the options listed below
- "explanation": a brief, non-empty explanation
- "confidence": a float between 0 and 1 inclusive

Question:
Can you follow instructions to return valid JSON and select the expected option?

Options:
Include
Exclude

Choose "Include" if you can comply with the requested JSON format, produce a confidence float, and select one of the provided options. Choose "Exclude" otherwise.

Return only JSON, no markdown, no surrounding text.
""".strip()

EXPECTED_SELECTED = "Include"


class SmokeTestResponse(pydantic.BaseModel):
    explanation: str
    confidence: pydantic.confloat(ge=0.0, le=1.0)
    selected: str


def parse_smoke_test_response(raw_response: str) -> SmokeTestResponse:
    return SmokeTestResponse(**json.loads(raw_response))


def validate_smoke_test_response(
    json_response: dict,
    expected_selected: str = EXPECTED_SELECTED,
) -> SmokeTestResponse:
    parsed_response = parse_smoke_test_response(json.dumps(json_response))
    if parsed_response.selected != expected_selected:
        raise ValueError(
            "LLM returned an unexpected answer "
            f"'{parsed_response.selected}', expected '{expected_selected}'"
        )
    return parsed_response


class Command(BaseCommand):
    help = "Check the configured LLM client and run a capability smoke test."

    def handle(self, *args, **options):
        mode = settings.LLM_MODE

        try:
            client_spec = get_client_spec(mode)
        except LLMConfigurationError as exc:
            raise CommandError(str(exc)) from exc

        if not client_spec.is_real:
            real_modes = ", ".join(get_real_client_modes())
            raise CommandError(
                "LLM_MODE='%s' uses the %s; this command requires a real client "
                "(currently: %s)" % (mode, client_spec.label, real_modes)
            )

        try:
            client = get_client()
            model = LanguageModel.get_default_model()
            if model is None:
                raise LLMConfigurationError(
                    f"No active default language model configured for {mode}"
                )
            raw_response = client.complete_prompt(SMOKE_TEST_PROMPT, model)
            logger.info(
                "\n\n✅ 1/3 configuration and connection check passed  \n\n"
            )
            json_response = json.loads(raw_response)
            logger.info("\n\n✅ 2/3 LLM returning single JSON value \n\n")
            parsed_response = validate_smoke_test_response(json_response)
            logger.info(
                "\n\n✅ 3/3 format, capabilities, semantics & type checks passed \n\n"
            )
        except Exception as exc:
            raise CommandError(f"LLM smoke test failed: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                "LLM check passed for mode=%s: selected=%s confidence=%.3f"
                % (mode, parsed_response.selected, parsed_response.confidence)
            )
        )

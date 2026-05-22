import json
from unittest.mock import MagicMock, patch

from django.test import override_settings

import pytest

from my_app.model_factories import ReviewFactory
from my_app.models import (
    Citation,
    CitationDataset,
    CitationDatasetColumn,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
)
from my_app.prompts.screening_prompt import (
    L1ScreeningPromptBuilder,
    UnexpectedLLMOutputError,
    get_l1_screening_results,
)


def _build_screening_prompt_context():
    sr = ReviewFactory()
    dataset = CitationDataset.objects.create(review=sr)
    col1 = CitationDatasetColumn.objects.create(
        dataset=dataset, name="custom_col1"
    )
    col2 = CitationDatasetColumn.objects.create(
        dataset=dataset, name="custom_col2"
    )

    dataset.screening_columns.set([col1])

    row = Citation.objects.create(
        dataset=dataset,
        title="Test Title",
        abstract="Test Abstract",
        data={
            "custom_col1": "Custom Value 1",
            "custom_col2": "Custom Value 2",
        },
        order=1,
    )

    question = L1ScreeningQuestion.objects.create(
        review=sr, question_text="Is this relevant?"
    )
    include_option = L1ScreeningQuestionOption.objects.create(
        question=question, option_text="Include", option_value="yes_def"
    )
    exclude_option = L1ScreeningQuestionOption.objects.create(
        question=question, option_text="No", option_value="no_def"
    )

    return sr, dataset, row, question, include_option, exclude_option


def test_screening_prompt_builder():
    _, _, row, question, _, _ = _build_screening_prompt_context()

    prompt_builder = L1ScreeningPromptBuilder(question=question, citation=row)
    prompt_args = prompt_builder.get_screening_prompt_args()

    assert prompt_args.question == "Is this relevant?"

    assert "Title: Test Title" in prompt_args.citation
    assert "Abstract: Test Abstract" in prompt_args.citation
    assert "custom_col1: Custom Value 1" in prompt_args.citation
    assert "custom_col2" not in prompt_args.citation
    assert "Custom Value 2" not in prompt_args.citation

    assert "0. Include" in prompt_args.options
    assert "1. No" in prompt_args.options

    assert "<Include>\nyes_def\n</Include>" in prompt_args.definitions
    assert "<No>\nno_def\n</No>" in prompt_args.definitions

    prompt_str = prompt_builder.build_str()
    assert "Is this relevant?" in prompt_str


@override_settings(HAS_LLM=True)
def test_get_l1_screening_results_returns_exact_matching_option():
    _, _, row, question, include_option, _ = _build_screening_prompt_context()

    client = MagicMock()
    client.complete_prompt.return_value = json.dumps(
        {
            "selected": "Include",
            "explanation": "The citation matches the inclusion criteria.",
            "confidence": 0.88,
        }
    )

    with patch(
        "my_app.prompts.screening_prompt.get_client", return_value=client
    ):
        result = get_l1_screening_results(question, row)

    assert result.selected == include_option
    assert result.explanation == "The citation matches the inclusion criteria."
    assert result.confidence == 0.88
    client.complete_prompt.assert_called_once()


@override_settings(HAS_LLM=True)
def test_get_l1_screening_results_raises_when_json_is_invalid():
    _, _, row, question, _, _ = _build_screening_prompt_context()

    client = MagicMock()
    client.complete_prompt.return_value = "{not valid json}"

    with patch(
        "my_app.prompts.screening_prompt.get_client", return_value=client
    ):
        with pytest.raises(UnexpectedLLMOutputError, match="invalid JSON"):
            get_l1_screening_results(question, row)


@override_settings(HAS_LLM=True)
def test_get_l1_screening_results_raises_when_selected_option_does_not_match():
    _, _, row, question, _, _ = _build_screening_prompt_context()

    client = MagicMock()
    client.complete_prompt.return_value = json.dumps(
        {
            "selected": "Unknown",
            "explanation": "No match.",
            "confidence": 0.1,
        }
    )

    with patch(
        "my_app.prompts.screening_prompt.get_client", return_value=client
    ):
        with pytest.raises(
            UnexpectedLLMOutputError,
            match="doesn't match available options",
        ):
            get_l1_screening_results(question, row)


@override_settings(HAS_LLM=True)
def test_get_l1_screening_results_raises_on_pydantic_validation_error():
    _, _, row, question, _, _ = _build_screening_prompt_context()

    client = MagicMock()
    client.complete_prompt.return_value = json.dumps(
        {
            "selected": "Include",
            "explanation": "The citation matches the inclusion criteria.",
            "confidence": 1.5,
        }
    )

    with patch(
        "my_app.prompts.screening_prompt.get_client", return_value=client
    ):
        with pytest.raises(UnexpectedLLMOutputError):
            get_l1_screening_results(question, row)

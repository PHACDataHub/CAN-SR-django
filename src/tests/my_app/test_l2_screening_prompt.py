import json
from unittest.mock import MagicMock, patch

from django.test import override_settings

import pytest

from my_app.model_factories import ReviewFactory, UserFactory
from my_app.models import (
    Citation,
    CitationDataset,
    Document,
    DocumentMetadata,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
)
from my_app.prompts.l2_screening_prompt import (
    L2ScreeningPromptBuilder,
    UnexpectedLLMOutputError,
    get_l2_screening_results,
)


def _build_screening_prompt_context():
    sr = ReviewFactory()
    dataset = CitationDataset.objects.create(review=sr)

    row = Citation.objects.create(
        dataset=dataset,
        title="Test Title",
        abstract="Test Abstract",
        data={},
        order=1,
    )

    document = Document.objects.create(
        document_type="pdf",
        file="documents/example.pdf",
        uploaded_by=UserFactory(),
    )
    metadata_record = DocumentMetadata.objects.create(
        document=document,
        coordinates=[
            {
                "type": "s",
                "text": "First sentence.",
            },
            {
                "type": "s",
                "text": "First sentence.",
            },
            {
                "type": "s",
                "text": "Second sentence.",
            },
        ],
    )

    question = L2ScreeningQuestion.objects.create(
        review=sr, question_text="Is this relevant?"
    )
    include_option = L2ScreeningQuestionOption.objects.create(
        question=question, option_text="Include", option_value="yes_def"
    )
    exclude_option = L2ScreeningQuestionOption.objects.create(
        question=question, option_text="No", option_value="no_def"
    )

    return (
        sr,
        dataset,
        row,
        metadata_record,
        question,
        include_option,
        exclude_option,
    )


def test_screening_prompt_builder():
    _, _, row, metadata_record, question, *options = (
        _build_screening_prompt_context()
    )

    prompt_builder = L2ScreeningPromptBuilder(
        question=question,
        options=options,
        citation=row,
        metadata_record=metadata_record,
    )
    prompt_args = prompt_builder.get_screening_prompt_args()

    assert prompt_args.question == "Is this relevant?"

    assert prompt_args.fulltext == (
        "[0] First sentence.\n\n[1] Second sentence."
    )
    assert "0. Include" in prompt_args.options
    assert "1. No" in prompt_args.options

    assert "<Include>\nyes_def\n</Include>" in prompt_args.definitions
    assert "<No>\nno_def\n</No>" in prompt_args.definitions

    assert prompt_args.tables == "(none)"
    assert prompt_args.figures == "(none)"

    prompt_str = prompt_builder.build_str()
    assert "Is this relevant?" in prompt_str
    assert "[0] First sentence." in prompt_str


@override_settings(HAS_LLM=True)
def test_get_l2_screening_results_returns_exact_matching_option():
    _, _, row, metadata_record, question, include_option, exclude_option = (
        _build_screening_prompt_context()
    )

    client = MagicMock()
    client.complete_prompt.return_value = json.dumps(
        {
            "selected": "Include",
            "explanation": "The citation matches the inclusion criteria.",
            "confidence": 0.88,
            "evidence_sentences": [0, 1],
            "evidence_tables": [2],
            "evidence_figures": [3],
        }
    )

    with patch(
        "my_app.prompts.l2_screening_prompt.get_client", return_value=client
    ):
        result = get_l2_screening_results(
            question,
            [include_option, exclude_option],
            row,
            metadata_record,
        )

    assert result.selected == include_option
    assert result.explanation == "The citation matches the inclusion criteria."
    assert result.confidence == 0.88
    assert result.evidence_sentences == [0, 1]
    assert result.evidence_tables == [2]
    assert result.evidence_figures == [3]
    client.complete_prompt.assert_called_once()


@override_settings(HAS_LLM=True)
def test_get_l2_screening_results_raises_when_json_is_invalid():
    _, _, row, metadata_record, question, *options = (
        _build_screening_prompt_context()
    )

    client = MagicMock()
    client.complete_prompt.return_value = "{not valid json}"

    with patch(
        "my_app.prompts.l2_screening_prompt.get_client", return_value=client
    ):
        with pytest.raises(UnexpectedLLMOutputError, match="invalid JSON"):
            get_l2_screening_results(question, options, row, metadata_record)


@override_settings(HAS_LLM=True)
def test_get_l2_screening_results_raises_when_selected_option_does_not_match():
    _, _, row, metadata_record, question, *options = (
        _build_screening_prompt_context()
    )

    client = MagicMock()
    client.complete_prompt.return_value = json.dumps(
        {
            "selected": "Unknown",
            "explanation": "No match.",
            "confidence": 0.1,
            "evidence_sentences": [],
            "evidence_tables": [],
            "evidence_figures": [],
        }
    )

    with patch(
        "my_app.prompts.l2_screening_prompt.get_client", return_value=client
    ):
        with pytest.raises(
            UnexpectedLLMOutputError,
            match="doesn't match available options",
        ):
            get_l2_screening_results(question, options, row, metadata_record)


@override_settings(HAS_LLM=True)
def test_get_l2_screening_results_raises_on_pydantic_validation_error():
    _, _, row, metadata_record, question, *options = (
        _build_screening_prompt_context()
    )

    client = MagicMock()
    client.complete_prompt.return_value = json.dumps(
        {
            "selected": "Include",
            "explanation": "The citation matches the inclusion criteria.",
            "confidence": 1.5,
            "evidence_sentences": [0],
            "evidence_tables": [],
            "evidence_figures": [],
        }
    )

    with patch(
        "my_app.prompts.l2_screening_prompt.get_client", return_value=client
    ):
        with pytest.raises(UnexpectedLLMOutputError):
            get_l2_screening_results(question, options, row, metadata_record)

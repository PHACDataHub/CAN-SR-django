import json
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

import pytest

from my_app.model_factories import ReviewFactory
from my_app.models import (
    Citation,
    CitationDataset,
    Document,
    DocumentFigure,
    DocumentTable,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    TextExtractionResult,
)
from my_app.prompts.l2_screening_prompt import (
    L2ScreeningPromptBuilder,
    UnexpectedLLMOutputError,
    get_l2_screening_results,
)

pytestmark = [pytest.mark.backend, pytest.mark.l2_screening]


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
        file="documents/example.pdf",
    )
    row.document = document
    row.save(update_fields=["document"])
    text_extraction_result = TextExtractionResult.objects.create(
        document=document,
        status=TextExtractionResult.TextExtractionStatus.COMPLETED,
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
        text_extraction_result,
        question,
        include_option,
        exclude_option,
    )


def test_screening_prompt_builder():
    _, _, row, text_extraction_result, question, *options = (
        _build_screening_prompt_context()
    )

    prompt_builder = L2ScreeningPromptBuilder(
        question=question,
        options=options,
        citation=row,
        text_extraction_result=text_extraction_result,
        tables=[],
        figures=[],
    )
    prompt_args = prompt_builder.get_screening_prompt_args()

    assert prompt_args.question == "Is this relevant?"

    assert prompt_args.fulltext == (
        "[0] First sentence.\n\n[1] Second sentence."
    )
    assert "'Include'" in prompt_args.options
    assert "0. 'Include'" not in prompt_args.options
    assert "'No'" in prompt_args.options
    assert "1. 'No'" not in prompt_args.options

    assert "<Include>\nyes_def\n</Include>" in prompt_args.definitions
    assert "<No>\nno_def\n</No>" in prompt_args.definitions

    assert prompt_args.tables == "(none)"
    assert prompt_args.figures == "(none)"

    prompt_str = prompt_builder.build_str(prompt_args)
    assert "Is this relevant?" in prompt_str
    assert "[0] First sentence." in prompt_str


def test_screening_prompt_builder_includes_tables_and_figures(tmp_path):
    _, _, row, text_extraction_result, question, *options = (
        _build_screening_prompt_context()
    )
    document = row.document

    with override_settings(MEDIA_ROOT=tmp_path):
        table = DocumentTable.objects.create(
            document=document,
            index=1,
            caption="Baseline characteristics",
            table_markdown="| Group | Count |\n| --- | --- |\n| A | 12 |",
        )
        figure = DocumentFigure.objects.create(
            document=document,
            index=2,
            caption="Participant flow",
            file=SimpleUploadedFile(
                "figure.png", b"figure bytes", content_type="image/png"
            ),
        )

        prompt_builder = L2ScreeningPromptBuilder(
            question=question,
            options=options,
            citation=row,
            text_extraction_result=text_extraction_result,
            tables=[table],
            figures=[figure],
        )
        prompt_args = prompt_builder.get_screening_prompt_args()

        assert (
            "Table 1  caption: Baseline characteristics" in prompt_args.tables
        )
        assert "| A | 12 |" in prompt_args.tables
        assert (
            "Figure [F2] caption: Participant flow (see attached image F2)"
            in prompt_args.figures
        )
        assert len(prompt_args.figure_image_files) == 1
        assert prompt_args.figure_image_files[0].read() == b"figure bytes"


@override_settings(HAS_LLM=True)
def test_get_l2_screening_results_returns_exact_matching_option():
    (
        _,
        _,
        row,
        text_extraction_result,
        question,
        include_option,
        exclude_option,
    ) = _build_screening_prompt_context()

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
            text_extraction_result,
            [],
            [],
        )

    assert result.selected == include_option
    assert result.explanation == "The citation matches the inclusion criteria."
    assert result.confidence == 0.88
    assert result.evidence_sentences == [0, 1]
    assert result.evidence_tables == [2]
    assert result.evidence_figures == [3]
    client.complete_prompt.assert_called_once()


@override_settings(HAS_LLM=True)
def test_get_l2_screening_results_sends_figures_as_multimodal_files(tmp_path):
    (
        _,
        _,
        row,
        text_extraction_result,
        question,
        include_option,
        exclude_option,
    ) = _build_screening_prompt_context()

    with override_settings(MEDIA_ROOT=tmp_path):
        figure = DocumentFigure.objects.create(
            document=row.document,
            index=1,
            caption="Outcome figure",
            file=SimpleUploadedFile(
                "figure.png", b"figure bytes", content_type="image/png"
            ),
        )

        client = MagicMock()
        client.complete_multimodal_prompt.return_value = json.dumps(
            {
                "selected": "Include",
                "explanation": "The figure supports inclusion.",
                "confidence": 0.72,
                "evidence_sentences": [0],
                "evidence_tables": [],
                "evidence_figures": [1],
            }
        )

        with patch(
            "my_app.prompts.l2_screening_prompt.get_client",
            return_value=client,
        ):
            result = get_l2_screening_results(
                question,
                [include_option, exclude_option],
                row,
                text_extraction_result,
                [],
                [figure],
            )

    assert result.selected == include_option
    assert result.evidence_figures == [1]
    client.complete_prompt.assert_not_called()
    client.complete_multimodal_prompt.assert_called_once()
    _, kwargs = client.complete_multimodal_prompt.call_args
    assert kwargs["files"] == [figure.file]


@override_settings(HAS_LLM=True)
def test_get_l2_screening_results_raises_when_json_is_invalid():
    _, _, row, text_extraction_result, question, *options = (
        _build_screening_prompt_context()
    )

    client = MagicMock()
    client.complete_prompt.return_value = "{not valid json}"

    with patch(
        "my_app.prompts.l2_screening_prompt.get_client", return_value=client
    ):
        with pytest.raises(UnexpectedLLMOutputError, match="invalid JSON"):
            get_l2_screening_results(
                question, options, row, text_extraction_result, [], []
            )


@override_settings(HAS_LLM=True)
def test_get_l2_screening_results_raises_when_selected_option_does_not_match():
    _, _, row, text_extraction_result, question, *options = (
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
            get_l2_screening_results(
                question, options, row, text_extraction_result, [], []
            )


@override_settings(HAS_LLM=True)
def test_get_l2_screening_results_raises_on_pydantic_validation_error():
    _, _, row, text_extraction_result, question, *options = (
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
            get_l2_screening_results(
                question, options, row, text_extraction_result, [], []
            )

import json
from unittest.mock import MagicMock, patch, sentinel

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
    Parameter,
    ParameterOption,
    TextExtractionResult,
)
from my_app.prompts.parameter_extraction_prompt import (
    ParameterExtractionPromptBuilder,
    UnexpectedLLMOutputError,
    build_parameter_extraction_response_schema,
    get_parameter_extraction_results,
)

pytestmark = [pytest.mark.backend]


def _build_parameter_extraction_prompt_context():
    review = ReviewFactory()
    dataset = CitationDataset.objects.create(review=review)

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

    parameter = Parameter.objects.create(
        review=review,
        name="Dose",
        description="The administered dose, including units.",
    )

    return row, text_extraction_result, parameter


def test_parameter_extraction_prompt_builder():
    row, text_extraction_result, parameter = (
        _build_parameter_extraction_prompt_context()
    )

    prompt_builder = ParameterExtractionPromptBuilder(
        parameter=parameter,
        citation=row,
        text_extraction_result=text_extraction_result,
        tables=[],
        figures=[],
    )
    prompt_args = prompt_builder.get_prompt_args()

    assert prompt_args.parameter_name == "Dose"
    assert (
        prompt_args.parameter_description
        == "The administered dose, including units."
    )
    assert prompt_args.fulltext == (
        "[0] First sentence.\n\n[1] Second sentence."
    )
    assert prompt_args.tables == "(none)"
    assert prompt_args.figures == "(none)"
    assert prompt_args.has_tables is False
    assert prompt_args.has_figures is False
    assert prompt_args.figure_image_files == []

    prompt_str = prompt_builder.build_str(prompt_args)
    assert "- Parameter name: Dose" in prompt_str
    assert "The administered dose, including units." in prompt_str
    assert "[0] First sentence." in prompt_str
    assert "Units and reporting instructions:" not in prompt_str
    assert "Calculation instructions:" not in prompt_str
    assert "Available options" not in prompt_str
    assert "Select exactly one of the option names below" not in prompt_str
    assert '"selected_option"' not in prompt_str
    assert '"value"' in prompt_str
    assert '"evidence_tables"' not in prompt_str
    assert '"evidence_figures"' not in prompt_str
    assert "- Tables (numbered):" not in prompt_str
    assert "Figures (numbered;" not in prompt_str


def test_parameter_extraction_prompt_includes_instructions_and_options():
    row, text_extraction_result, parameter = (
        _build_parameter_extraction_prompt_context()
    )
    parameter.option_type = Parameter.OptionType.SELECT
    parameter.units_and_reporting_instructions = "Report the dose band."
    parameter.calculation_instructions = "Use the total daily dose."
    parameter.save()
    ParameterOption.objects.create(
        parameter=parameter,
        name="High dose",
        context="At least 10 mg per day.",
    )
    builder = ParameterExtractionPromptBuilder(
        parameter=parameter,
        citation=row,
        text_extraction_result=text_extraction_result,
        tables=[],
        figures=[],
    )

    prompt = builder.build_str(builder.get_prompt_args())

    assert "Report the dose band." in prompt
    assert "Use the total daily dose." in prompt
    assert '"High dose": At least 10 mg per day.' in prompt
    assert "- Available options (select exactly one):" in prompt
    assert "select exactly one of the option names below" in prompt
    assert '"selected_option"' in prompt
    assert '"value"' not in prompt
    assert "Follow the calculation instructions below" in prompt


def test_parameter_extraction_prompt_builder_includes_tables_and_figures(
    tmp_path,
):
    row, text_extraction_result, parameter = (
        _build_parameter_extraction_prompt_context()
    )

    with override_settings(MEDIA_ROOT=tmp_path):
        table = DocumentTable.objects.create(
            document=row.document,
            index=1,
            caption="Intervention details",
            table_markdown="| Group | Dose |\n| --- | --- |\n| A | 5 mg/kg |",
        )
        figure = DocumentFigure.objects.create(
            document=row.document,
            index=2,
            caption="Dose response",
            file=SimpleUploadedFile(
                "figure.png", b"figure bytes", content_type="image/png"
            ),
        )

        prompt_builder = ParameterExtractionPromptBuilder(
            parameter=parameter,
            citation=row,
            text_extraction_result=text_extraction_result,
            tables=[table],
            figures=[figure],
        )
        prompt_args = prompt_builder.get_prompt_args()

        assert "Table 1  caption: Intervention details" in prompt_args.tables
        assert "| A | 5 mg/kg |" in prompt_args.tables
        assert (
            "Figure [F2] caption: Dose response (see attached image F2)"
            in prompt_args.figures
        )
        prompt = prompt_builder.build_str(prompt_args)
        assert "- Tables (numbered):" in prompt
        assert "Table 1  caption: Intervention details" in prompt
        assert "Figures (numbered;" in prompt
        assert "Figure [F2] caption: Dose response" in prompt
        assert '"evidence_tables"' in prompt
        assert '"evidence_figures"' in prompt
        schema = build_parameter_extraction_response_schema(
            parameter,
            True,
            True,
        ).schema
        assert "evidence_tables" in schema["properties"]
        assert "evidence_tables" in schema["required"]
        assert "evidence_figures" in schema["properties"]
        assert "evidence_figures" in schema["required"]
        assert len(prompt_args.figure_image_files) == 1
        assert prompt_args.figure_image_files[0].read() == b"figure bytes"


@override_settings(HAS_LLM=True)
def test_get_parameter_extraction_results_returns_valid_response():
    row, text_extraction_result, parameter = (
        _build_parameter_extraction_prompt_context()
    )

    client = MagicMock()
    client.complete_prompt.return_value = json.dumps(
        {
            "found": True,
            "value": "5 mg/kg",
            "explanation": "Sentence [0] reports the administered dose.",
            "evidence_sentences": [0],
        }
    )

    with patch(
        "my_app.prompts.parameter_extraction_prompt.get_client",
        return_value=client,
    ):
        result = get_parameter_extraction_results(
            row,
            parameter,
            text_extraction_result,
            [],
            [],
            sentinel.model,
        )

    assert result.found is True
    assert result.value == "5 mg/kg"
    assert result.explanation == "Sentence [0] reports the administered dose."
    assert result.evidence_sentences == [0]
    assert result.evidence_tables == []
    assert result.evidence_figures == []
    client.complete_prompt.assert_called_once()
    call = client.complete_prompt.call_args
    assert call.kwargs["model"] is sentinel.model
    response_schema = call.kwargs["response_schema"]
    assert response_schema.name == "parameter_extraction_result"
    assert response_schema.schema["properties"]["found"] == {
        "title": "Found",
        "type": "boolean",
    }
    assert response_schema.schema["additionalProperties"] is False
    assert "value" in response_schema.schema["properties"]
    assert "value" in response_schema.schema["required"]
    assert "selected_option" not in response_schema.schema["properties"]
    assert "selected_option" not in response_schema.schema["required"]
    assert "evidence_tables" not in response_schema.schema["properties"]
    assert "evidence_figures" not in response_schema.schema["properties"]


@override_settings(HAS_LLM=True)
def test_get_parameter_extraction_results_maps_selected_option():
    row, text_extraction_result, parameter = (
        _build_parameter_extraction_prompt_context()
    )
    parameter.option_type = Parameter.OptionType.SELECT
    parameter.save(update_fields=["option_type"])
    option = ParameterOption.objects.create(
        parameter=parameter,
        name="High dose",
        context="At least 10 mg per day.",
    )
    client = MagicMock()
    client.complete_prompt.return_value = json.dumps(
        {
            "found": True,
            "selected_option": "High dose",
            "explanation": "The reported dose matches this band.",
            "evidence_sentences": [0],
        }
    )

    with patch(
        "my_app.prompts.parameter_extraction_prompt.get_client",
        return_value=client,
    ):
        result = get_parameter_extraction_results(
            row,
            parameter,
            text_extraction_result,
            [],
            [],
            sentinel.model,
        )

    assert result.selected_option_id == option.id
    response_schema = client.complete_prompt.call_args.kwargs[
        "response_schema"
    ]
    assert response_schema.schema["properties"]["selected_option"]["enum"] == [
        "High dose",
        None,
    ]
    assert "selected_option" in response_schema.schema["required"]
    assert "value" not in response_schema.schema["properties"]
    assert "value" not in response_schema.schema["required"]


@override_settings(HAS_LLM=True)
def test_get_parameter_extraction_results_sends_figures_as_multimodal_files(
    tmp_path,
):
    row, text_extraction_result, parameter = (
        _build_parameter_extraction_prompt_context()
    )

    with override_settings(MEDIA_ROOT=tmp_path):
        figure = DocumentFigure.objects.create(
            document=row.document,
            index=1,
            caption="Dose figure",
            file=SimpleUploadedFile(
                "figure.png", b"figure bytes", content_type="image/png"
            ),
        )

        client = MagicMock()
        client.complete_multimodal_prompt.return_value = json.dumps(
            {
                "found": True,
                "value": "5 mg/kg",
                "explanation": "Figure 1 reports the dose.",
                "evidence_sentences": [],
                "evidence_figures": [1],
            }
        )

        with patch(
            "my_app.prompts.parameter_extraction_prompt.get_client",
            return_value=client,
        ):
            result = get_parameter_extraction_results(
                row,
                parameter,
                text_extraction_result,
                [],
                [figure],
                sentinel.model,
            )

    assert result.evidence_figures == [1]
    client.complete_prompt.assert_not_called()
    client.complete_multimodal_prompt.assert_called_once()
    args, kwargs = client.complete_multimodal_prompt.call_args
    assert "- Tables (numbered):" not in args[0]
    assert "Figure [F1] caption: Dose figure" in args[0]
    assert kwargs["files"] == [figure.file]
    assert kwargs["model"] is sentinel.model
    assert kwargs["response_schema"].name == "parameter_extraction_result"
    schema_properties = kwargs["response_schema"].schema["properties"]
    assert "evidence_tables" not in schema_properties
    assert "evidence_figures" in schema_properties


@override_settings(HAS_LLM=True)
def test_get_parameter_extraction_results_raises_when_json_is_invalid():
    row, text_extraction_result, parameter = (
        _build_parameter_extraction_prompt_context()
    )

    client = MagicMock()
    client.complete_prompt.return_value = "{not valid json}"

    with patch(
        "my_app.prompts.parameter_extraction_prompt.get_client",
        return_value=client,
    ):
        with pytest.raises(UnexpectedLLMOutputError, match="parse LLM output"):
            get_parameter_extraction_results(
                row,
                parameter,
                text_extraction_result,
                [],
                [],
                sentinel.model,
            )


@override_settings(HAS_LLM=True)
def test_get_parameter_extraction_results_raises_on_pydantic_validation_error():
    row, text_extraction_result, parameter = (
        _build_parameter_extraction_prompt_context()
    )

    client = MagicMock()
    client.complete_prompt.return_value = json.dumps(
        {
            "found": True,
            "value": "5 mg/kg",
            "explanation": "Sentence [0] reports the administered dose.",
            "evidence_sentences": "0",
        }
    )

    with patch(
        "my_app.prompts.parameter_extraction_prompt.get_client",
        return_value=client,
    ):
        with pytest.raises(
            UnexpectedLLMOutputError,
            match="did not match expected schema",
        ):
            get_parameter_extraction_results(
                row,
                parameter,
                text_extraction_result,
                [],
                [],
                sentinel.model,
            )

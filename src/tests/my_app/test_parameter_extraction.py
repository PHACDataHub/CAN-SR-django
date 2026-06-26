from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import override_settings

import pytest

from proj.util import MissingPreconditionError

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    ParameterCategoryFactory,
    ParameterFactory,
    ReviewFactory,
)
from my_app.models import (
    Document,
    DocumentFigure,
    DocumentTable,
    FigureExtractionResult,
    LanguageModel,
    ParameterExtractionResult,
    ScreeningResultStatus,
    TextExtractionResult,
)
from my_app.services.parameter_extraction import (
    DeferredParameterExtractionService,
    ProcessParameterExtractionService,
)

pytestmark = [pytest.mark.backend]


def _build_parameter_extraction_context(
    *,
    language_model=None,
    with_document=True,
    with_text_extraction_result=True,
    text_extraction_status=TextExtractionResult.TextExtractionStatus.COMPLETED,
    with_figure_extraction_result=True,
    figure_extraction_status=FigureExtractionResult.Status.COMPLETED,
):
    review = ReviewFactory(language_model=language_model)
    dataset = CitationDatasetFactory(review=review)
    citation = CitationFactory(
        dataset=dataset,
        order=1,
        title="Row",
        abstract="Row abstract",
    )

    if with_document:
        document = Document.objects.create(
            file="documents/example.pdf",
        )
        citation.document = document
        citation.save(update_fields=["document"])

        if with_text_extraction_result:
            text_extraction_result = TextExtractionResult.objects.create(
                document=document,
                status=text_extraction_status,
                coordinates=[
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
        else:
            text_extraction_result = None

        if with_figure_extraction_result:
            FigureExtractionResult.objects.create(
                document=document,
                status=figure_extraction_status,
            )
    else:
        text_extraction_result = None

    category = ParameterCategoryFactory(review=review)
    parameter = ParameterFactory(
        category=category,
        name="Dose",
        description="Extract the intervention dose.",
    )

    return review, dataset, citation, text_extraction_result, parameter


def test_deferred_parameter_extraction_service_enqueues_created_results():
    model = LanguageModel.get_default_model()
    review, _, row_1, _, parameter = _build_parameter_extraction_context(
        language_model=model
    )
    _, _, row_2, _, _ = _build_parameter_extraction_context()
    row_2.dataset = row_1.dataset
    row_2.save(update_fields=["dataset"])

    existing_result = ParameterExtractionResult.objects.create(
        citation=row_1,
        question=parameter,
        status=ScreeningResultStatus.COMPLETED,
    )

    task_mock = MagicMock()
    task_mock.enqueue = MagicMock()

    with patch(
        "my_app.tasks.parameter_extraction.process_parameter_extraction_task",
        task_mock,
    ):
        service = DeferredParameterExtractionService(
            rows=[row_1, row_2],
            questions=[parameter],
            overwrite_existing=False,
        )
        service.perform()

    results = list(
        ParameterExtractionResult.objects.filter(
            question=parameter,
            citation__in=[row_1, row_2],
        ).order_by("citation_id")
    )

    assert [result.citation_id for result in results] == [row_1.id, row_2.id]
    assert results[0].id == existing_result.id
    assert results[1].status == ScreeningResultStatus.PENDING
    assert results[1].language_model == model
    assert task_mock.enqueue.call_count == 1
    assert task_mock.enqueue.call_args.kwargs == {"result_id": results[1].id}


def test_deferred_parameter_extraction_service_overwrite_targets_only_requested_rows_and_parameters():
    _, _, target_row, _, parameter = _build_parameter_extraction_context()
    _, _, untouched_row, _, other_parameter = (
        _build_parameter_extraction_context()
    )
    untouched_row.dataset = target_row.dataset
    untouched_row.save(update_fields=["dataset"])

    target_result = ParameterExtractionResult.objects.create(
        citation=target_row,
        question=parameter,
        status=ScreeningResultStatus.COMPLETED,
    )
    untouched_same_row_result = ParameterExtractionResult.objects.create(
        citation=target_row,
        question=other_parameter,
        status=ScreeningResultStatus.PENDING,
    )
    untouched_same_parameter_result = ParameterExtractionResult.objects.create(
        citation=untouched_row,
        question=parameter,
        status=ScreeningResultStatus.ABANDONED,
    )

    task_mock = MagicMock()
    task_mock.enqueue = MagicMock()

    with patch(
        "my_app.tasks.parameter_extraction.process_parameter_extraction_task",
        task_mock,
    ):
        service = DeferredParameterExtractionService(
            rows=[target_row],
            questions=[parameter],
            overwrite_existing=True,
        )
        service.perform()

    results = list(
        ParameterExtractionResult.objects.filter(
            citation__in=[target_row, untouched_row],
            question__in=[parameter, other_parameter],
        ).order_by("citation_id", "question_id")
    )

    assert (
        ParameterExtractionResult.objects.filter(pk=target_result.pk).count()
        == 0
    )
    assert (
        ParameterExtractionResult.objects.filter(
            pk=untouched_same_row_result.pk
        ).count()
        == 1
    )
    assert (
        ParameterExtractionResult.objects.filter(
            pk=untouched_same_parameter_result.pk
        ).count()
        == 1
    )
    assert len(results) == 3

    target_pair_results = [
        result
        for result in results
        if result.citation_id == target_row.id
        and result.question_id == parameter.id
    ]
    assert len(target_pair_results) == 1
    assert target_pair_results[0].status == ScreeningResultStatus.PENDING
    assert task_mock.enqueue.call_count == 1
    assert task_mock.enqueue.call_args.kwargs == {
        "result_id": target_pair_results[0].id
    }


@override_settings(HAS_LLM=False)
def test_process_parameter_extraction_service_uses_mock_results_helper_with_text_extraction_result():
    _, _, row, _, parameter = _build_parameter_extraction_context()
    result = ParameterExtractionResult.objects.create(
        citation=row,
        question=parameter,
        status=ScreeningResultStatus.PENDING,
    )

    ProcessParameterExtractionService(result_id=result.id).perform()

    result.refresh_from_db()

    assert result.status == ScreeningResultStatus.COMPLETED
    assert result.found is True
    assert result.value.startswith("Mock value from sentence")
    assert result.explanation.startswith("Mock explanation based on sentence")


def test_process_parameter_extraction_service_persists_extraction_results():
    _, _, row, _, parameter = _build_parameter_extraction_context()
    table = DocumentTable.objects.create(
        document=row.document,
        index=2,
        table_markdown="| Outcome | Count |\n| --- | --- |\n| Cases | 12 |",
    )
    figure = DocumentFigure.objects.create(
        document=row.document,
        index=3,
        caption="Outcome chart",
    )
    result = ParameterExtractionResult.objects.create(
        citation=row,
        question=parameter,
        status=ScreeningResultStatus.PENDING,
    )

    extraction_result = SimpleNamespace(
        found=True,
        value="5 mg/kg",
        explanation="The dose was reported in the methods.",
        evidence_sentences=[0, 1],
        evidence_tables=[2],
        evidence_figures=[3],
    )

    with patch(
        "my_app.services.parameter_extraction.get_parameter_extraction_results",
        return_value=extraction_result,
    ) as get_results:
        ProcessParameterExtractionService(result_id=result.id).perform()

    result.refresh_from_db()

    assert result.status == ScreeningResultStatus.COMPLETED
    assert result.found is True
    assert result.value == "5 mg/kg"
    assert result.evidence_sentences == [0, 1]
    assert result.evidence_tables == [2]
    assert result.evidence_figures == [3]
    assert result.explanation == "The dose was reported in the methods."
    assert get_results.call_args.args[3] == [table]
    assert get_results.call_args.args[4] == [figure]
    assert get_results.call_args.args[5] is result.language_model


def test_process_parameter_extraction_service_raises_when_document_missing():
    _, _, row, _, parameter = _build_parameter_extraction_context(
        with_document=False
    )
    result = ParameterExtractionResult.objects.create(
        citation=row,
        question=parameter,
        status=ScreeningResultStatus.PENDING,
    )

    with pytest.raises(
        MissingPreconditionError, match="requires a document to be attached"
    ):
        ProcessParameterExtractionService(result_id=result.id).perform()

    result.refresh_from_db()
    assert result.status == ScreeningResultStatus.PENDING

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import override_settings

import pytest

from proj.util import MissingPreconditionError

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    ReviewFactory,
)
from my_app.models import (
    Document,
    DocumentFigure,
    DocumentTable,
    FigureExtractionResult,
    L2ScreeningResult,
    ScreeningResultStatus,
    TextExtractionResult,
)
from my_app.services.l2_screening import (
    DeferredL2ScreeningService,
    ProcessL2ScreeningService,
)

pytestmark = [pytest.mark.backend, pytest.mark.l2_screening]


def _build_l2_screening_context(
    *,
    with_document=True,
    with_text_extraction_result=True,
    text_extraction_status=TextExtractionResult.TextExtractionStatus.COMPLETED,
    with_figure_extraction_result=True,
    figure_extraction_status=FigureExtractionResult.Status.COMPLETED,
):
    review = ReviewFactory()
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

    question = L2ScreeningQuestionFactory(
        review=review,
        question_text="Is this citation eligible?",
    )
    L2ScreeningQuestionOptionFactory(
        question=question,
        option_text="Include",
        option_value="Include the citation",
    )
    L2ScreeningQuestionOptionFactory(
        question=question,
        option_text="Exclude",
        option_value="Exclude the citation",
    )

    return review, dataset, citation, text_extraction_result, question


def test_deferred_l2_screening_service_enqueues_created_results():
    _, _, row_1, _, question = _build_l2_screening_context()
    _, _, row_2, _, _ = _build_l2_screening_context()
    row_2.dataset = row_1.dataset
    row_2.save(update_fields=["dataset"])

    existing_result = L2ScreeningResult.objects.create(
        citation=row_1,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )

    task_mock = MagicMock()
    task_mock.enqueue = MagicMock()

    with patch(
        "my_app.tasks.l2_screening.process_l2_screening_task",
        task_mock,
    ):
        service = DeferredL2ScreeningService(
            rows=[row_1, row_2],
            questions=[question],
            overwrite_existing=False,
        )
        service.perform()

    results = list(
        L2ScreeningResult.objects.filter(
            question=question,
            citation__in=[row_1, row_2],
        ).order_by("citation_id")
    )

    assert [result.citation_id for result in results] == [row_1.id, row_2.id]
    assert results[0].id == existing_result.id
    assert results[1].status == ScreeningResultStatus.PENDING
    assert task_mock.enqueue.call_count == 1
    assert task_mock.enqueue.call_args.kwargs == {"result_id": results[1].id}


def test_deferred_l2_screening_service_overwrite_targets_only_requested_rows_and_questions():
    _, _, target_row, _, question = _build_l2_screening_context()
    _, _, untouched_row, _, other_question = _build_l2_screening_context()
    untouched_row.dataset = target_row.dataset
    untouched_row.save(update_fields=["dataset"])

    L2ScreeningQuestionOptionFactory(
        question=other_question,
        option_text="Include",
        option_value="Include the citation",
    )
    L2ScreeningQuestionOptionFactory(
        question=other_question,
        option_text="Exclude",
        option_value="Exclude the citation",
    )

    target_result = L2ScreeningResult.objects.create(
        citation=target_row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )
    untouched_same_row_result = L2ScreeningResult.objects.create(
        citation=target_row,
        question=other_question,
        status=ScreeningResultStatus.PENDING,
    )
    untouched_same_question_result = L2ScreeningResult.objects.create(
        citation=untouched_row,
        question=question,
        status=ScreeningResultStatus.ABANDONED,
    )

    task_mock = MagicMock()
    task_mock.enqueue = MagicMock()

    with patch(
        "my_app.tasks.l2_screening.process_l2_screening_task",
        task_mock,
    ):
        service = DeferredL2ScreeningService(
            rows=[target_row],
            questions=[question],
            overwrite_existing=True,
        )
        service.perform()

    results = list(
        L2ScreeningResult.objects.filter(
            citation__in=[target_row, untouched_row],
            question__in=[question, other_question],
        ).order_by("citation_id", "question_id")
    )

    assert L2ScreeningResult.objects.filter(pk=target_result.pk).count() == 0
    assert (
        L2ScreeningResult.objects.filter(
            pk=untouched_same_row_result.pk
        ).count()
        == 1
    )
    assert (
        L2ScreeningResult.objects.filter(
            pk=untouched_same_question_result.pk
        ).count()
        == 1
    )
    assert len(results) == 3

    target_pair_results = [
        result
        for result in results
        if result.citation_id == target_row.id
        and result.question_id == question.id
    ]
    assert len(target_pair_results) == 1
    assert target_pair_results[0].status == ScreeningResultStatus.PENDING
    assert task_mock.enqueue.call_count == 1
    assert task_mock.enqueue.call_args.kwargs == {
        "result_id": target_pair_results[0].id
    }


@override_settings(HAS_LLM=False)
def test_process_l2_screening_service_uses_mock_results_helper_with_text_extraction_result():
    _, _, row, _, question = _build_l2_screening_context()
    result = L2ScreeningResult.objects.create(
        citation=row,
        question=question,
        status=ScreeningResultStatus.PENDING,
    )

    ProcessL2ScreeningService(result_id=result.id).perform()

    result.refresh_from_db()

    assert result.status == ScreeningResultStatus.COMPLETED
    assert result.selected_option.question == question
    assert result.explanation == (
        "This is a mock explanation for why the option was selected."
    )
    assert 0.5 <= result.confidence <= 1.0


def test_process_l2_screening_service_persists_evidence_sentences():
    _, _, row, _, question = _build_l2_screening_context()
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
    selected_option = question.options.get(option_text="Include")
    result = L2ScreeningResult.objects.create(
        citation=row,
        question=question,
        status=ScreeningResultStatus.PENDING,
    )

    screening_result = SimpleNamespace(
        selected=selected_option,
        confidence=0.88,
        explanation="Relevant evidence was found.",
        evidence_sentences=[0, 1],
        evidence_tables=[2],
        evidence_figures=[3],
    )

    with patch(
        "my_app.services.l2_screening.get_l2_screening_results",
        return_value=screening_result,
    ) as get_results:
        ProcessL2ScreeningService(result_id=result.id).perform()

    result.refresh_from_db()

    assert result.status == ScreeningResultStatus.COMPLETED
    assert result.selected_option == selected_option
    assert result.evidence_sentences == [0, 1]
    assert result.evidence_tables == [2]
    assert result.evidence_figures == [3]
    assert result.explanation == "Relevant evidence was found."
    assert result.confidence == 0.88
    assert get_results.call_args.args[4] == [table]
    assert get_results.call_args.args[5] == [figure]


def test_process_l2_screening_service_raises_when_document_missing():
    _, _, row, _, question = _build_l2_screening_context(with_document=False)
    result = L2ScreeningResult.objects.create(
        citation=row,
        question=question,
        status=ScreeningResultStatus.PENDING,
    )

    with pytest.raises(
        MissingPreconditionError, match="requires a document to be attached"
    ):
        ProcessL2ScreeningService(result_id=result.id).perform()

    result.refresh_from_db()
    assert result.status == ScreeningResultStatus.PENDING


def test_deferred_l2_screening_service_raises_when_text_extraction_result_missing():
    _, _, row, _, question = _build_l2_screening_context(
        with_text_extraction_result=False
    )

    task_mock = MagicMock()
    task_mock.enqueue = MagicMock()

    with patch(
        "my_app.tasks.l2_screening.process_l2_screening_task",
        task_mock,
    ):
        with pytest.raises(
            MissingPreconditionError,
            match="requires text extraction to be completed",
        ):
            DeferredL2ScreeningService(
                rows=[row],
                questions=[question],
                overwrite_existing=False,
            ).perform()

    assert L2ScreeningResult.objects.count() == 0
    assert task_mock.enqueue.call_count == 0


def test_deferred_l2_screening_service_raises_when_text_extraction_incomplete():
    _, _, row, _, question = _build_l2_screening_context(
        text_extraction_status=TextExtractionResult.TextExtractionStatus.PENDING
    )

    task_mock = MagicMock()
    task_mock.enqueue = MagicMock()

    with patch(
        "my_app.tasks.l2_screening.process_l2_screening_task",
        task_mock,
    ):
        with pytest.raises(
            MissingPreconditionError,
            match="requires text extraction to be completed",
        ):
            DeferredL2ScreeningService(
                rows=[row],
                questions=[question],
                overwrite_existing=False,
            ).perform()

    assert L2ScreeningResult.objects.count() == 0
    assert task_mock.enqueue.call_count == 0


def test_process_l2_screening_service_raises_when_text_extraction_result_missing():
    _, _, row, _, question = _build_l2_screening_context(
        with_text_extraction_result=False
    )
    result = L2ScreeningResult.objects.create(
        citation=row,
        question=question,
        status=ScreeningResultStatus.PENDING,
    )

    with pytest.raises(
        MissingPreconditionError,
        match="requires text extraction to be completed",
    ):
        ProcessL2ScreeningService(result_id=result.id).perform()

    result.refresh_from_db()
    assert result.status == ScreeningResultStatus.PENDING


def test_deferred_l2_screening_service_raises_when_figure_extraction_result_missing():
    _, _, row, _, question = _build_l2_screening_context(
        with_figure_extraction_result=False
    )

    task_mock = MagicMock()
    task_mock.enqueue = MagicMock()

    with patch(
        "my_app.tasks.l2_screening.process_l2_screening_task",
        task_mock,
    ):
        with pytest.raises(
            MissingPreconditionError,
            match="requires figure extraction to be completed",
        ):
            DeferredL2ScreeningService(
                rows=[row],
                questions=[question],
                overwrite_existing=False,
            ).perform()

    assert L2ScreeningResult.objects.count() == 0
    assert task_mock.enqueue.call_count == 0


def test_process_l2_screening_service_raises_when_figure_extraction_incomplete():
    _, _, row, _, question = _build_l2_screening_context(
        figure_extraction_status=FigureExtractionResult.Status.PENDING
    )
    result = L2ScreeningResult.objects.create(
        citation=row,
        question=question,
        status=ScreeningResultStatus.PENDING,
    )

    with pytest.raises(
        MissingPreconditionError,
        match="requires figure extraction to be completed",
    ):
        ProcessL2ScreeningService(result_id=result.id).perform()

    result.refresh_from_db()
    assert result.status == ScreeningResultStatus.PENDING

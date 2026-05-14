import json
from unittest.mock import MagicMock, patch

from django.test import override_settings

import pytest

from my_app.model_factories import SystematicReviewFactory
from my_app.models import (
    CitationDataset,
    CitationDatasetRow,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    L1ScreeningResult,
    ScreeningResultStatus,
)
from my_app.prompts.screening_prompt import (
    get_l1_screening_results,
    get_mock_l1_screening_results,
)
from my_app.services.ai_screening import (
    DeferredL1ScreeningService,
    ProcessL1ScreeningService,
)


def _create_dataset(review):
    return CitationDataset.objects.create(systematic_review=review)


def _create_row(dataset, order, title):
    return CitationDatasetRow.objects.create(
        dataset=dataset,
        order=order,
        title=title,
        abstract=f"{title} abstract",
    )


def _create_question(review, question_text="Is this citation relevant?"):
    return L1ScreeningQuestion.objects.create(
        review=review,
        question_text=question_text,
    )


def _create_options(question):
    include_option = L1ScreeningQuestionOption.objects.create(
        question=question,
        option_text="Include",
        option_value="Include the citation",
    )
    exclude_option = L1ScreeningQuestionOption.objects.create(
        question=question,
        option_text="Exclude",
        option_value="Exclude the citation",
    )
    return include_option, exclude_option


def test_deferred_l1_screening_service_enqueues_created_results():
    review = SystematicReviewFactory()
    dataset = _create_dataset(review)
    row_1 = _create_row(dataset, order=1, title="Row 1")
    row_2 = _create_row(dataset, order=2, title="Row 2")
    question = _create_question(review)
    _create_options(question)

    existing_result = L1ScreeningResult.objects.create(
        citation=row_1,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )

    task_mock = MagicMock()
    task_mock.enqueue = MagicMock()

    with patch(
        "my_app.tasks.ai_screening.process_l1_screening_task",
        task_mock,
    ):
        service = DeferredL1ScreeningService(
            rows=[row_1, row_2],
            questions=[question],
            overwrite_existing=False,
        )
        service.perform()

    results = list(
        L1ScreeningResult.objects.filter(
            question=question,
            citation__in=[row_1, row_2],
        ).order_by("citation_id")
    )

    assert [result.citation_id for result in results] == [row_1.id, row_2.id]
    assert results[0].id == existing_result.id
    assert results[1].status == ScreeningResultStatus.PENDING
    assert task_mock.enqueue.call_count == 1
    assert task_mock.enqueue.call_args.kwargs == {"result_id": results[1].id}


def test_deferred_l1_screening_service_overwrite_targets_only_requested_rows_and_questions():
    review = SystematicReviewFactory()
    dataset = _create_dataset(review)
    target_row = _create_row(dataset, order=1, title="Target row")
    untouched_row = _create_row(dataset, order=2, title="Untouched row")
    question = _create_question(review)
    other_question = _create_question(review, question_text="Other question")
    _create_options(question)
    _create_options(other_question)

    target_result = L1ScreeningResult.objects.create(
        citation=target_row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )
    untouched_same_row_result = L1ScreeningResult.objects.create(
        citation=target_row,
        question=other_question,
        status=ScreeningResultStatus.PENDING,
    )
    untouched_same_question_result = L1ScreeningResult.objects.create(
        citation=untouched_row,
        question=question,
        status=ScreeningResultStatus.ABANDONED,
    )

    task_mock = MagicMock()
    task_mock.enqueue = MagicMock()

    with patch(
        "my_app.tasks.ai_screening.process_l1_screening_task",
        task_mock,
    ):
        service = DeferredL1ScreeningService(
            rows=[target_row],
            questions=[question],
            overwrite_existing=True,
        )
        service.perform()

    results = list(
        L1ScreeningResult.objects.filter(
            citation__in=[target_row, untouched_row],
            question__in=[question, other_question],
        ).order_by("citation_id", "question_id")
    )

    assert L1ScreeningResult.objects.filter(pk=target_result.pk).count() == 0
    assert (
        L1ScreeningResult.objects.filter(
            pk=untouched_same_row_result.pk
        ).count()
        == 1
    )
    assert (
        L1ScreeningResult.objects.filter(
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


@override_settings(HAS_LLM=True)
def test_get_l1_screening_results_returns_exact_matching_option():
    review = SystematicReviewFactory()
    dataset = _create_dataset(review)
    row = _create_row(dataset, order=1, title="Row")
    question = _create_question(review)
    include_option, _ = _create_options(question)

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
def test_get_l1_screening_results_raises_when_llm_returns_unknown_option():
    review = SystematicReviewFactory()
    dataset = _create_dataset(review)
    row = _create_row(dataset, order=1, title="Row")
    question = _create_question(review)
    _create_options(question)

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
            ValueError,
            match="doesn't match any of the available options",
        ):
            get_l1_screening_results(question, row)


@override_settings(HAS_LLM=False)
def test_process_l1_screening_service_uses_mock_results_helper():
    review = SystematicReviewFactory()
    dataset = _create_dataset(review)
    row = _create_row(dataset, order=1, title="Row")
    question = _create_question(review)
    options = _create_options(question)

    result = L1ScreeningResult.objects.create(
        citation=row,
        question=question,
        status=ScreeningResultStatus.PENDING,
    )

    ProcessL1ScreeningService(result_id=result.id).perform()

    result.refresh_from_db()

    assert result.status == ScreeningResultStatus.COMPLETED
    assert result.selected_option in options
    assert (
        result.explanation
        == "This is a mock explanation for why the option was selected."
    )
    assert 0.5 <= result.confidence <= 1.0

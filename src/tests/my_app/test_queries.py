from data_fetcher.middleware import GlobalRequest

from my_app.model_factories import SystematicReviewFactory
from my_app.models import (
    CitationDataset,
    CitationDatasetRow,
    L1ScreeningQuestion,
    L1ScreeningResult,
    ScreeningResultStatus,
)
from my_app.queries import L1ScreeningStatusFetcher


def _create_dataset(review):
    return CitationDataset.objects.create(systematic_review=review)


def _create_dataset_row(dataset, order):
    return CitationDatasetRow.objects.create(
        dataset=dataset,
        order=order,
        title=f"Citation {order}",
    )


def test_l1_screening_status_fetcher_returns_not_started_for_missing_results():
    review = SystematicReviewFactory()
    dataset = _create_dataset(review)
    row = _create_dataset_row(dataset, order=1)

    with GlobalRequest():
        fetcher = L1ScreeningStatusFetcher.get_instance()

        single_result = fetcher.get(row.id)
        multiple_results = fetcher.get_many([row.id])

    assert single_result == ScreeningResultStatus.NOT_STARTED
    assert multiple_results == [ScreeningResultStatus.NOT_STARTED]


def test_l1_screening_status_fetcher_returns_statuses_in_request_order():
    review = SystematicReviewFactory()
    dataset = _create_dataset(review)
    question = L1ScreeningQuestion.objects.create(
        review=review,
        question_text="Is this citation relevant?",
    )
    second_question = L1ScreeningQuestion.objects.create(
        review=review,
        question_text="Is this citation eligible?",
    )

    not_started_row = _create_dataset_row(dataset, order=1)
    completed_row = _create_dataset_row(dataset, order=2)
    abandoned_row = _create_dataset_row(dataset, order=3)
    pending_row = _create_dataset_row(dataset, order=4)
    mixed_row = _create_dataset_row(dataset, order=5)

    L1ScreeningResult.objects.create(
        citation=completed_row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )
    L1ScreeningResult.objects.create(
        citation=abandoned_row,
        question=question,
        status=ScreeningResultStatus.ABANDONED,
    )
    L1ScreeningResult.objects.create(
        citation=pending_row,
        question=question,
        status=ScreeningResultStatus.PENDING,
    )
    L1ScreeningResult.objects.create(
        citation=mixed_row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )
    L1ScreeningResult.objects.create(
        citation=mixed_row,
        question=second_question,
        status=ScreeningResultStatus.PENDING,
    )

    with GlobalRequest():
        fetcher = L1ScreeningStatusFetcher.get_instance()
        results = fetcher.get_many(
            [
                not_started_row.id,
                completed_row.id,
                abandoned_row.id,
                pending_row.id,
                mixed_row.id,
            ]
        )

    assert results == [
        ScreeningResultStatus.NOT_STARTED,
        ScreeningResultStatus.COMPLETED,
        ScreeningResultStatus.ABANDONED,
        ScreeningResultStatus.PENDING,
        ScreeningResultStatus.PENDING,
    ]

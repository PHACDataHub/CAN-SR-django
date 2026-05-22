from data_fetcher.middleware import GlobalRequest

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningResultFactory,
    ReviewFactory,
)
from my_app.models import ScreeningResultStatus
from my_app.queries import L1ScreeningStatusFetcher


def test_l1_screening_status_fetcher_returns_not_started_for_missing_results():
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(
        dataset=dataset,
        order=1,
        title="Citation 1",
    )

    with GlobalRequest():
        fetcher = L1ScreeningStatusFetcher.get_instance()

        single_result = fetcher.get(row.id)
        multiple_results = fetcher.get_many([row.id])

    assert single_result == ScreeningResultStatus.NOT_STARTED
    assert multiple_results == [ScreeningResultStatus.NOT_STARTED]


def test_l1_screening_status_fetcher_returns_statuses_in_request_order():
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    question = L1ScreeningQuestionFactory(
        review=review,
        question_text="Is this citation relevant?",
    )
    second_question = L1ScreeningQuestionFactory(
        review=review,
        question_text="Is this citation eligible?",
    )

    not_started_row = CitationFactory(
        dataset=dataset,
        order=1,
        title="Citation 1",
    )
    completed_row = CitationFactory(
        dataset=dataset,
        order=2,
        title="Citation 2",
    )
    abandoned_row = CitationFactory(
        dataset=dataset,
        order=3,
        title="Citation 3",
    )
    pending_row = CitationFactory(
        dataset=dataset,
        order=4,
        title="Citation 4",
    )
    mixed_row = CitationFactory(
        dataset=dataset,
        order=5,
        title="Citation 5",
    )

    L1ScreeningResultFactory(
        citation=completed_row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )
    L1ScreeningResultFactory(
        citation=abandoned_row,
        question=question,
        status=ScreeningResultStatus.ABANDONED,
    )
    L1ScreeningResultFactory(
        citation=pending_row,
        question=question,
        status=ScreeningResultStatus.PENDING,
    )
    L1ScreeningResultFactory(
        citation=mixed_row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )
    L1ScreeningResultFactory(
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

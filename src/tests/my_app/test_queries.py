import pytest
from data_fetcher.middleware import GlobalRequest

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    DocumentFactory,
    FigureExtractionResultFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L1ScreeningResultFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    ParameterCategoryFactory,
    ParameterExtractionResultFactory,
    ParameterFactory,
    ReviewFactory,
    TextExtractionResultFactory,
    UserFactory,
)
from my_app.models import (
    FigureExtractionResult,
    ScreeningResultStatus,
    TextExtractionResult,
)
from my_app.queries import (
    L1ScreeningStatusFetcher,
    get_adjacent_citation_ids,
    get_l1_screening_progress_stats,
    get_parameter_extraction_progress_stats,
    is_l2_screening_defined,
    is_parameter_extraction_defined,
    is_ready_for_l2_screening,
    is_ready_for_parameter_extraction,
)

pytestmark = [pytest.mark.backend, pytest.mark.l1_screening]


def test_is_l2_screening_defined_requires_a_question_and_option():
    citation = CitationFactory()

    assert is_l2_screening_defined(citation.id) is False

    question = L2ScreeningQuestionFactory(review=citation.dataset.review)
    assert is_l2_screening_defined(citation.id) is False

    L2ScreeningQuestionOptionFactory(question=question)
    assert is_l2_screening_defined(citation.id) is True


def test_is_parameter_extraction_defined_requires_a_category_and_parameter():
    citation = CitationFactory()

    assert is_parameter_extraction_defined(citation.id) is False

    category = ParameterCategoryFactory(review=citation.dataset.review)
    assert is_parameter_extraction_defined(citation.id) is False

    ParameterFactory(category=category)
    assert is_parameter_extraction_defined(citation.id) is True


def test_is_ready_for_l2_screening_requires_successful_document_extraction():
    document = DocumentFactory()
    citation = CitationFactory(document=document)
    question = L2ScreeningQuestionFactory(review=citation.dataset.review)
    L2ScreeningQuestionOptionFactory(question=question)

    assert is_ready_for_l2_screening(citation.id) is False

    TextExtractionResultFactory(
        document=document,
        status=TextExtractionResult.TextExtractionStatus.COMPLETED,
    )
    FigureExtractionResultFactory(
        document=document,
        status=FigureExtractionResult.Status.PENDING,
    )
    assert is_ready_for_l2_screening(citation.id) is False

    document.figure_extraction_result.status = (
        FigureExtractionResult.Status.COMPLETED
    )
    document.figure_extraction_result.save()
    assert is_ready_for_l2_screening(citation.id) is True


def test_is_ready_for_parameter_extraction_requires_defined_parameters():
    document = DocumentFactory()
    citation = CitationFactory(document=document)
    TextExtractionResultFactory(
        document=document,
        status=TextExtractionResult.TextExtractionStatus.COMPLETED,
    )
    FigureExtractionResultFactory(
        document=document,
        status=FigureExtractionResult.Status.COMPLETED,
    )

    assert is_ready_for_parameter_extraction(citation.id) is False

    category = ParameterCategoryFactory(review=citation.dataset.review)
    ParameterFactory(category=category)
    assert is_ready_for_parameter_extraction(citation.id) is True


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


def test_get_adjacent_citation_ids_uses_order_within_same_dataset():
    dataset = CitationDatasetFactory()
    other_dataset = CitationDatasetFactory()
    previous_row = CitationFactory(dataset=dataset, order=10)
    current_row = CitationFactory(dataset=dataset, order=20)
    next_row = CitationFactory(dataset=dataset, order=30)
    CitationFactory(dataset=other_dataset, order=25)

    previous_id, next_id = get_adjacent_citation_ids(current_row.id)

    assert previous_id == previous_row.id
    assert next_id == next_row.id


def test_l1_screening_progress_stats_counts_review_citations_by_human_review_status():
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    question = L1ScreeningQuestionFactory(review=review)
    answer = L1ScreeningQuestionOptionFactory(question=question)
    user = UserFactory()

    incomplete_row = CitationFactory(dataset=dataset, order=1)
    completed_row = CitationFactory(dataset=dataset, order=2)
    human_answered_row = CitationFactory(dataset=dataset, order=3)
    human_validated_row = CitationFactory(dataset=dataset, order=4)

    L1ScreeningResultFactory(
        citation=incomplete_row,
        question=question,
        status=ScreeningResultStatus.PENDING,
    )
    L1ScreeningResultFactory(
        citation=completed_row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )
    L1ScreeningResultFactory(
        citation=human_answered_row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
        human_selected_answer=answer,
    )
    L1ScreeningResultFactory(
        citation=human_validated_row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
        human_validated_by=user,
    )

    stats = get_l1_screening_progress_stats(review.id)

    assert stats.total_citations == 4
    assert stats.incomplete_citations == 1
    assert stats.completed_not_human_reviewed_citations == 1
    assert stats.human_reviewed_citations == 2
    assert stats.human_reviewed_percent == 50


def test_parameter_extraction_progress_stats_counts_human_reviewed_citations():
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    category = ParameterCategoryFactory(review=review)
    parameter = ParameterFactory(category=category)

    incomplete_row = CitationFactory(dataset=dataset, order=1)
    completed_row = CitationFactory(dataset=dataset, order=2)
    human_reviewed_row = CitationFactory(dataset=dataset, order=3)

    ParameterExtractionResultFactory(
        citation=incomplete_row,
        question=parameter,
        status=ScreeningResultStatus.PENDING,
    )
    ParameterExtractionResultFactory(
        citation=completed_row,
        question=parameter,
        status=ScreeningResultStatus.COMPLETED,
    )
    ParameterExtractionResultFactory(
        citation=human_reviewed_row,
        question=parameter,
        status=ScreeningResultStatus.COMPLETED,
        human_found=False,
        human_value=None,
    )

    stats = get_parameter_extraction_progress_stats(review.id)

    assert stats.total_citations == 3
    assert stats.incomplete_citations == 1
    assert stats.completed_not_human_reviewed_citations == 1
    assert stats.human_reviewed_citations == 1
    assert stats.human_reviewed_percent == 33

import pytest
from data_fetcher.middleware import GlobalRequest

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    DocumentFactory,
    FigureExtractionResultFactory,
    L1HumanAnswerFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L1ScreeningResultFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    ParameterCategoryFactory,
    ParameterExtractionResultFactory,
    ParameterFactory,
    ParameterHumanAnswerFactory,
    ReviewFactory,
    TextExtractionResultFactory,
    UserFactory,
)
from my_app.models import (
    FigureExtractionResult,
    ParameterAnswerAgreement,
    ScreeningResultStatus,
    TextExtractionResult,
)
from my_app.queries import (
    L1ScreeningStatusFetcher,
    get_adjacent_citation_ids,
    get_l1_screening_progress_stats,
    get_parameter_answer_agreement_metrics,
    get_parameter_extraction_progress_stats,
    get_parameter_human_ai_agreements,
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
    )
    L1HumanAnswerFactory(
        citation=human_answered_row,
        question=question,
        selected_option=answer,
        user=user,
    )
    L1ScreeningResultFactory(
        citation=human_validated_row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )
    L1HumanAnswerFactory(
        citation=human_validated_row,
        question=question,
        selected_option=answer,
        user=user,
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
    )
    ParameterHumanAnswerFactory(
        citation=human_reviewed_row,
        question=parameter,
        found=False,
        value=None,
    )

    stats = get_parameter_extraction_progress_stats(review.id)

    assert stats.total_citations == 3
    assert stats.incomplete_citations == 1
    assert stats.completed_not_human_reviewed_citations == 1
    assert stats.human_reviewed_citations == 1
    assert stats.human_reviewed_percent == 33


def _create_parameter_human_ai_pair(
    *,
    review=None,
    ai_found=True,
    ai_value=None,
    human_found=True,
    human_value=None,
    result_status=ScreeningResultStatus.COMPLETED,
):
    if review is None:
        review = ReviewFactory()
    dataset = getattr(review, "citation_dataset", None)
    if dataset is None:
        dataset = CitationDatasetFactory(review=review)
    parameter = ParameterFactory(
        category=ParameterCategoryFactory(review=review)
    )
    citation = CitationFactory(dataset=dataset)
    result = ParameterExtractionResultFactory(
        citation=citation,
        question=parameter,
        status=result_status,
        found=ai_found,
        value=ai_value,
    )
    answer = ParameterHumanAnswerFactory(
        citation=citation,
        question=parameter,
        found=human_found,
        value=human_value,
    )
    return review, result, answer


@pytest.mark.parametrize(
    ("ai_found", "ai_value", "human_found", "human_value", "expected"),
    [
        (
            True,
            "10 mg",
            False,
            None,
            ParameterAnswerAgreement.DETECTION_DISAGREEMENT,
        ),
        (
            False,
            None,
            False,
            "Ignored value",
            ParameterAnswerAgreement.ABSENCE_AGREEMENT,
        ),
        (
            True,
            " 10 MG\n",
            True,
            "10mg",
            ParameterAnswerAgreement.VALUE_AGREEMENT,
        ),
        (
            True,
            "heart attack",
            True,
            "myocardial infarction",
            ParameterAnswerAgreement.VALUE_DISAGREEMENT,
        ),
    ],
)
def test_parameter_human_ai_agreement_states(
    ai_found,
    ai_value,
    human_found,
    human_value,
    expected,
):
    review, _, answer = _create_parameter_human_ai_pair(
        ai_found=ai_found,
        ai_value=ai_value,
        human_found=human_found,
        human_value=human_value,
    )

    agreement = get_parameter_human_ai_agreements(review.id).get(pk=answer.pk)

    assert agreement.agreement == expected


def test_parameter_agreements_only_pair_completed_results_in_same_review():
    review, _, answer = _create_parameter_human_ai_pair()
    _, _, other_review_answer = _create_parameter_human_ai_pair()
    _, _, pending_answer = _create_parameter_human_ai_pair(
        review=review,
        result_status=ScreeningResultStatus.PENDING,
    )
    unmatched_answer = ParameterHumanAnswerFactory(
        citation=CitationFactory(dataset=answer.citation.dataset),
        question=answer.question,
    )

    answer_ids = set(
        get_parameter_human_ai_agreements(review.id).values_list(
            "id", flat=True
        )
    )

    assert answer_ids == {answer.id}
    assert other_review_answer.id not in answer_ids
    assert pending_answer.id not in answer_ids
    assert unmatched_answer.id not in answer_ids


def test_parameter_agreement_metrics_count_each_human_ai_pair():
    review, result, _ = _create_parameter_human_ai_pair(
        ai_value="10 mg",
        human_value="10mg",
    )

    ParameterHumanAnswerFactory(
        citation=result.citation,
        question=result.question,
        found=True,
        value="10 mg",
    )
    _create_parameter_human_ai_pair(
        review=review,
        ai_found=True,
        human_found=False,
    )

    metrics = get_parameter_answer_agreement_metrics(review.id)
    assert metrics.detection_disagreement == 1
    assert metrics.absence_agreement == 0
    assert metrics.value_agreement == 2
    assert metrics.value_disagreement == 0
    assert metrics.total == 3

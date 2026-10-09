from datetime import timedelta

from django.utils import timezone

import pytest

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    L1HumanAnswerFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L1ScreeningResultFactory,
    L2HumanAnswerFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    L2ScreeningResultFactory,
    ReviewFactory,
)
from my_app.models import ScreeningActions, ScreeningResultStatus
from my_app.queries import (
    ReviewStage,
    ScreeningMetric,
    get_screening_answer_metrics,
)

STAGE_FACTORIES = [
    (
        ReviewStage.L1_SCREENING,
        L1ScreeningQuestionFactory,
        L1ScreeningQuestionOptionFactory,
        L1ScreeningResultFactory,
        L1HumanAnswerFactory,
    ),
    (
        ReviewStage.L2_SCREENING,
        L2ScreeningQuestionFactory,
        L2ScreeningQuestionOptionFactory,
        L2ScreeningResultFactory,
        L2HumanAnswerFactory,
    ),
]


def add_pair(result_factory, human_factory, citation, question, ai, human):
    result_factory(
        citation=citation,
        question=question,
        selected_option=ai,
        status=ScreeningResultStatus.COMPLETED,
    )
    human_factory(citation=citation, question=question, selected_option=human)


@pytest.mark.parametrize("stage_factories", STAGE_FACTORIES)
def test_screening_metrics_across_questions_and_citations(stage_factories):
    stage, question_factory, option_factory, result_factory, human_factory = (
        stage_factories
    )
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    citations = [CitationFactory(dataset=dataset) for _ in range(5)]
    question = question_factory(review=review)
    second_question = question_factory(review=review)
    include_a = option_factory(
        question=question, screening_action=ScreeningActions.ScreenIn
    )
    include_b = option_factory(
        question=question, screening_action=ScreeningActions.ScreenIn
    )
    exclude = option_factory(
        question=question, screening_action=ScreeningActions.ScreenOut
    )
    second_exclude = option_factory(
        question=second_question,
        screening_action=ScreeningActions.ScreenOut,
    )

    for citation, ai, human in zip(
        citations,
        [include_a, include_a, include_a, exclude, exclude],
        [include_a, include_b, exclude, include_a, exclude],
    ):
        add_pair(result_factory, human_factory, citation, question, ai, human)
    add_pair(
        result_factory,
        human_factory,
        citations[0],
        second_question,
        second_exclude,
        second_exclude,
    )
    result_factory(
        citation=citations[1],
        question=second_question,
        selected_option=second_exclude,
        status=ScreeningResultStatus.COMPLETED,
    )
    human_factory(
        citation=citations[2],
        question=second_question,
        selected_option=second_exclude,
    )

    by_question, overall = get_screening_answer_metrics(review.id, stage)

    assert set(by_question) == {question.id, second_question.id}
    first = by_question[question.id]
    assert (
        first.true_positives,
        first.false_negatives,
        first.false_positives,
        first.true_negatives,
    ) == (2, 1, 1, 1)
    assert first.observations == 5
    assert first.exact_agreements == 2
    assert first.missing == 0
    assert first.accuracy == 2 / 5
    assert first.precision == 2 / 3
    assert first.recall == 2 / 3
    assert first.f1 == 2 / 3
    assert first.npv == 1 / 2

    second = by_question[second_question.id]
    assert second.observations == 1
    assert second.missing == 4
    assert second.true_negatives == 1
    assert second.accuracy == 1
    assert second.precision is None
    assert second.recall is None
    assert second.f1 is None
    assert second.npv == 1

    assert overall.observations == 6
    assert overall.missing == 4
    assert overall.exact_agreements == 3
    assert overall.accuracy == 1 / 2
    assert overall.precision == 2 / 3
    assert overall.recall == 2 / 3
    assert overall.f1 == 2 / 3
    assert overall.npv == 2 / 3


@pytest.mark.parametrize("stage_factories", STAGE_FACTORIES)
def test_screening_metrics_ignore_deleted_and_disabled_records(
    stage_factories,
):
    stage, question_factory, option_factory, result_factory, human_factory = (
        stage_factories
    )
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    citations = [CitationFactory(dataset=dataset) for _ in range(5)]
    question = question_factory(review=review)
    include = option_factory(question=question)
    deleted_option = option_factory(question=question)
    deleted_option.soft_delete()

    add_pair(
        result_factory,
        human_factory,
        citations[0],
        question,
        deleted_option,
        include,
    )
    add_pair(
        result_factory,
        human_factory,
        citations[1],
        question,
        include,
        deleted_option,
    )
    result_factory(
        citation=citations[2],
        question=question,
        selected_option=include,
        status=ScreeningResultStatus.PENDING,
    )
    human_factory(
        citation=citations[2], question=question, selected_option=include
    )
    add_pair(
        result_factory,
        human_factory,
        citations[3],
        question,
        include,
        include,
    )
    disabled = question_factory(review=review, disable_screening=True)
    disabled_option = option_factory(question=disabled)
    add_pair(
        result_factory,
        human_factory,
        citations[4],
        disabled,
        disabled_option,
        disabled_option,
    )
    deleted_question = question_factory(review=review)
    deleted_question_option = option_factory(question=deleted_question)
    add_pair(
        result_factory,
        human_factory,
        citations[4],
        deleted_question,
        deleted_question_option,
        deleted_question_option,
    )
    deleted_question.soft_delete()

    by_question, overall = get_screening_answer_metrics(review.id, stage)

    assert set(by_question) == {question.id}
    assert overall.observations == 1
    assert overall.missing == 4
    assert overall.accuracy == 1


@pytest.mark.parametrize("stage_factories", STAGE_FACTORIES)
def test_screening_metrics_use_most_recent_eligible_human_answer(
    stage_factories,
):
    stage, question_factory, option_factory, result_factory, human_factory = (
        stage_factories
    )
    review = ReviewFactory()
    citation = CitationFactory(dataset=CitationDatasetFactory(review=review))
    question = question_factory(review=review)
    include = option_factory(question=question)
    exclude = option_factory(
        question=question, screening_action=ScreeningActions.ScreenOut
    )
    result_factory(
        citation=citation,
        question=question,
        selected_option=include,
        status=ScreeningResultStatus.COMPLETED,
    )
    older = human_factory(
        citation=citation, question=question, selected_option=include
    )
    newer = human_factory(
        citation=citation, question=question, selected_option=exclude
    )
    older_updated = timezone.now() - timedelta(days=1)
    type(older).objects.filter(pk=older.pk).update(updated_at=older_updated)

    _, overall = get_screening_answer_metrics(review.id, stage)
    assert overall.observations == 1
    assert overall.false_negatives == 1
    assert overall.accuracy == 0

    type(older).objects.filter(pk=older.pk).update(
        updated_at=newer.updated_at + timedelta(days=1)
    )
    _, overall = get_screening_answer_metrics(review.id, stage)
    assert overall.true_positives == 1
    assert overall.accuracy == 1

    type(older).objects.filter(pk=older.pk).update(updated_at=newer.updated_at)
    _, overall = get_screening_answer_metrics(review.id, stage)
    assert overall.false_negatives == 1

    deleted_option = option_factory(question=question)
    deleted_answer = human_factory(
        citation=citation, question=question, selected_option=deleted_option
    )
    deleted_option.soft_delete()
    type(deleted_answer).objects.filter(pk=deleted_answer.pk).update(
        updated_at=newer.updated_at + timedelta(days=2)
    )
    _, overall = get_screening_answer_metrics(review.id, stage)
    assert overall.false_negatives == 1
    assert overall.observations == 1


@pytest.mark.parametrize("stage_factories", STAGE_FACTORIES)
def test_screening_metrics_are_isolated_by_review_and_stage(stage_factories):
    stage, question_factory, option_factory, result_factory, human_factory = (
        stage_factories
    )
    review = ReviewFactory()
    other_review = ReviewFactory()
    citation = CitationFactory(dataset=CitationDatasetFactory(review=review))
    other_citation = CitationFactory(
        dataset=CitationDatasetFactory(review=other_review)
    )
    question = question_factory(review=review)
    option = option_factory(question=question)
    other_question = question_factory(review=other_review)
    other_option = option_factory(question=other_question)
    add_pair(result_factory, human_factory, citation, question, option, option)
    add_pair(
        result_factory,
        human_factory,
        other_citation,
        other_question,
        other_option,
        other_option,
    )

    by_question, overall = get_screening_answer_metrics(review.id, stage)
    assert set(by_question) == {question.id}
    assert overall.observations == 1
    assert overall.missing == 0

    other_stage = ReviewStage.L2_SCREENING
    if stage == ReviewStage.L2_SCREENING:
        other_stage = ReviewStage.L1_SCREENING
    other_by_question, other_overall = get_screening_answer_metrics(
        review.id, other_stage
    )
    assert other_by_question == {}
    assert other_overall.observations == 0


def test_screening_metric_has_undefined_ratios_without_denominators():
    metric = ScreeningMetric()
    metric.add_missing()

    assert metric.missing == 1
    assert metric.observations == 0
    assert metric.accuracy is None
    assert metric.precision is None
    assert metric.recall is None
    assert metric.f1 is None
    assert metric.npv is None


@pytest.mark.parametrize("stage_factories", STAGE_FACTORIES)
def test_screening_metrics_use_four_queries_independent_of_answer_count(
    stage_factories, django_assert_num_queries
):
    stage, question_factory, option_factory, result_factory, human_factory = (
        stage_factories
    )
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    question = question_factory(review=review)
    option = option_factory(question=question)
    for _ in range(30):
        citation = CitationFactory(dataset=dataset)
        add_pair(
            result_factory,
            human_factory,
            citation,
            question,
            option,
            option,
        )

    with django_assert_num_queries(4):
        by_question, overall = get_screening_answer_metrics(review.id, stage)

    assert by_question[question.id].observations == 30
    assert overall.accuracy == 1

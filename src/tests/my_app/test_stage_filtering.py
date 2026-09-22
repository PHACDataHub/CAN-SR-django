from typing import NamedTuple

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
    get_adjacent_citation_ids,
    get_citations_for_stage,
    get_l2_screening_progress_stats,
    get_parameter_extraction_progress_stats,
)

pytestmark = pytest.mark.backend


class ScreeningLayer(NamedTuple):
    question_factory: type
    option_factory: type
    human_factory: type
    result_factory: type
    stage: ReviewStage


@pytest.fixture(
    params=[
        pytest.param(
            ScreeningLayer(
                L1ScreeningQuestionFactory,
                L1ScreeningQuestionOptionFactory,
                L1HumanAnswerFactory,
                L1ScreeningResultFactory,
                ReviewStage.L2_SCREENING,
            ),
            id="L1-answers-for-L2",
        ),
        pytest.param(
            ScreeningLayer(
                L2ScreeningQuestionFactory,
                L2ScreeningQuestionOptionFactory,
                L2HumanAnswerFactory,
                L2ScreeningResultFactory,
                ReviewStage.PARAMETER_EXTRACTION,
            ),
            id="L2-answers-for-parameters",
        ),
    ]
)
def screening_layer(request):
    return request.param


def test_stage_filter_requires_a_passing_answer_to_every_active_question(
    screening_layer,
):
    layer = screening_layer
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    included = CitationFactory(dataset=dataset, order=1)
    missing_answer = CitationFactory(dataset=dataset, order=2)
    excluded_answer = CitationFactory(dataset=dataset, order=3)
    first_question = layer.question_factory(review=review)
    second_question = layer.question_factory(review=review)
    first_in = layer.option_factory(
        question=first_question, screening_action=ScreeningActions.ScreenIn
    )
    second_in = layer.option_factory(
        question=second_question, screening_action=ScreeningActions.ScreenIn
    )
    second_out = layer.option_factory(
        question=second_question, screening_action=ScreeningActions.ScreenOut
    )

    for citation in (included, missing_answer, excluded_answer):
        layer.human_factory(
            citation=citation,
            question=first_question,
            selected_option=first_in,
        )
    layer.result_factory(
        citation=included,
        question=second_question,
        selected_option=second_in,
        status=ScreeningResultStatus.COMPLETED,
    )
    layer.human_factory(
        citation=excluded_answer,
        question=second_question,
        selected_option=second_out,
    )

    assert list(get_citations_for_stage(review.id, layer.stage)) == [included]
    assert list(
        get_citations_for_stage(review.id, ReviewStage.L1_SCREENING)
    ) == [
        included,
        missing_answer,
        excluded_answer,
    ]


def test_stage_filter_human_exclusion_overrides_ai_inclusion(screening_layer):
    layer = screening_layer
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    screened_in = layer.option_factory(
        question=question, screening_action=ScreeningActions.ScreenIn
    )
    screened_out = layer.option_factory(
        question=question, screening_action=ScreeningActions.ScreenOut
    )
    layer.result_factory(
        citation=citation,
        question=question,
        selected_option=screened_in,
        status=ScreeningResultStatus.COMPLETED,
    )
    layer.human_factory(
        citation=citation, question=question, selected_option=screened_out
    )

    assert not get_citations_for_stage(
        citation.dataset.review_id, layer.stage
    ).exists()


def test_stage_filter_human_inclusion_overrides_ai_exclusion(screening_layer):
    layer = screening_layer
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    screened_in = layer.option_factory(
        question=question, screening_action=ScreeningActions.ScreenIn
    )
    screened_out = layer.option_factory(
        question=question, screening_action=ScreeningActions.ScreenOut
    )
    layer.result_factory(
        citation=citation,
        question=question,
        selected_option=screened_out,
        status=ScreeningResultStatus.COMPLETED,
    )
    layer.human_factory(
        citation=citation, question=question, selected_option=screened_in
    )

    assert list(
        get_citations_for_stage(citation.dataset.review_id, layer.stage)
    ) == [citation]


def test_stage_filter_deleted_options_cannot_screen_in_a_citation(
    screening_layer,
):
    layer = screening_layer
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    human_citation = CitationFactory(dataset=dataset, order=1)
    ai_citation = CitationFactory(dataset=dataset, order=2)
    question = layer.question_factory(review=review)
    deleted_option = layer.option_factory(
        question=question, screening_action=ScreeningActions.ScreenIn
    )
    deleted_option.soft_delete()
    layer.human_factory(
        citation=human_citation,
        question=question,
        selected_option=deleted_option,
    )
    layer.result_factory(
        citation=ai_citation,
        question=question,
        selected_option=deleted_option,
        status=ScreeningResultStatus.COMPLETED,
    )

    assert not get_citations_for_stage(review.id, layer.stage).exists()


def test_stage_filter_ignores_deleted_questions_and_their_answers(
    screening_layer,
):
    layer = screening_layer
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    included = CitationFactory(dataset=dataset, order=1)
    missing_active_answer = CitationFactory(dataset=dataset, order=2)
    active_question = layer.question_factory(review=review)
    deleted_question = layer.question_factory(review=review)
    active_option = layer.option_factory(
        question=active_question, screening_action=ScreeningActions.ScreenIn
    )
    deleted_question_option = layer.option_factory(
        question=deleted_question,
        screening_action=ScreeningActions.ScreenOut,
    )
    layer.human_factory(
        citation=included,
        question=active_question,
        selected_option=active_option,
    )
    for citation in (included, missing_active_answer):
        layer.human_factory(
            citation=citation,
            question=deleted_question,
            selected_option=deleted_question_option,
        )
    deleted_question.soft_delete()

    assert list(get_citations_for_stage(review.id, layer.stage)) == [included]


def test_stage_filter_disabled_question_ignores_missing_and_excluding_answers(
    screening_layer,
):
    layer = screening_layer
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    no_disabled_answer = CitationFactory(dataset=dataset, order=1)
    human_excluded = CitationFactory(dataset=dataset, order=2)
    ai_excluded = CitationFactory(dataset=dataset, order=3)
    missing_active_answer = CitationFactory(dataset=dataset, order=4)
    active_question = layer.question_factory(review=review)
    disabled_question = layer.question_factory(
        review=review, disable_screening=True
    )
    active_in = layer.option_factory(
        question=active_question, screening_action=ScreeningActions.ScreenIn
    )
    disabled_out = layer.option_factory(
        question=disabled_question, screening_action=ScreeningActions.ScreenOut
    )
    for citation in (no_disabled_answer, human_excluded, ai_excluded):
        layer.human_factory(
            citation=citation,
            question=active_question,
            selected_option=active_in,
        )
    layer.human_factory(
        citation=human_excluded,
        question=disabled_question,
        selected_option=disabled_out,
    )
    layer.result_factory(
        citation=ai_excluded,
        question=disabled_question,
        selected_option=disabled_out,
        status=ScreeningResultStatus.COMPLETED,
    )

    assert list(get_citations_for_stage(review.id, layer.stage)) == [
        no_disabled_answer,
        human_excluded,
        ai_excluded,
    ]


def test_stage_filter_all_disabled_questions_include_every_citation(
    screening_layer,
):
    layer = screening_layer
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    citations = [
        CitationFactory(dataset=dataset, order=1),
        CitationFactory(dataset=dataset, order=2),
    ]
    layer.question_factory(review=review, disable_screening=True)

    assert list(get_citations_for_stage(review.id, layer.stage)) == citations


def test_stage_filter_requires_completed_ai_result(screening_layer):
    layer = screening_layer
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    screened_in = layer.option_factory(
        question=question, screening_action=ScreeningActions.ScreenIn
    )
    layer.result_factory(
        citation=citation,
        question=question,
        selected_option=screened_in,
        status=ScreeningResultStatus.PENDING,
    )

    assert not get_citations_for_stage(
        citation.dataset.review_id, layer.stage
    ).exists()


def test_stage_filter_review_override_includes_all_citations(screening_layer):
    layer = screening_layer
    review = ReviewFactory(disable_filtering=True)
    dataset = CitationDatasetFactory(review=review)
    citations = [
        CitationFactory(dataset=dataset, order=1),
        CitationFactory(dataset=dataset, order=2),
    ]
    layer.question_factory(review=review)

    assert list(get_citations_for_stage(review.id, layer.stage)) == citations
    assert (
        list(get_citations_for_stage(review.id, ReviewStage.L1_SCREENING))
        == citations
    )


def test_stage_filter_navigation_and_metrics_use_screened_citations(
    screening_layer,
):
    layer = screening_layer
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    first = CitationFactory(dataset=dataset, order=1)
    excluded = CitationFactory(dataset=dataset, order=2)
    last = CitationFactory(dataset=dataset, order=3)
    question = layer.question_factory(review=review)
    screened_in = layer.option_factory(
        question=question, screening_action=ScreeningActions.ScreenIn
    )
    for citation in (first, last):
        layer.human_factory(
            citation=citation,
            question=question,
            selected_option=screened_in,
        )

    assert get_adjacent_citation_ids(first.id, layer.stage) == (None, last.id)
    assert get_adjacent_citation_ids(last.id, layer.stage) == (first.id, None)
    if layer.stage == ReviewStage.L2_SCREENING:
        stats = get_l2_screening_progress_stats(review.id)
    else:
        stats = get_parameter_extraction_progress_stats(review.id)
    assert stats.total_citations == 2

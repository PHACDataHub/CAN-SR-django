from typing import NamedTuple

import pytest

from my_app.constants import DEFAULT_CONFIDENCE
from my_app.model_factories import (
    CitationFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L1ScreeningResultFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    L2ScreeningResultFactory,
)
from my_app.models import (
    Citation,
    CitationAIStatus,
    L1CriticalScreeningResult,
    L2CriticalScreeningResult,
    ScreeningActions,
    ScreeningResultStatus,
)

pytestmark = pytest.mark.backend


class ScreeningLayer(NamedTuple):
    question_factory: type
    option_factory: type
    result_factory: type
    critical_result_model: type
    annotation_method: str
    annotation_field: str


@pytest.fixture(
    params=[
        pytest.param(
            ScreeningLayer(
                L1ScreeningQuestionFactory,
                L1ScreeningQuestionOptionFactory,
                L1ScreeningResultFactory,
                L1CriticalScreeningResult,
                "add_l1_ai_status",
                "l1_ai_status",
            ),
            id="L1",
        ),
        pytest.param(
            ScreeningLayer(
                L2ScreeningQuestionFactory,
                L2ScreeningQuestionOptionFactory,
                L2ScreeningResultFactory,
                L2CriticalScreeningResult,
                "add_l2_ai_status",
                "l2_ai_status",
            ),
            id="L2",
        ),
    ]
)
def layer(request):
    return request.param


def get_status(layer, citation):
    queryset = getattr(Citation.objects, layer.annotation_method)()
    return getattr(queryset.get(pk=citation.pk), layer.annotation_field)


def make_result(
    layer,
    citation,
    question,
    action=ScreeningActions.ScreenIn,
    confidence=DEFAULT_CONFIDENCE,
    critical_confidence=DEFAULT_CONFIDENCE,
    status=ScreeningResultStatus.COMPLETED,
    critical_status=ScreeningResultStatus.COMPLETED,
    with_critical=True,
):
    option = layer.option_factory(question=question, screening_action=action)
    result = layer.result_factory(
        citation=citation,
        question=question,
        selected_option=option,
        status=status,
        confidence=confidence,
    )
    if with_critical:
        layer.critical_result_model.objects.create(
            initial_result=result,
            status=critical_status,
            confidence=critical_confidence,
        )
    return result


def test_no_active_questions_or_missing_result_is_not_screened(layer):
    # It should stay unscreened until every active question has a result.
    citation = CitationFactory()
    assert get_status(layer, citation) == CitationAIStatus.NotScreenedYet

    layer.question_factory(review=citation.dataset.review)
    assert get_status(layer, citation) == CitationAIStatus.NotScreenedYet


@pytest.mark.parametrize(
    "status, expected",
    [
        (ScreeningResultStatus.PENDING, CitationAIStatus.NotScreenedYet),
        (ScreeningResultStatus.NOT_STARTED, CitationAIStatus.NotScreenedYet),
        (
            ScreeningResultStatus.ABANDONED,
            CitationAIStatus.AmbiguouslyIncluded,
        ),
    ],
)
def test_incomplete_result_status(layer, status, expected):
    # It should treat pending work as unscreened and abandoned work as ambiguous.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    layer.result_factory(citation=citation, question=question, status=status)

    assert get_status(layer, citation) == expected


@pytest.mark.parametrize(
    "action, expected",
    [
        (ScreeningActions.ScreenIn, CitationAIStatus.ConfidentlyIncluded),
        (ScreeningActions.ScreenOut, CitationAIStatus.AutoExcluded),
    ],
)
def test_confident_completed_result(layer, action, expected):
    # It should include a confirmed screen-in or exclude a confirmed screen-out.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    make_result(layer, citation, question, action=action)

    assert get_status(layer, citation) == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"confidence": 0.89},
        {"critical_confidence": 0.89},
        {"confidence": None},
        {"critical_confidence": None},
        {"with_critical": False},
        {"critical_status": ScreeningResultStatus.PENDING},
        {"critical_status": ScreeningResultStatus.ABANDONED},
    ],
)
@pytest.mark.parametrize(
    "action", [ScreeningActions.ScreenIn, ScreeningActions.ScreenOut]
)
def test_unconfident_or_inconsistent_result_is_ambiguous(
    layer, kwargs, action
):
    # It should not trust either action without sufficient, completed confirmation.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    make_result(layer, citation, question, action=action, **kwargs)

    assert get_status(layer, citation) == CitationAIStatus.AmbiguouslyIncluded


def test_critical_selected_option_is_ambiguous(layer):
    # It should be ambiguous when the critical result disagrees with the first.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    result = make_result(layer, citation, question)
    critical = result.critical_result
    critical.selected_option = result.selected_option
    critical.save(update_fields=["selected_option"])

    assert get_status(layer, citation) == CitationAIStatus.AmbiguouslyIncluded


@pytest.mark.parametrize(
    "action", [ScreeningActions.ScreenIn, ScreeningActions.ScreenOut]
)
def test_deleted_option_is_ambiguous(layer, action):
    # It should not trust a result whose selected option was deleted.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    result = make_result(layer, citation, question, action=action)
    result.selected_option.soft_delete()
    assert get_status(layer, citation) == CitationAIStatus.AmbiguouslyIncluded


def test_wrong_question_option_is_ambiguous(layer):
    # It should not trust an option selected from a different question.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    result = make_result(layer, citation, question)
    other_question = layer.question_factory(review=citation.dataset.review)
    other_option = layer.option_factory(question=other_question)
    result.selected_option = other_option
    result.save(update_fields=["selected_option"])
    other_question.soft_delete()
    assert get_status(layer, citation) == CitationAIStatus.AmbiguouslyIncluded


def test_missing_selected_option_is_ambiguous(layer):
    # It should be ambiguous when a completed result has no selected option.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    result = make_result(layer, citation, question)
    result.selected_option = None
    result.save(update_fields=["selected_option"])

    assert get_status(layer, citation) == CitationAIStatus.AmbiguouslyIncluded


@pytest.mark.parametrize(
    "question_threshold, review_threshold, confidence, expected",
    [
        (None, None, 0.9, CitationAIStatus.ConfidentlyIncluded),
        (None, 0.8, 0.8, CitationAIStatus.ConfidentlyIncluded),
        (0.7, 0.8, 0.7, CitationAIStatus.ConfidentlyIncluded),
        (0.9, 0.8, 0.8, CitationAIStatus.AmbiguouslyIncluded),
        (0.0, 0.9, 0.0, CitationAIStatus.ConfidentlyIncluded),
    ],
)
def test_threshold_fallback_and_equality(
    layer, question_threshold, review_threshold, confidence, expected
):
    # It should use question, review, then default thresholds, accepting equality.
    citation = CitationFactory()
    review = citation.dataset.review
    review.confidence = review_threshold
    review.save(update_fields=["confidence"])
    question = layer.question_factory(
        review=review, confidence=question_threshold
    )
    make_result(
        layer,
        citation,
        question,
        confidence=confidence,
        critical_confidence=confidence,
    )

    assert get_status(layer, citation) == expected


def test_auto_exclusion_precedes_missing_pending_and_ambiguous(layer):
    # It should exclude once any active question has a confirmed screen-out.
    citation = CitationFactory()
    review = citation.dataset.review
    excluded_question = layer.question_factory(review=review)
    pending_question = layer.question_factory(review=review)
    layer.question_factory(review=review)
    make_result(
        layer,
        citation,
        excluded_question,
        action=ScreeningActions.ScreenOut,
    )
    layer.result_factory(citation=citation, question=pending_question)

    assert get_status(layer, citation) == CitationAIStatus.AutoExcluded


def test_missing_or_pending_precedes_ambiguous(layer):
    # It should remain unscreened while an active question is missing or pending.
    citation = CitationFactory()
    review = citation.dataset.review
    abandoned_question = layer.question_factory(review=review)
    pending_question = layer.question_factory(review=review)
    missing_question = layer.question_factory(review=review)
    layer.result_factory(
        citation=citation,
        question=abandoned_question,
        status=ScreeningResultStatus.ABANDONED,
    )
    layer.result_factory(citation=citation, question=pending_question)

    assert get_status(layer, citation) == CitationAIStatus.NotScreenedYet

    pending_question.soft_delete()
    # It should still be unscreened while another active question lacks a result.
    assert get_status(layer, citation) == CitationAIStatus.NotScreenedYet

    missing_question.soft_delete()
    # It should become ambiguous once only the abandoned result remains.
    assert get_status(layer, citation) == CitationAIStatus.AmbiguouslyIncluded


def test_deleted_and_disabled_questions_are_ignored(layer):
    # It should judge only active, enabled questions, even when others exclude.
    citation = CitationFactory()
    review = citation.dataset.review
    active_question = layer.question_factory(review=review)
    deleted_question = layer.question_factory(review=review)
    disabled_question = layer.question_factory(
        review=review, disable_screening=True
    )
    make_result(layer, citation, active_question)
    make_result(
        layer, citation, deleted_question, action=ScreeningActions.ScreenOut
    )
    make_result(
        layer, citation, disabled_question, action=ScreeningActions.ScreenOut
    )
    deleted_question.soft_delete()

    assert get_status(layer, citation) == CitationAIStatus.ConfidentlyIncluded

    active_question.soft_delete()
    # It should be unscreened when no active, enabled questions remain.
    assert get_status(layer, citation) == CitationAIStatus.NotScreenedYet


def test_result_for_another_review_is_ignored(layer):
    # It should ignore a result tied to a question outside the citation's review.
    citation = CitationFactory()
    active_question = layer.question_factory(review=citation.dataset.review)
    other_citation = CitationFactory()
    other_question = layer.question_factory(
        review=other_citation.dataset.review
    )
    make_result(layer, citation, active_question)
    make_result(
        layer, citation, other_question, action=ScreeningActions.ScreenOut
    )

    assert get_status(layer, citation) == CitationAIStatus.ConfidentlyIncluded


def test_annotation_is_opt_in_chainable_and_stage_specific(layer):
    # It should add only requested statuses and support queryset filtering.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    make_result(layer, citation, question)

    assert not hasattr(
        Citation.objects.get(pk=citation.pk), layer.annotation_field
    )
    queryset = getattr(
        Citation.objects.filter(pk=citation.pk), layer.annotation_method
    )()
    assert list(
        queryset.filter(
            **{layer.annotation_field: CitationAIStatus.ConfidentlyIncluded}
        ).values_list("pk", flat=True)
    ) == [citation.pk]

    both = (
        Citation.objects.add_l1_ai_status()
        .add_l2_ai_status()
        .get(pk=citation.pk)
    )
    assert (
        getattr(both, layer.annotation_field)
        == CitationAIStatus.ConfidentlyIncluded
    )
    other_field = (
        "l2_ai_status"
        if layer.annotation_field == "l1_ai_status"
        else "l1_ai_status"
    )
    assert getattr(both, other_field) == CitationAIStatus.NotScreenedYet

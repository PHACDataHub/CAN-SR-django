from typing import NamedTuple

import pytest
from freezegun import freeze_time

from my_app.model_factories import (
    CitationFactory,
    L1HumanAnswerFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L2HumanAnswerFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
)
from my_app.models import (
    Citation,
    CitationAIStatus,
    CitationHumanStatus,
    ScreeningActions,
)

pytestmark = pytest.mark.backend


class ScreeningLayer(NamedTuple):
    question_factory: type
    option_factory: type
    answer_factory: type
    annotation_method: str
    annotation_field: str
    other_field: str


@pytest.fixture(
    params=[
        pytest.param(
            ScreeningLayer(
                L1ScreeningQuestionFactory,
                L1ScreeningQuestionOptionFactory,
                L1HumanAnswerFactory,
                "add_l1_human_status",
                "l1_human_status",
                "l2_human_status",
            ),
            id="L1",
        ),
        pytest.param(
            ScreeningLayer(
                L2ScreeningQuestionFactory,
                L2ScreeningQuestionOptionFactory,
                L2HumanAnswerFactory,
                "add_l2_human_status",
                "l2_human_status",
                "l1_human_status",
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


def make_answer(layer, citation, question, action=ScreeningActions.ScreenIn):
    return layer.answer_factory(
        citation=citation,
        question=question,
        selected_option=layer.option_factory(
            question=question, screening_action=action
        ),
    )


def test_no_questions_or_missing_answers_is_unanswered(layer):
    # No questions or incomplete coverage must stay unanswered rather than
    # imply inclusion.
    citation = CitationFactory()
    assert get_status(layer, citation) == CitationHumanStatus.Unanswered
    question = layer.question_factory(review=citation.dataset.review)
    assert get_status(layer, citation) == CitationHumanStatus.Unanswered
    make_answer(layer, citation, question)
    layer.question_factory(review=citation.dataset.review)
    assert get_status(layer, citation) == CitationHumanStatus.Unanswered


def test_all_questions_included(layer):
    # Every active question needs an inclusion answer before the citation can
    # be included.
    citation = CitationFactory()
    for _ in range(2):
        question = layer.question_factory(review=citation.dataset.review)
        make_answer(layer, citation, question)
    assert get_status(layer, citation) == CitationHumanStatus.In


def test_exclusion_precedes_missing_and_included_answers(layer):
    # A single exclusion must decide the citation even when other answers are
    # missing or include.
    citation = CitationFactory()
    review = citation.dataset.review
    included = layer.question_factory(review=review)
    excluded = layer.question_factory(review=review)
    layer.question_factory(review=review)
    make_answer(layer, citation, included)
    make_answer(layer, citation, excluded, ScreeningActions.ScreenOut)
    assert get_status(layer, citation) == CitationHumanStatus.Out


@pytest.mark.parametrize(
    "latest_action, expected",
    [
        (ScreeningActions.ScreenIn, CitationHumanStatus.In),
        (ScreeningActions.ScreenOut, CitationHumanStatus.Out),
    ],
)
def test_only_latest_answer_counts(layer, latest_action, expected):
    # Only the newest answer per question counts, so older disagreements cannot
    # affect the status.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    for action in [ScreeningActions.ScreenIn, ScreeningActions.ScreenOut]:
        with freeze_time("2026-01-01"):
            make_answer(layer, citation, question, action)
    with freeze_time("2026-01-02"):
        make_answer(layer, citation, question, latest_action)
    assert get_status(layer, citation) == expected


def test_latest_update_precedes_creation_order(layer):
    # Editing an older answer makes it the latest decision, regardless of
    # creation order.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    with freeze_time("2026-01-01"):
        first = make_answer(layer, citation, question)
    with freeze_time("2026-01-02"):
        make_answer(layer, citation, question, ScreeningActions.ScreenOut)
    with freeze_time("2026-01-03"):
        first.save()
    assert get_status(layer, citation) == CitationHumanStatus.In


def test_latest_id_breaks_timestamp_tie(layer):
    # Equal update timestamps use the higher ID so the latest decision is
    # deterministic.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    with freeze_time("2026-01-01"):
        make_answer(layer, citation, question, ScreeningActions.ScreenOut)
        make_answer(layer, citation, question)
    assert get_status(layer, citation) == CitationHumanStatus.In


@pytest.mark.parametrize("invalid_option", ["deleted", "wrong_question"])
@pytest.mark.parametrize(
    "action", [ScreeningActions.ScreenIn, ScreeningActions.ScreenOut]
)
def test_invalid_latest_answer_is_unanswered(layer, invalid_option, action):
    # An invalid latest option leaves the question unanswered without reviving
    # older decisions.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    with freeze_time("2026-01-01"):
        make_answer(layer, citation, question, ScreeningActions.ScreenOut)
    with freeze_time("2026-01-02"):
        answer = make_answer(layer, citation, question, action)
    if invalid_option == "deleted":
        answer.selected_option.soft_delete()
    else:
        other_question = layer.question_factory(review=citation.dataset.review)
        answer.selected_option = layer.option_factory(
            question=other_question, screening_action=action
        )
        answer.save(update_fields=["selected_option"])
        other_question.soft_delete()
    assert get_status(layer, citation) == CitationHumanStatus.Unanswered


def test_deleted_disabled_and_other_review_questions_are_ignored(layer):
    # Only active questions in this review matter; ignored questions must
    # neither exclude nor require answers.
    citation = CitationFactory()
    review = citation.dataset.review
    active = layer.question_factory(review=review)
    deleted = layer.question_factory(review=review)
    disabled = layer.question_factory(review=review, disable_screening=True)
    other_review = layer.question_factory()
    make_answer(layer, citation, active)
    for question in [deleted, disabled, other_review]:
        make_answer(layer, citation, question, ScreeningActions.ScreenOut)
    deleted.soft_delete()
    layer.question_factory(review=review, disable_screening=True)
    missing_deleted = layer.question_factory(review=review)
    missing_deleted.soft_delete()
    assert get_status(layer, citation) == CitationHumanStatus.In
    active.soft_delete()
    assert get_status(layer, citation) == CitationHumanStatus.Unanswered


def test_answers_for_another_citation_are_ignored(layer):
    # Answers are scoped to each citation so one citation cannot inherit
    # another's decision.
    citation = CitationFactory()
    other_citation = CitationFactory(dataset=citation.dataset)
    question = layer.question_factory(review=citation.dataset.review)
    make_answer(layer, other_citation, question, ScreeningActions.ScreenOut)
    assert get_status(layer, citation) == CitationHumanStatus.Unanswered
    make_answer(layer, citation, question)
    assert get_status(layer, citation) == CitationHumanStatus.In


def test_annotation_is_opt_in_chainable_and_stage_specific(layer):
    # Optional annotations must support filtering and compose across stages and
    # AI statuses without interference.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    make_answer(layer, citation, question)
    assert not hasattr(
        Citation.objects.get(pk=citation.pk), layer.annotation_field
    )
    queryset = getattr(
        Citation.objects.filter(pk=citation.pk), layer.annotation_method
    )()
    assert list(
        queryset.filter(
            **{layer.annotation_field: CitationHumanStatus.In}
        ).values_list("pk", flat=True)
    ) == [citation.pk]
    both = (
        Citation.objects.add_l1_human_status()
        .add_l2_human_status()
        .add_l1_ai_status()
        .add_l2_ai_status()
        .get(pk=citation.pk)
    )
    assert getattr(both, layer.annotation_field) == CitationHumanStatus.In
    assert getattr(both, layer.other_field) == CitationHumanStatus.Unanswered
    assert both.l1_ai_status == CitationAIStatus.NotScreenedYet
    assert both.l2_ai_status == CitationAIStatus.NotScreenedYet


@pytest.mark.parametrize("citation_count", [1, 10])
def test_annotation_does_not_add_queries_per_citation(
    layer, citation_count, django_assert_num_queries
):
    # Fetching and reading both statuses must use one query as citation count
    # grows.
    first = CitationFactory()
    citations = [first] + CitationFactory.create_batch(
        citation_count - 1, dataset=first.dataset
    )
    questions = layer.question_factory.create_batch(
        2, review=first.dataset.review
    )
    for citation in citations:
        for question in questions:
            make_answer(layer, citation, question)

    with django_assert_num_queries(1):
        queryset = (
            Citation.objects.filter(dataset=first.dataset)
            .add_l1_human_status()
            .add_l2_human_status()
        )
        statuses = [
            (
                getattr(citation, layer.annotation_field),
                getattr(citation, layer.other_field),
            )
            for citation in queryset
        ]
        assert (
            statuses
            == [(CitationHumanStatus.In, CitationHumanStatus.Unanswered)]
            * citation_count
        )

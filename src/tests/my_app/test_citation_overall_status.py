from typing import NamedTuple

import pytest
from freezegun import freeze_time

from my_app.constants import DEFAULT_CONFIDENCE
from my_app.model_factories import (
    CitationFactory,
    L1HumanAnswerFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L1ScreeningResultFactory,
    L2HumanAnswerFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    L2ScreeningResultFactory,
)
from my_app.models import (
    Citation,
    CitationAIStatus,
    CitationHumanStatus,
    CitationStatus,
    L1CriticalScreeningResult,
    L2CriticalScreeningResult,
    ScreeningActions,
    ScreeningResultStatus,
)
from my_app.queries import ReviewStage, get_citations_for_stage

pytestmark = pytest.mark.backend


class ScreeningLayer(NamedTuple):
    question_factory: type
    option_factory: type
    human_factory: type
    result_factory: type
    critical_model: type
    stage: str

    @property
    def field(self):
        return f"{self.stage}_overall_status"


@pytest.fixture(
    params=[
        pytest.param(
            ScreeningLayer(
                L1ScreeningQuestionFactory,
                L1ScreeningQuestionOptionFactory,
                L1HumanAnswerFactory,
                L1ScreeningResultFactory,
                L1CriticalScreeningResult,
                "l1",
            ),
            id="L1",
        ),
        pytest.param(
            ScreeningLayer(
                L2ScreeningQuestionFactory,
                L2ScreeningQuestionOptionFactory,
                L2HumanAnswerFactory,
                L2ScreeningResultFactory,
                L2CriticalScreeningResult,
                "l2",
            ),
            id="L2",
        ),
    ]
)
def layer(request):
    return request.param


def get_status(layer, citation):
    queryset = getattr(Citation.objects, f"add_{layer.stage}_overall_status")()
    return getattr(queryset.get(pk=citation.pk), layer.field)


def make_human(layer, citation, question, action=ScreeningActions.ScreenIn):
    return layer.human_factory(
        citation=citation,
        question=question,
        selected_option=layer.option_factory(
            question=question, screening_action=action
        ),
    )


def make_ai(
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
    result = layer.result_factory(
        citation=citation,
        question=question,
        status=status,
        confidence=confidence,
        selected_option=layer.option_factory(
            question=question, screening_action=action
        ),
    )
    if with_critical:
        layer.critical_model.objects.create(
            initial_result=result,
            status=critical_status,
            confidence=critical_confidence,
        )
    return result


def test_no_active_answers_is_unanswered(layer):
    # Empty reviews and unanswered questions must not imply inclusion.
    citation = CitationFactory()
    assert get_status(layer, citation) == CitationStatus.Unanswered
    layer.question_factory(review=citation.dataset.review)
    assert get_status(layer, citation) == CitationStatus.Unanswered


@pytest.mark.parametrize("source", ["human", "ai"])
@pytest.mark.parametrize(
    "action, expected",
    [
        (ScreeningActions.ScreenIn, CitationStatus.In),
        (ScreeningActions.ScreenOut, CitationStatus.Out),
    ],
)
def test_single_source_decision(layer, source, action, expected):
    # Each source can independently decide a citation using a valid answer.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    if source == "human":
        make_human(layer, citation, question, action)
    else:
        make_ai(layer, citation, question, action)
    assert get_status(layer, citation) == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"confidence": 0.89},
        {"critical_confidence": 0.89},
        {"confidence": None},
        {"critical_confidence": None},
        {"with_critical": False},
        {"status": ScreeningResultStatus.PENDING},
        {"status": ScreeningResultStatus.NOT_STARTED},
        {"status": ScreeningResultStatus.ABANDONED},
        {"critical_status": ScreeningResultStatus.PENDING},
        {"critical_status": ScreeningResultStatus.NOT_STARTED},
        {"critical_status": ScreeningResultStatus.ABANDONED},
    ],
)
@pytest.mark.parametrize(
    "action", [ScreeningActions.ScreenIn, ScreeningActions.ScreenOut]
)
def test_unconfirmed_ai_is_ambiguous(layer, kwargs, action):
    # AI records exist, but neither action is decisive without completed
    # confirmation.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    make_ai(layer, citation, question, action=action, **kwargs)
    assert get_status(layer, citation) == CitationStatus.Ambiguous


@pytest.mark.parametrize(
    "action", [ScreeningActions.ScreenIn, ScreeningActions.ScreenOut]
)
def test_critical_disagreement_is_ambiguous(layer, action):
    # A critical result selecting an option cannot confirm the initial
    # decision.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    result = make_ai(layer, citation, question, action)
    critical = result.critical_result
    critical.selected_option = result.selected_option
    critical.save(update_fields=["selected_option"])
    assert get_status(layer, citation) == CitationStatus.Ambiguous


@pytest.mark.parametrize(
    "question_threshold, review_threshold, confidence, expected",
    [
        (None, None, DEFAULT_CONFIDENCE, CitationStatus.In),
        (None, 0.8, 0.8, CitationStatus.In),
        (0.7, 0.8, 0.7, CitationStatus.In),
        (0.9, 0.8, 0.8, CitationStatus.Ambiguous),
        (0.0, 0.9, 0.0, CitationStatus.In),
    ],
)
@pytest.mark.parametrize(
    "action", [ScreeningActions.ScreenIn, ScreeningActions.ScreenOut]
)
def test_ai_threshold_fallback_and_equality(
    layer, question_threshold, review_threshold, confidence, expected, action
):
    # Both AI actions use question/review/default thresholds and accept
    # equality.
    citation = CitationFactory()
    review = citation.dataset.review
    review.confidence = review_threshold
    review.save(update_fields=["confidence"])
    question = layer.question_factory(
        review=review, confidence=question_threshold
    )
    make_ai(
        layer,
        citation,
        question,
        action,
        confidence=confidence,
        critical_confidence=confidence,
    )
    if expected == CitationStatus.In and action == ScreeningActions.ScreenOut:
        expected = CitationStatus.Out
    assert get_status(layer, citation) == expected


@pytest.mark.parametrize("source", ["human", "ai"])
@pytest.mark.parametrize("invalid", ["deleted", "wrong_question"])
@pytest.mark.parametrize(
    "action", [ScreeningActions.ScreenIn, ScreeningActions.ScreenOut]
)
def test_invalid_options_are_ambiguous(layer, source, invalid, action):
    # Invalid options supply no decision, but their records prevent Unanswered.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    if source == "human":
        answer = make_human(layer, citation, question, action)
    else:
        answer = make_ai(layer, citation, question, action)
    if invalid == "deleted":
        answer.selected_option.soft_delete()
    else:
        other_question = layer.question_factory(review=citation.dataset.review)
        answer.selected_option = layer.option_factory(
            question=other_question, screening_action=action
        )
        answer.save(update_fields=["selected_option"])
        other_question.soft_delete()
    assert get_status(layer, citation) == CitationStatus.Ambiguous


def test_missing_ai_selected_option_is_ambiguous(layer):
    # Completed AI work without an option is still an answer record, not a
    # decision.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    result = make_ai(layer, citation, question)
    result.selected_option = None
    result.save(update_fields=["selected_option"])
    assert get_status(layer, citation) == CitationStatus.Ambiguous


@pytest.mark.parametrize(
    "human_action, expected",
    [
        (ScreeningActions.ScreenIn, CitationStatus.In),
        (ScreeningActions.ScreenOut, CitationStatus.Out),
    ],
)
def test_latest_human_overrides_conflicting_ai(layer, human_action, expected):
    # Superseded human answers and conflicting AI must not defeat the latest
    # human.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    if human_action == ScreeningActions.ScreenIn:
        opposite = ScreeningActions.ScreenOut
    else:
        opposite = ScreeningActions.ScreenIn
    make_ai(layer, citation, question, opposite)
    with freeze_time("2026-01-01"):
        make_human(layer, citation, question, opposite)
    with freeze_time("2026-01-02"):
        make_human(layer, citation, question, human_action)
    assert get_status(layer, citation) == expected


def test_human_update_and_id_determine_latest_answer(layer):
    # Equal timestamps use ID; later edits override creation order
    # consistently.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    with freeze_time("2026-01-01"):
        first = make_human(layer, citation, question)
        make_human(layer, citation, question, ScreeningActions.ScreenOut)
    assert get_status(layer, citation) == CitationStatus.Out
    with freeze_time("2026-01-02"):
        first.save()
    assert get_status(layer, citation) == CitationStatus.In


@pytest.mark.parametrize(
    "action, expected",
    [
        (ScreeningActions.ScreenIn, CitationStatus.In),
        (ScreeningActions.ScreenOut, CitationStatus.Out),
    ],
)
def test_invalid_latest_human_allows_valid_ai_fallback(
    layer, action, expected
):
    # An invalid human option supplies neither an override nor an older
    # decision.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    make_ai(layer, citation, question, action)
    with freeze_time("2026-01-01"):
        make_human(layer, citation, question, ScreeningActions.ScreenOut)
    with freeze_time("2026-01-02"):
        latest = make_human(layer, citation, question)
    latest.selected_option.soft_delete()
    assert get_status(layer, citation) == expected


@pytest.mark.parametrize("source", ["human", "ai"])
@pytest.mark.parametrize("exclusion_source", ["human", "ai"])
def test_inclusion_requires_every_question_but_exclusion_is_immediate(
    layer, source, exclusion_source
):
    # Partial coverage is ambiguous, while any decisive exclusion wins over
    # gaps.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    missing = layer.question_factory(review=citation.dataset.review)
    if source == "human":
        make_human(layer, citation, question)
    else:
        make_ai(layer, citation, question)
    assert get_status(layer, citation) == CitationStatus.Ambiguous
    if exclusion_source == "human":
        make_human(layer, citation, missing, ScreeningActions.ScreenOut)
    else:
        make_ai(layer, citation, missing, ScreeningActions.ScreenOut)
    assert get_status(layer, citation) == CitationStatus.Out


def test_invalid_latest_human_does_not_revive_older_answer(layer):
    # An invalid latest choice must leave ambiguity when no valid AI can fill
    # the gap.
    citation = CitationFactory()
    question = layer.question_factory(review=citation.dataset.review)
    with freeze_time("2026-01-01"):
        make_human(layer, citation, question, ScreeningActions.ScreenOut)
    with freeze_time("2026-01-02"):
        latest = make_human(layer, citation, question)
    latest.selected_option.soft_delete()
    assert get_status(layer, citation) == CitationStatus.Ambiguous


def test_stage_filter_uses_combined_confirmed_inclusions(layer):
    # Stage eligibility must fill human gaps with confirmed AI and reject
    # ambiguity.
    included = CitationFactory()
    ambiguous = CitationFactory(dataset=included.dataset)
    first = layer.question_factory(review=included.dataset.review)
    second = layer.question_factory(review=included.dataset.review)
    for citation in [included, ambiguous]:
        make_human(layer, citation, first)
    make_ai(layer, included, second)
    make_ai(layer, ambiguous, second, with_critical=False)
    stage = ReviewStage.L2_SCREENING
    if layer.stage == "l2":
        stage = ReviewStage.PARAMETER_EXTRACTION
    assert list(
        get_citations_for_stage(included.dataset.review_id, stage)
    ) == [included]


@pytest.mark.parametrize("source", ["human", "ai"])
def test_inactive_and_other_review_questions_are_ignored(layer, source):
    # Ignored answers must neither exclude citations nor count as active
    # answers.
    citation = CitationFactory()
    active = layer.question_factory(review=citation.dataset.review)
    ignored = [
        layer.question_factory(review=citation.dataset.review),
        layer.question_factory(
            review=citation.dataset.review, disable_screening=True
        ),
        layer.question_factory(),
    ]
    ignored[0].soft_delete()
    for question in ignored:
        if source == "human":
            make_human(layer, citation, question, ScreeningActions.ScreenOut)
        else:
            make_ai(layer, citation, question, ScreeningActions.ScreenOut)
    assert get_status(layer, citation) == CitationStatus.Unanswered
    make_human(layer, citation, active)
    assert get_status(layer, citation) == CitationStatus.In
    active.soft_delete()
    assert get_status(layer, citation) == CitationStatus.Unanswered


@pytest.mark.parametrize("source", ["human", "ai"])
def test_other_citation_answers_are_ignored(layer, source):
    # Shared questions must not allow answers to leak between citations.
    citation = CitationFactory()
    other = CitationFactory(dataset=citation.dataset)
    question = layer.question_factory(review=citation.dataset.review)
    if source == "human":
        make_human(layer, other, question, ScreeningActions.ScreenOut)
    else:
        make_ai(layer, other, question, ScreeningActions.ScreenOut)
    assert get_status(layer, citation) == CitationStatus.Unanswered


def test_disjoint_sources_cannot_be_combined_from_aggregate_statuses(layer):
    # This test proves you can't derive overall status from human and AI status aggregates
    covered = CitationFactory()
    incomplete = CitationFactory(dataset=covered.dataset)
    first = layer.question_factory(review=covered.dataset.review)
    second = layer.question_factory(review=covered.dataset.review)
    make_human(layer, covered, first)
    make_ai(layer, covered, second)
    make_human(layer, incomplete, first)
    make_ai(layer, incomplete, first)
    queryset = getattr(Citation.objects, f"add_{layer.stage}_overall_status")()
    queryset = getattr(queryset, f"add_{layer.stage}_ai_status")()
    queryset = getattr(queryset, f"add_{layer.stage}_human_status")()
    for citation in queryset.filter(pk__in=[covered.pk, incomplete.pk]):
        assert (
            getattr(citation, f"{layer.stage}_ai_status")
            == CitationAIStatus.NotScreenedYet
        )
        assert (
            getattr(citation, f"{layer.stage}_human_status")
            == CitationHumanStatus.Unanswered
        )
    assert get_status(layer, covered) == CitationStatus.In
    assert get_status(layer, incomplete) == CitationStatus.Ambiguous


def test_partial_human_override_cannot_be_inferred_from_aggregate_statuses(
    layer,
):
    # Matching source summaries hide whether humans override the AI exclusion
    # or another question.
    overridden = CitationFactory()
    excluded = CitationFactory(dataset=overridden.dataset)
    first = layer.question_factory(review=overridden.dataset.review)
    second = layer.question_factory(review=overridden.dataset.review)
    for citation in [overridden, excluded]:
        make_ai(layer, citation, first, ScreeningActions.ScreenOut)
        make_ai(layer, citation, second)
    make_human(layer, overridden, first)
    make_human(layer, excluded, second)
    queryset = getattr(Citation.objects, f"add_{layer.stage}_overall_status")()
    queryset = getattr(queryset, f"add_{layer.stage}_ai_status")()
    queryset = getattr(queryset, f"add_{layer.stage}_human_status")()
    for citation in queryset.filter(pk__in=[overridden.pk, excluded.pk]):
        assert (
            getattr(citation, f"{layer.stage}_ai_status")
            == CitationAIStatus.AutoExcluded
        )
        assert (
            getattr(citation, f"{layer.stage}_human_status")
            == CitationHumanStatus.Unanswered
        )
    assert get_status(layer, overridden) == CitationStatus.In
    assert get_status(layer, excluded) == CitationStatus.Out


@pytest.mark.parametrize("citation_count", [1, 10])
def test_annotation_is_optional_chainable_and_uses_one_query(
    layer, citation_count, django_assert_num_queries
):
    # Both stage annotations must stay optional and fetch decisions without N+1
    # queries.
    first = CitationFactory()
    citations = [first] + CitationFactory.create_batch(
        citation_count - 1, dataset=first.dataset
    )
    question = layer.question_factory(review=first.dataset.review)
    for citation in citations:
        make_human(layer, citation, question)
    assert not hasattr(Citation.objects.get(pk=first.pk), layer.field)
    other_stage = "l2"
    if layer.stage == "l2":
        other_stage = "l1"
    with django_assert_num_queries(1):
        queryset = (
            Citation.objects.filter(dataset=first.dataset)
            .add_l1_overall_status()
            .add_l2_overall_status()
        )
        queryset = queryset.filter(**{layer.field: CitationStatus.In})
        rows = list(queryset)
        assert len(rows) == citation_count
        assert all(
            getattr(row, layer.field) == CitationStatus.In for row in rows
        )
        assert all(
            getattr(row, f"{other_stage}_overall_status")
            == CitationStatus.Unanswered
            for row in rows
        )

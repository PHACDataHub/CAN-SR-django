from datetime import timedelta
from unittest.mock import patch

from django.core.management.base import CommandError
from django.utils import timezone

import pytest
from dateutil.relativedelta import relativedelta
from freezegun import freeze_time

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    ParameterFactory,
    ReviewFactory,
    UserFactory,
)
from my_app.models import (
    Citation,
    CitationAIStatus,
    CitationStatus,
    L1CriticalScreeningResult,
    L1HumanAnswer,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    L1ScreeningResult,
    L2CriticalScreeningResult,
    L2HumanAnswer,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    L2ScreeningResult,
    Parameter,
    ParameterExtractionResult,
    ParameterHumanAnswer,
    ParameterOption,
    Review,
    ScreeningActions,
    ScreeningResultStatus,
)
from my_app.scripts.gen_fake_data_for_review import (
    FakeL1Data,
    FakeL2Data,
    FakeParameterData,
    human_answer_count,
    run,
)

SCRIPT = "my_app.scripts.gen_fake_data_for_review"


@pytest.mark.parametrize("action", ScreeningActions.values)
@pytest.mark.parametrize(
    "roll,agrees", [(0, True), (0.989, True), (0.99, False), (0.999, False)]
)
def test_mirrored_l2_answer_matches_exact_l1_option(action, roll, agrees):
    question = L1ScreeningQuestionFactory()
    options = [
        L1ScreeningQuestionOptionFactory(
            question=question, screening_action=value
        )
        for value in [
            ScreeningActions.ScreenIn,
            ScreeningActions.ScreenIn,
            ScreeningActions.ScreenOut,
        ]
    ]
    l2_question = question.sync_to_l2()
    l2_options = [option.sync_to_l2() for option in options]
    selected_option = next(
        option for option in options if option.screening_action == action
    )
    citation = CitationFactory(dataset__review=question.review)
    L1ScreeningResult.objects.create(
        citation=citation,
        question=question,
        selected_option=selected_option,
        status=ScreeningResultStatus.COMPLETED,
    )
    generator = FakeL2Data(question.review)
    with freeze_time("2026-09-09") as clock:
        generator.clock = clock
        with patch(f"{SCRIPT}.random.random", side_effect=[roll, 0.0, 0.99]):
            generator.generate_answers(citation, l2_question, l2_options)
    result = L2ScreeningResult.objects.get()
    assert result.status == ScreeningResultStatus.COMPLETED
    assert (
        result.selected_option.l1_option_id == selected_option.pk
    ) == agrees
    assert result.critical_result.selected_option is None


@pytest.mark.parametrize("status", [None, ScreeningResultStatus.ABANDONED])
def test_mirrored_l2_without_valid_l1_answer_uses_random_logic(status):
    question = L1ScreeningQuestionFactory()
    options = [
        L1ScreeningQuestionOptionFactory(
            question=question, screening_action=action
        )
        for action in ScreeningActions.values
    ]
    l2_question = question.sync_to_l2()
    l2_options = [option.sync_to_l2() for option in options]
    citation = CitationFactory(dataset__review=question.review)
    if status is not None:
        L1ScreeningResult.objects.create(
            citation=citation, question=question, status=status
        )
    with patch(f"{SCRIPT}.random.random", return_value=0.96):
        option, erroneous = FakeL2Data(question.review).base_answer(
            citation, l2_question, l2_options
        )
    assert option.screening_action == ScreeningActions.ScreenOut
    assert not erroneous


def test_included_l2_citation_reuses_exact_l1_screen_in_option():
    question = L1ScreeningQuestionFactory()
    options = [
        L1ScreeningQuestionOptionFactory(question=question) for _ in range(2)
    ]
    l2_question = question.sync_to_l2()
    l2_options = [option.sync_to_l2() for option in options]
    citation = CitationFactory(dataset__review=question.review)
    L1ScreeningResult.objects.create(
        citation=citation,
        question=question,
        selected_option=options[1],
        status=ScreeningResultStatus.COMPLETED,
    )
    generator = FakeL2Data(question.review)
    assert (
        generator.included_option(
            citation, l2_question, l2_options
        ).l1_option_id
        == options[1].pk
    )


def test_run_generates_l1_and_l2_data_for_all_review_citations():
    review = ReviewFactory()
    citations = CitationFactory.create_batch(
        2, dataset=CitationDatasetFactory(review=review)
    )
    other_citation = CitationFactory()
    with freeze_time("2026-10-09 12:00:00"):
        start = timezone.now() - relativedelta(months=1)
        run(str(review.pk), "l1")
        questions = list(review.l1_screening_questions.all())
        assert 4 <= len(questions) <= 6
        assert L1ScreeningResult.objects.count() == len(citations) * len(
            questions
        )
        for question in questions:
            options = list(question.options.all())
            assert 2 <= len(options) <= 5
            assert {option.screening_action for option in options} == set(
                ScreeningActions.values
            )
            mirror = question.l2_copies.get()
            assert mirror.question_text == question.question_text
            assert mirror.options.count() == len(options)
            for option in options:
                assert (
                    option.l2_copies.get().screening_action
                    == option.screening_action
                )
        results = list(L1ScreeningResult.objects.order_by("pk"))
        assert all(result.created_at >= start for result in results)
        for previous, following in zip(results, results[1:]):
            assert (
                timedelta(seconds=60)
                <= following.created_at - previous.created_at
                <= timedelta(seconds=1200)
            )
        assert all(
            result.critical_result.created_at > result.created_at
            for result in results
        )
        assert all(
            answer.created_at
            > answer.citation.l1screeningresult_set.get(
                question=answer.question
            ).created_at
            for answer in L1HumanAnswer.objects.all()
        )
        run(str(review.pk), "L2")
        assert (
            len(questions) + 2
            <= review.l2_screening_questions.count()
            <= len(questions) + 5
        )
        assert (
            L2ScreeningResult.objects.count()
            == len(citations) * review.l2_screening_questions.count()
        )
        assert not L2ScreeningResult.objects.filter(
            citation=other_citation
        ).exists()
        assert L2ScreeningResult.objects.filter(
            question__l1_question__isnull=False
        ).count() == len(citations) * len(questions)
        run(str(review.pk), "l1")
        assert (
            L1ScreeningResult.objects.count()
            == len(citations) * review.l1_screening_questions.count()
        )


@pytest.mark.parametrize(
    "base_roll,critical_roll,expected_action,base_status,critical_status,disagrees",
    [
        (
            0.0,
            0.0,
            ScreeningActions.ScreenIn,
            ScreeningResultStatus.COMPLETED,
            ScreeningResultStatus.COMPLETED,
            False,
        ),
        (
            0.949,
            0.949,
            ScreeningActions.ScreenIn,
            ScreeningResultStatus.COMPLETED,
            ScreeningResultStatus.COMPLETED,
            False,
        ),
        (
            0.95,
            0.95,
            ScreeningActions.ScreenOut,
            ScreeningResultStatus.COMPLETED,
            ScreeningResultStatus.COMPLETED,
            True,
        ),
        (
            0.979,
            0.979,
            ScreeningActions.ScreenOut,
            ScreeningResultStatus.COMPLETED,
            ScreeningResultStatus.COMPLETED,
            True,
        ),
        (
            0.98,
            0.98,
            None,
            ScreeningResultStatus.ABANDONED,
            ScreeningResultStatus.ABANDONED,
            False,
        ),
    ],
)
def test_screening_answer_outcomes(
    base_roll,
    critical_roll,
    expected_action,
    base_status,
    critical_status,
    disagrees,
):
    question = L1ScreeningQuestionFactory()
    options = [
        L1ScreeningQuestionOptionFactory(
            question=question, screening_action=action
        )
        for action in ScreeningActions.values
    ]
    citation = CitationFactory(dataset__review=question.review)
    generator = FakeL1Data(question.review)
    with freeze_time("2026-09-09") as clock:
        generator.clock = clock
        with patch(
            f"{SCRIPT}.random.random",
            side_effect=[base_roll, critical_roll, 0.99],
        ):
            generator.generate_answers(citation, question, options)
    result = L1ScreeningResult.objects.get()
    assert result.status == base_status
    if expected_action is None:
        assert result.selected_option is None
        assert result.abandoned_at == result.created_at
        assert result.confidence is None
    else:
        assert result.selected_option.screening_action == expected_action
    critical = result.critical_result
    assert critical.status == critical_status
    if disagrees:
        assert critical.selected_option.screening_action != expected_action
    else:
        assert critical.selected_option is None
    if critical_status == ScreeningResultStatus.ABANDONED:
        assert critical.error
        assert critical.abandoned_at == critical.created_at


def test_two_human_answers_include_agreement_and_disagreement():
    question = L1ScreeningQuestionFactory()
    users = UserFactory.create_batch(2)
    question.review.users.add(*users)
    options = [
        L1ScreeningQuestionOptionFactory(
            question=question, screening_action=action
        )
        for action in ScreeningActions.values
    ]
    generator = FakeL1Data(question.review)
    with freeze_time("2026-09-09") as clock:
        generator.clock = clock
        with patch(
            f"{SCRIPT}.random.random",
            side_effect=[0.0, 0.0, 0.55, 0.799, 0.80],
        ):
            generator.generate_answers(
                CitationFactory(dataset__review=question.review),
                question,
                options,
            )
    first, second = L1HumanAnswer.objects.order_by("pk")
    assert first.selected_option.screening_action == ScreeningActions.ScreenIn
    assert (
        second.selected_option.screening_action == ScreeningActions.ScreenOut
    )
    assert first.user == users[0]
    assert second.user == users[1]
    assert (
        timedelta(seconds=30)
        <= second.created_at - first.created_at
        <= timedelta(seconds=300)
    )


@pytest.mark.parametrize(
    "roll,count",
    [(0, 1), (0.549, 1), (0.55, 2), (0.599, 2), (0.60, 0), (0.999, 0)],
)
def test_human_answer_count(roll, count):
    with patch(f"{SCRIPT}.random.random", return_value=roll):
        assert human_answer_count() == count


def test_parameter_run_includes_existing_free_text_parameter():
    review = ReviewFactory()
    existing = ParameterFactory(review=review)
    citations = CitationFactory.create_batch(
        2, dataset=CitationDatasetFactory(review=review)
    )
    with freeze_time("2026-10-09"):
        run(str(review.pk), "parameter")
    generated = review.parameters.exclude(pk=existing.pk)
    assert 4 <= generated.count() <= 8
    for parameter in generated:
        assert parameter.option_type == Parameter.OptionType.SELECT
        assert 2 <= parameter.options.count() <= 5
    assert (
        ParameterExtractionResult.objects.count()
        == len(citations) * review.parameters.count()
    )
    assert ParameterExtractionResult.objects.filter(
        question=existing
    ).count() == len(citations)


@pytest.mark.parametrize(
    "roll,status,found",
    [
        (0, ScreeningResultStatus.COMPLETED, True),
        (0.90, ScreeningResultStatus.COMPLETED, False),
        (0.98, ScreeningResultStatus.ABANDONED, False),
    ],
)
def test_parameter_outcomes_and_human_disagreement(roll, status, found):
    question = ParameterFactory()
    generator = FakeParameterData(question.review)
    with freeze_time("2026-09-09") as clock:
        generator.clock = clock
        with patch(
            f"{SCRIPT}.random.random", side_effect=[roll, 0.55, 0.799, 0.80]
        ):
            generator.generate_answers(
                CitationFactory(dataset__review=question.review), question, []
            )
    result = ParameterExtractionResult.objects.get()
    assert result.status == status
    assert result.found == found
    first, second = ParameterHumanAnswer.objects.order_by("pk")
    assert first.found == found
    assert second.found != found


@pytest.mark.parametrize(
    "args", [(), ("1",), ("1", "invalid"), ("invalid", "l1"), ("-1", "l1")]
)
def test_invalid_arguments(args):
    with pytest.raises(CommandError):
        run(*args)


def test_invalid_existing_question_rolls_back_generated_questions():
    question = L1ScreeningQuestionFactory()
    with pytest.raises(
        CommandError, match="needs active screen-in and screen-out"
    ):
        run(str(question.review_id), "l1")
    assert L1ScreeningQuestion.objects.count() == 1
    assert question.review.l2_screening_questions.count() == 0


@pytest.mark.parametrize(
    "stage,result_model,human_model,ai_annotation,overall_annotation",
    [
        (
            "L1",
            L1ScreeningResult,
            L1HumanAnswer,
            "l1_ai_status",
            "l1_overall_status",
        ),
        (
            "L2",
            L2ScreeningResult,
            L2HumanAnswer,
            "l2_ai_status",
            "l2_overall_status",
        ),
    ],
)
def test_first_thirty_percent_are_confidently_included(
    stage, result_model, human_model, ai_annotation, overall_annotation
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    for order in reversed(range(10)):
        CitationFactory(dataset=dataset, order=order)
    with (
        patch(f"{SCRIPT}.random.random", return_value=0.96),
        patch(f"{SCRIPT}.human_answer_count", return_value=1),
    ):
        run(str(review.pk), stage)

    citations = list(Citation.objects.filter(dataset=dataset))
    included = citations[:3]
    random_citations = citations[3:]
    assert included[0].order == 0
    for result in result_model.objects.filter(citation__in=included):
        assert result.status == ScreeningResultStatus.COMPLETED
        assert (
            result.selected_option.screening_action
            == ScreeningActions.ScreenIn
        )
        assert 0.9 <= result.confidence <= 0.99
        critical = result.critical_result
        assert critical.status == ScreeningResultStatus.COMPLETED
        assert critical.selected_option is None
        assert 0.9 <= critical.confidence <= 0.99
        assert critical.created_at > result.created_at
    assert not human_model.objects.filter(citation__in=included).exists()
    for result in result_model.objects.filter(citation__in=random_citations):
        assert (
            result.selected_option.screening_action
            == ScreeningActions.ScreenOut
        )
        assert (
            result.critical_result.selected_option.screening_action
            == ScreeningActions.ScreenIn
        )
    assert (
        human_model.objects.count()
        == result_model.objects.filter(citation__in=random_citations).count()
    )
    queryset = getattr(Citation.objects, f"add_{ai_annotation}")()
    queryset = getattr(queryset, f"add_{overall_annotation}")()
    for citation in queryset.filter(
        pk__in=[citation.pk for citation in included]
    ):
        assert (
            getattr(citation, ai_annotation)
            == CitationAIStatus.ConfidentlyIncluded
        )
        assert getattr(citation, overall_annotation) == CitationStatus.In


def test_reset_hard_deletes_all_stages_and_preserves_other_reviews():
    review = ReviewFactory()
    other_review = ReviewFactory()
    citations = [
        CitationFactory(dataset__review=current_review)
        for current_review in (review, other_review)
    ]
    with patch(f"{SCRIPT}.random.random", return_value=0):
        for current_review in (review, other_review):
            for stage in ("L1", "L2", "PARAM"):
                run(str(current_review.pk), stage)

    review.l1_screening_questions.first().soft_delete()
    review.l2_screening_questions.filter(
        l1_question__isnull=True
    ).first().soft_delete()
    review.parameters.first().soft_delete()
    criteria_models = (
        L1ScreeningQuestion,
        L2ScreeningQuestion,
        Parameter,
    )
    related_models = (
        L1ScreeningQuestionOption,
        L2ScreeningQuestionOption,
        ParameterOption,
        L1ScreeningResult,
        L2ScreeningResult,
        ParameterExtractionResult,
        L1CriticalScreeningResult,
        L2CriticalScreeningResult,
        L1HumanAnswer,
        L2HumanAnswer,
        ParameterHumanAnswer,
    )
    models = criteria_models + related_models
    # All related records belong to one of the two seeded reviews.
    other_records = {
        model: set(model.objects.values_list("pk", flat=True))
        for model in models
    }
    for model in models:
        if model in criteria_models:
            own_records = model.objects.filter(review=review)
        elif model in (L1CriticalScreeningResult, L2CriticalScreeningResult):
            own_records = model.objects.filter(
                initial_result__question__review=review
            )
        elif model == ParameterOption:
            own_records = model.objects.filter(parameter__review=review)
        else:
            own_records = model.objects.filter(question__review=review)
        own_ids = set(own_records.values_list("pk", flat=True))
        assert own_ids
        other_records[model] -= own_ids
        assert other_records[model]

    run(str(review.pk), "RESET")

    for model in models:
        assert (
            set(model.objects.values_list("pk", flat=True))
            == other_records[model]
        )
    assert Review.objects.filter(pk=review.pk).exists()
    assert set(Citation.objects.values_list("pk", flat=True)) == {
        citation.pk for citation in citations
    }
    run(str(review.pk), "reset")
    for model in models:
        assert (
            set(model.objects.values_list("pk", flat=True))
            == other_records[model]
        )

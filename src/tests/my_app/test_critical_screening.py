"""Examples of the critical prompt contract, plus task lifecycle checks."""

from unittest.mock import patch

from django.test import override_settings

import pydantic
import pytest

from proj.llm_client import ClientFailureError, UnexpectedLLMOutputError

from my_app.model_factories import (
    CitationFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
)
from my_app.models import (
    DocumentTable,
    L1CriticalScreeningResult,
    L1ScreeningResult,
    L2CriticalScreeningResult,
    L2ScreeningResult,
    LanguageModel,
    ScreeningResultStatus,
)
from my_app.prompts.l1_screening_prompt import (
    L1ScreeningPromptBuilder,
    build_l1_response_schema,
    build_raw_l1_result_model,
)
from my_app.prompts.l2_screening_prompt import (
    L2ScreeningPromptBuilder,
    build_l2_response_schema,
    build_raw_l2_result_model,
)
from my_app.services.critical_screening import (
    ProcessL1CriticalScreeningService,
    ProcessL2CriticalScreeningService,
)
from my_app.services.l1_screening import ProcessL1ScreeningService
from my_app.services.l2_screening import ProcessL2ScreeningService
from tests.my_app.test_l2_screening import _build_l2_screening_context

pytestmark = pytest.mark.backend


def l1_initial_result():
    citation = CitationFactory()
    question = L1ScreeningQuestionFactory(review=citation.dataset.review)
    include = L1ScreeningQuestionOptionFactory(
        question=question, option_text="Include"
    )
    L1ScreeningQuestionOptionFactory(question=question, option_text="Exclude")
    return L1ScreeningResult.objects.create(
        citation=citation,
        question=question,
        selected_option=include,
        status=ScreeningResultStatus.COMPLETED,
        language_model=LanguageModel.get_default_model(),
    )


def l2_initial_result():
    _, _, citation, _, question = _build_l2_screening_context()
    return L2ScreeningResult.objects.create(
        citation=citation,
        question=question,
        selected_option=question.options.get(option_text="Include"),
        status=ScreeningResultStatus.COMPLETED,
        language_model=LanguageModel.get_default_model(),
    )


def test_example_l1_critical_prompt_removes_original_option_and_explanation():
    """The original answer appears as context, never as an available option."""
    initial = l1_initial_result()
    options = list(initial.question.options.all())
    prompt = L1ScreeningPromptBuilder(
        initial.question, options, initial.citation, initial.selected_option
    ).build_str()
    assert (
        'The first model answered: "Include", You are NOT allowed to choose the original answer.'
        in prompt
    )
    assert 'Choose "None of the above" if you agree' in prompt
    assert (
        "The available options (exact text) are:\n'Exclude'\n'None of the above'"
        in prompt
    )
    assert '"explanation"' not in prompt
    schema = build_l1_response_schema(options, initial.selected_option).schema
    assert set(schema["properties"]) == {"selected", "confidence"}
    assert schema["properties"]["selected"]["enum"] == [
        "Exclude",
        "None of the above",
    ]


def test_example_l2_critical_prompt_keeps_source_material_but_requests_no_evidence():
    """Source text and tables remain input; evidence lists are omitted from output."""
    initial = l2_initial_result()
    table = DocumentTable.objects.create(
        document=initial.citation.document,
        index=1,
        table_markdown="Sample size: 42",
    )
    builder = L2ScreeningPromptBuilder(
        initial.question,
        list(initial.question.options.all()),
        initial.citation,
        initial.citation.document.text_extraction_result,
        [table],
        [],
        initial.selected_option,
    )
    prompt = builder.build_str(builder.get_screening_prompt_args())
    assert (
        'The first model answered: "Include", You are NOT allowed to choose the original answer.'
        in prompt
    )
    assert 'Choose "None of the above" if you agree' in prompt
    assert "'Exclude'\n'None of the above'" in prompt
    assert "First sentence." in prompt
    assert "Sample size: 42" in prompt
    assert '"explanation"' not in prompt
    assert '"evidence_' not in prompt
    schema = build_l2_response_schema(
        list(initial.question.options.all()),
        True,
        True,
        initial.selected_option,
    ).schema
    assert set(schema["properties"]) == {"selected", "confidence"}
    assert set(schema["required"]) == {"selected", "confidence"}


@override_settings(HAS_LLM=True)
def test_example_l1_agreement_json_is_saved_as_completed_with_null_option():
    initial = l1_initial_result()
    critical = L1CriticalScreeningResult.objects.create(
        initial_result=initial, language_model=initial.language_model
    )
    # "None of the above" is a prompt-only option representing agreement.
    response = '{"selected": "None of the above", "confidence": 0.93}'
    with patch("my_app.prompts.l1_screening_prompt.get_client") as client:
        client.return_value.complete_prompt.return_value = response
        ProcessL1CriticalScreeningService(critical.pk).perform()
        assert (
            client.return_value.complete_prompt.call_args.args[1]
            == initial.language_model
        )
    critical.refresh_from_db()
    assert critical.status == ScreeningResultStatus.COMPLETED
    assert critical.selected_option is None
    assert critical.confidence == 0.93
    initial.refresh_from_db()
    assert initial.selected_option.option_text == "Include"


@override_settings(HAS_LLM=True)
def test_example_l2_disagreement_json_is_saved_as_an_alternative_option():
    initial = l2_initial_result()
    critical = L2CriticalScreeningResult.objects.create(
        initial_result=initial, language_model=initial.language_model
    )
    # A dissenting answer points to a real option; no evidence or explanation is sent.
    response = '{"selected": "Exclude", "confidence": 0.81}'
    with patch("my_app.prompts.l2_screening_prompt.get_client") as client:
        client.return_value.complete_prompt.return_value = response
        ProcessL2CriticalScreeningService(critical.pk).perform()
        assert (
            client.return_value.complete_prompt.call_args.args[1]
            == initial.language_model
        )
    critical.refresh_from_db()
    assert critical.status == ScreeningResultStatus.COMPLETED
    assert critical.selected_option == initial.question.options.get(
        option_text="Exclude"
    )
    assert critical.confidence == 0.81


@pytest.mark.parametrize("level", [1, 2])
@override_settings(HAS_LLM=False)
def test_initial_success_enqueues_critical_only_after_commit_and_rescreens_replace_it(
    level, django_capture_on_commit_callbacks
):
    initial = {1: l1_initial_result, 2: l2_initial_result}[level]()
    service = {1: ProcessL1ScreeningService, 2: ProcessL2ScreeningService}[
        level
    ](initial.pk)
    model = {1: L1CriticalScreeningResult, 2: L2CriticalScreeningResult}[level]
    with patch(
        f"my_app.tasks.l{level}_screening.process_l{level}_critical_screening_task"
    ) as task:
        with django_capture_on_commit_callbacks(execute=True):
            service.perform()
            task.enqueue.assert_not_called()
            initial.refresh_from_db()
            assert initial.status == ScreeningResultStatus.COMPLETED
        critical = model.objects.get(initial_result=initial)
        task.enqueue.assert_called_once_with(result_id=critical.pk)
        assert critical.language_model == initial.language_model
        old_pk = critical.pk
        with django_capture_on_commit_callbacks(execute=True):
            service.perform()
        assert not model.objects.filter(pk=old_pk).exists()
        assert model.objects.filter(initial_result=initial).count() == 1
        assert task.enqueue.call_count == 2
    # A stale queued task is a harmless no-op.
    {
        1: ProcessL1CriticalScreeningService,
        2: ProcessL2CriticalScreeningService,
    }[level](old_pk).perform()


@pytest.mark.parametrize("level", [1, 2])
def test_failed_initial_screening_does_not_enqueue_critical_review(
    level, django_capture_on_commit_callbacks
):
    initial = {1: l1_initial_result, 2: l2_initial_result}[level]()
    model = {1: L1CriticalScreeningResult, 2: L2CriticalScreeningResult}[level]
    model.objects.create(initial_result=initial)
    with patch(
        f"my_app.services.l{level}_screening.get_l{level}_screening_results",
        side_effect=UnexpectedLLMOutputError,
    ):
        with patch(
            f"my_app.tasks.l{level}_screening.process_l{level}_critical_screening_task"
        ) as task:
            with django_capture_on_commit_callbacks(execute=True):
                {1: ProcessL1ScreeningService, 2: ProcessL2ScreeningService}[
                    level
                ](initial.pk).perform()
            task.enqueue.assert_not_called()
    initial.refresh_from_db()
    assert initial.status == ScreeningResultStatus.ABANDONED
    assert not model.objects.filter(initial_result=initial).exists()


@pytest.mark.parametrize("level", [1, 2])
@override_settings(HAS_LLM=True)
def test_critical_rejects_original_answer_and_retries_before_agreement(level):
    initial = {1: l1_initial_result, 2: l2_initial_result}[level]()
    model = {1: L1CriticalScreeningResult, 2: L2CriticalScreeningResult}[level]
    critical = model.objects.create(
        initial_result=initial, language_model=initial.language_model
    )
    with patch(
        f"my_app.prompts.l{level}_screening_prompt.get_client"
    ) as client:
        client.return_value.complete_prompt.side_effect = [
            '{"selected": "Include", "confidence": 0.9}',
            '{"selected": "None of the above", "confidence": 0.8}',
        ]
        {
            1: ProcessL1CriticalScreeningService,
            2: ProcessL2CriticalScreeningService,
        }[level](critical.pk).perform()
        assert client.return_value.complete_prompt.call_count == 2
    critical.refresh_from_db()
    assert critical.status == ScreeningResultStatus.COMPLETED
    assert critical.selected_option is None


def test_critical_schema_rejects_unrequested_fields_and_out_of_range_confidence():
    for model in (
        build_raw_l1_result_model(True),
        build_raw_l2_result_model(True, True, True),
    ):
        with pytest.raises(pydantic.ValidationError):
            model(
                selected="None of the above",
                confidence=0.7,
                explanation="Not requested",
            )
        with pytest.raises(pydantic.ValidationError):
            model(selected="None of the above", confidence=1.1)
    with pytest.raises(pydantic.ValidationError):
        build_raw_l2_result_model(True, True, True)(
            selected="Exclude", confidence=0.7, evidence_sentences=[]
        )


def test_critical_invalid_output_is_abandoned_without_changing_initial_result():
    initial = l1_initial_result()
    critical = L1CriticalScreeningResult.objects.create(initial_result=initial)
    with patch(
        "my_app.services.critical_screening.get_l1_screening_results",
        side_effect=UnexpectedLLMOutputError,
    ) as prompt:
        ProcessL1CriticalScreeningService(critical.pk).perform()
        assert prompt.call_count == 4
    critical.refresh_from_db()
    assert critical.status == ScreeningResultStatus.ABANDONED
    assert critical.abandoned_at is not None
    initial.refresh_from_db()
    assert initial.status == ScreeningResultStatus.COMPLETED


def test_critical_client_failure_propagates_for_task_retry():
    initial = l1_initial_result()
    critical = L1CriticalScreeningResult.objects.create(initial_result=initial)
    with patch(
        "my_app.services.critical_screening.get_l1_screening_results",
        side_effect=ClientFailureError,
    ):
        with pytest.raises(ClientFailureError):
            ProcessL1CriticalScreeningService(critical.pk).perform()
    critical.refresh_from_db()
    assert critical.status == ScreeningResultStatus.PENDING


@pytest.mark.parametrize("level", [1, 2])
@override_settings(
    HAS_LLM=True,
    TASKS={
        "default": {
            "BACKEND": "django_tasks_db.DatabaseBackend",
            "QUEUES": ["default"],
        }
    },
)
def test_database_worker_runs_initial_then_critical_prompt(
    level, run_database_tasks, django_capture_on_commit_callbacks
):
    from django_tasks_db.models import DBTaskResult

    from my_app.tasks.l1_screening import process_l1_screening_task
    from my_app.tasks.l2_screening import process_l2_screening_task

    initial = {1: l1_initial_result, 2: l2_initial_result}[level]()
    initial.status = ScreeningResultStatus.PENDING
    initial.selected_option = None
    initial.save()
    initial_response = (
        '{"selected": "Include", "confidence": 0.8, "explanation": "Eligible"}'
    )
    if level == 2:
        initial_response = '{"selected": "Include", "confidence": 0.8, "explanation": "Eligible", "evidence_sentences": [0]}'
    with patch(
        f"my_app.prompts.l{level}_screening_prompt.get_client"
    ) as client:
        client.return_value.complete_prompt.side_effect = [
            initial_response,
            '{"selected": "None of the above", "confidence": 0.9}',
        ]
        {1: process_l1_screening_task, 2: process_l2_screening_task}[
            level
        ].enqueue(result_id=initial.pk)
        with django_capture_on_commit_callbacks(execute=True):
            run_database_tasks()
        initial.refresh_from_db()
        assert initial.status == ScreeningResultStatus.COMPLETED
        assert initial.critical_result.status == ScreeningResultStatus.PENDING
        run_database_tasks()
        critical = initial.critical_result
        critical.refresh_from_db()
        assert critical.status == ScreeningResultStatus.COMPLETED
        assert critical.selected_option is None
        assert client.return_value.complete_prompt.call_count == 2
        assert DBTaskResult.objects.count() == 2


def test_critical_schema_allows_agreement_when_original_was_the_only_option():
    initial = l1_initial_result()
    schema = build_l1_response_schema(
        [initial.selected_option], initial.selected_option
    ).schema
    assert schema["properties"]["selected"]["enum"] == ["None of the above"]


def test_l2_normal_schema_removes_only_evidence_for_missing_sources():
    """The maximal model is preserved; each contextual schema removes fields."""
    full = build_raw_l2_result_model(True, True)
    assert set(full.model_fields) == {
        "selected",
        "confidence",
        "explanation",
        "evidence_sentences",
        "evidence_tables",
        "evidence_figures",
    }
    assert set(build_raw_l2_result_model(False, True).model_fields) == set(
        full.model_fields
    ) - {"evidence_tables"}
    assert set(build_raw_l2_result_model(True, False).model_fields) == set(
        full.model_fields
    ) - {"evidence_figures"}
    assert set(build_raw_l2_result_model(False, False).model_fields) == set(
        full.model_fields
    ) - {"evidence_tables", "evidence_figures"}


def test_inflight_critical_result_does_not_reappear_after_rescreen_deletes_it():
    from types import SimpleNamespace

    initial = l1_initial_result()
    critical = L1CriticalScreeningResult.objects.create(initial_result=initial)
    critical_id = critical.pk

    def answer_after_rescreen(*args, **kwargs):
        critical.delete()
        return SimpleNamespace(selected=None, confidence=0.9)

    with patch(
        "my_app.services.critical_screening.get_l1_screening_results",
        side_effect=answer_after_rescreen,
    ):
        ProcessL1CriticalScreeningService(critical_id).perform()
    assert not L1CriticalScreeningResult.objects.filter(
        initial_result=initial
    ).exists()


@override_settings(HAS_LLM=False)
def test_l1_critical_mock_helper_owns_its_answer_choices():
    from my_app.prompts.l1_screening_prompt import (
        get_l1_screening_results,
        get_mock_l1_screening_results,
    )

    initial = l1_initial_result()
    options = list(initial.question.options.all())
    with patch(
        "my_app.prompts.l1_screening_prompt.random.choice", return_value=None
    ) as choose:
        result = get_mock_l1_screening_results(
            initial.question,
            options,
            initial.citation,
            answer_to_critique=initial.selected_option,
        )
        assert result.selected is None
        assert [
            option.option_text if option else None
            for option in choose.call_args.args[0]
        ] == ["Exclude", None]
        public_result = get_l1_screening_results(
            initial.question,
            options,
            initial.citation,
            initial.language_model,
            answer_to_critique=initial.selected_option,
        )
        assert public_result.selected is None
        assert choose.call_count == 2


@override_settings(HAS_LLM=False)
def test_l2_critical_mock_helper_owns_its_answer_choices_and_skips_evidence():
    from my_app.prompts.l2_screening_prompt import (
        get_l2_screening_results,
        get_mock_l2_screening_results,
    )

    initial = l2_initial_result()
    options = list(initial.question.options.all())
    text = initial.citation.document.text_extraction_result
    with patch(
        "my_app.prompts.l2_screening_prompt.random.choice", return_value=None
    ) as choose:
        result = get_mock_l2_screening_results(
            initial.question,
            options,
            initial.citation,
            text,
            answer_to_critique=initial.selected_option,
        )
        assert result.selected is None
        assert result.evidence_sentences == []
        assert [
            option.option_text if option else None
            for option in choose.call_args.args[0]
        ] == ["Exclude", None]
        public_result = get_l2_screening_results(
            initial.question,
            options,
            initial.citation,
            text,
            [],
            [],
            initial.language_model,
            answer_to_critique=initial.selected_option,
        )
        assert public_result.selected is None
        assert public_result.evidence_tables == []
        assert choose.call_count == 2

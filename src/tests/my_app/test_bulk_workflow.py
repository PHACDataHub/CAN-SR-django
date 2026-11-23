from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.utils import timezone

import pytest
from django_tasks_db.models import DBTaskResult
from freezegun import freeze_time

from proj.util import MissingPreconditionError

from my_app.model_factories import (
    BulkWorkflowRequestFactory,
    CitationFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L1ScreeningResultFactory,
    ParameterExtractionResultFactory,
    ReviewFactory,
)
from my_app.models import (
    BulkWorkflowRequest,
    L1CriticalScreeningResult,
    L1ScreeningResult,
    ParameterExtractionResult,
)
from my_app.services.bulk_workflow import (
    QueueBulkResultsService,
    check_bulk_workflow_result,
)
from my_app.services.l1_screening import EnqueueL1ScreeningService
from my_app.services.parameter_extraction import (
    EnqueueParameterExtractionService,
)
from my_app.tasks.l1_screening import (
    process_l1_critical_screening_task,
    process_l1_screening_task,
)
from my_app.tasks.parameter_extraction import process_parameter_extraction_task
from tests.bulk_workflow_cases import bulk_context

pytestmark = pytest.mark.backend


@pytest.mark.parametrize("phase", [1, 3])
def test_bulk_selection_configuration_and_after_commit_dispatch(
    phase, django_capture_on_commit_callbacks, vanilla_user
):
    review, citations, question, _ = bulk_context(phase)
    other = CitationFactory(dataset__review=ReviewFactory())
    if phase == 3:
        CitationFactory(dataset=citations[0].dataset)  # No L2 inclusion.
    else:
        disabled = L1ScreeningQuestionFactory(
            review=review, disable_screening=True
        )
        L1ScreeningQuestionOptionFactory(question=disabled)
    task = "my_app.tasks.l1_screening.process_l1_screening_task"
    model = L1ScreeningResult
    if phase == 3:
        task = "my_app.tasks.parameter_extraction.process_parameter_extraction_task"
        model = ParameterExtractionResult
    with patch(task) as dispatch:
        with django_capture_on_commit_callbacks(execute=True):
            bulk = QueueBulkResultsService(
                review, phase, requested_by=vanilla_user
            ).perform()
            dispatch.enqueue.assert_not_called()
            assert model.objects.filter(bulk_request=bulk).count() == 2
        assert dispatch.enqueue.call_count == 2
    assert bulk.phase == phase
    assert bulk.requested_by == vanilla_user
    assert set(
        model.objects.filter(bulk_request=bulk).values_list(
            "citation_id", flat=True
        )
    ) == {row.pk for row in citations}
    assert not model.objects.filter(citation=other).exists()
    assert (
        DBTaskResult.objects.get().task_path
        == "my_app.tasks.bulk_workflow.check_bulk_workflow"
    )


@pytest.mark.parametrize("phase", [1, 3])
def test_unconfigured_bulk_request_is_rejected_atomically(phase):
    with pytest.raises(MissingPreconditionError):
        QueueBulkResultsService(ReviewFactory(), phase).perform()
    assert not BulkWorkflowRequest.objects.exists()
    assert not DBTaskResult.objects.exists()


@pytest.mark.parametrize("phase", [1, 3])
def test_duplicate_pending_bulk_request_preserves_results(phase):
    review, _, _, _ = bulk_context(phase)
    bulk = QueueBulkResultsService(review, phase).perform()
    with pytest.raises(MissingPreconditionError, match="already pending"):
        QueueBulkResultsService(review, phase).perform()
    assert BulkWorkflowRequest.objects.count() == 1
    results = bulk.l1_results
    if phase == 3:
        results = bulk.parameter_results
    assert results.count() == 2
    with pytest.raises(IntegrityError), transaction.atomic():
        BulkWorkflowRequestFactory(review=review, phase=phase)


def test_different_phases_can_run_for_the_same_review():
    review, _, _, _ = bulk_context(3)
    l1 = L1ScreeningQuestionFactory(review=review)
    L1ScreeningQuestionOptionFactory(question=l1)
    first = QueueBulkResultsService(review, 1).perform()
    third = QueueBulkResultsService(review, 3).perform()
    assert first.phase == 1 and third.phase == 3


def test_parameter_prerequisite_failure_does_not_delete_previous_results():
    review, citations, parameter, _ = bulk_context(3)
    old = ParameterExtractionResultFactory(
        citation=citations[0], question=parameter, status="completed"
    )
    citations[1].document.text_extraction_result.delete()
    with pytest.raises(MissingPreconditionError):
        QueueBulkResultsService(review, 3).perform()
    assert ParameterExtractionResult.objects.filter(pk=old.pk).exists()
    assert not BulkWorkflowRequest.objects.exists()


@pytest.mark.parametrize("phase", [1, 3])
def test_empty_bulk_finishes_successfully(phase):
    review, citations, _, _ = bulk_context(phase)
    for citation in citations:
        citation.delete()
    bulk = QueueBulkResultsService(review, phase).perform()
    check_bulk_workflow_result(bulk.pk)
    bulk.refresh_from_db()
    assert bulk.status == "completed"
    assert bulk.finished_at


@pytest.mark.parametrize(
    "initial,critical,expected",
    [
        ("pending", None, "pending"),
        ("completed", None, "pending"),
        ("completed", "pending", "pending"),
        ("completed", "completed", "completed"),
        ("abandoned", None, "failed"),
        ("completed", "abandoned", "failed"),
    ],
)
def test_l1_completion_includes_critical_screening(
    initial, critical, expected
):
    bulk = BulkWorkflowRequestFactory(phase=1)
    result = L1ScreeningResultFactory(bulk_request=bulk, status=initial)
    if critical:
        L1CriticalScreeningResult.objects.create(
            initial_result=result, status=critical
        )
    with freeze_time("2026-11-20 12:00:00"):
        check_bulk_workflow_result(bulk.pk)
        bulk.refresh_from_db()
        assert bulk.status == expected
        if expected != "pending":
            assert bulk.finished_at == timezone.now()
    finished_at = bulk.finished_at
    check_bulk_workflow_result(bulk.pk)
    bulk.refresh_from_db()
    assert bulk.finished_at == finished_at


@pytest.mark.parametrize(
    "statuses,expected",
    [
        (["pending"], "pending"),
        (["completed"], "completed"),
        (["abandoned"], "failed"),
        (["abandoned", "pending"], "pending"),
        (["abandoned", "completed"], "failed"),
    ],
)
def test_parameter_completion_only_waits_for_parameter_results(
    statuses, expected
):
    bulk = BulkWorkflowRequestFactory(phase=3)
    for status in statuses:
        ParameterExtractionResultFactory(bulk_request=bulk, status=status)
    check_bulk_workflow_result(bulk.pk)
    bulk.refresh_from_db()
    assert bulk.status == expected
    assert bool(bulk.finished_at) == (expected != "pending")


def test_l1_failure_waits_for_other_pairs_to_settle():
    bulk = BulkWorkflowRequestFactory(phase=1)
    L1ScreeningResultFactory(bulk_request=bulk, status="abandoned")
    pending = L1ScreeningResultFactory(bulk_request=bulk, status="pending")
    check_bulk_workflow_result(bulk.pk)
    bulk.refresh_from_db()
    assert bulk.status == "pending"
    pending.status = "abandoned"
    pending.save()
    check_bulk_workflow_result(bulk.pk)
    bulk.refresh_from_db()
    assert bulk.status == "failed"


@pytest.mark.parametrize("phase", [1, 3])
def test_bulk_checker_reschedules_while_results_are_pending(
    phase, django_capture_on_commit_callbacks
):
    bulk = BulkWorkflowRequestFactory(phase=phase)
    factory = L1ScreeningResultFactory
    if phase == 3:
        factory = ParameterExtractionResultFactory
    factory(bulk_request=bulk)
    with freeze_time("2026-11-20 12:00:00"):
        with django_capture_on_commit_callbacks(execute=True):
            check_bulk_workflow_result(bulk.pk)
        task = DBTaskResult.objects.get()
        assert task.run_after == timezone.now() + timedelta(seconds=5)


@pytest.mark.parametrize("kind", ["initial", "critical", "parameter"])
def test_bulk_task_errors_set_result_terminal(kind):
    bulk = BulkWorkflowRequestFactory(phase=1)
    result = L1ScreeningResultFactory(bulk_request=bulk)
    task = process_l1_screening_task
    service = "my_app.tasks.l1_screening.ProcessL1ScreeningService.perform"
    if kind == "critical":
        result = L1CriticalScreeningResult.objects.create(
            initial_result=result
        )
        task = process_l1_critical_screening_task
        service = "my_app.services.critical_screening.ProcessL1CriticalScreeningService.perform"
    elif kind == "parameter":
        bulk.phase = 3
        bulk.save()
        result = ParameterExtractionResultFactory(bulk_request=bulk)
        task = process_parameter_extraction_task
        service = "my_app.tasks.parameter_extraction.ProcessParameterExtractionService.perform"
    with (
        patch(service, side_effect=RuntimeError("API failed")),
        pytest.raises(RuntimeError),
    ):
        task.call(result_id=result.pk)
    result.refresh_from_db()
    assert result.status == "abandoned"
    assert result.abandoned_at


@pytest.mark.parametrize("phase", [1, 3])
def test_initial_dispatch_failure_does_not_block_other_results(
    phase, django_capture_on_commit_callbacks
):
    review, _, _, _ = bulk_context(phase)
    path = "my_app.tasks.l1_screening.process_l1_screening_task"
    if phase == 3:
        path = "my_app.tasks.parameter_extraction.process_parameter_extraction_task"
    with patch(path) as task:
        task.enqueue.side_effect = [RuntimeError("queue failed"), None]
        with django_capture_on_commit_callbacks(execute=True):
            bulk = QueueBulkResultsService(review, phase).perform()
    results = bulk.l1_results
    if phase == 3:
        results = bulk.parameter_results
    assert results.filter(status="abandoned").count() == 1
    assert results.filter(status="pending").count() == 1
    assert task.enqueue.call_count == 2


@pytest.mark.parametrize("phase", [1, 3])
def test_database_worker_completes_bulk(
    phase, django_capture_on_commit_callbacks, run_database_tasks
):
    review, _, _, option = bulk_context(phase)
    initial = SimpleNamespace(
        selected=option, confidence=0.95, explanation="Included"
    )
    critical = SimpleNamespace(selected=None, confidence=0.95)
    parameter = SimpleNamespace(
        found=True,
        value="Example value",
        explanation="Extracted",
        evidence_sentences=[],
        evidence_tables=[],
        evidence_figures=[],
    )
    with (
        freeze_time("2026-11-20 12:00:00") as clock,
        patch(
            "my_app.services.l1_screening.get_l1_screening_results",
            return_value=initial,
        ) as l1,
        patch(
            "my_app.services.critical_screening.get_l1_screening_results",
            return_value=critical,
        ) as review_task,
        patch(
            "my_app.services.parameter_extraction.get_parameter_extraction_results",
            return_value=parameter,
        ) as parameters,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            bulk = QueueBulkResultsService(review, phase).perform()
        for _ in range(5):
            with django_capture_on_commit_callbacks(execute=True):
                run_database_tasks()
            clock.tick(timedelta(seconds=6))
    bulk.refresh_from_db()
    assert bulk.status == "completed"
    assert bulk.finished_at
    if phase == 1:
        assert l1.call_count == review_task.call_count == 2
        assert parameters.call_count == 0
    else:
        assert parameters.call_count == 2
        assert l1.call_count == review_task.call_count == 0
        assert not L1CriticalScreeningResult.objects.exists()


@pytest.mark.parametrize("phase,query_count", [(1, 4), (3, 5)])
def test_batch_preparation_has_constant_queries(
    phase, query_count, django_assert_num_queries
):
    review, citations, question, _ = bulk_context(phase, count=13)
    service = EnqueueL1ScreeningService
    module = "my_app.services.l1_screening"
    if phase == 3:
        service = EnqueueParameterExtractionService
        module = "my_app.services.parameter_extraction"
    with patch(module + ".get_model_for_review", return_value=None):
        with django_assert_num_queries(query_count):
            results = service(citations, [question]).perform()
    assert len(results) == 13


def test_previous_phase2_bulk_task_entrypoint_still_runs(run_database_tasks):
    from my_app.tasks.phase2_workflow import check_bulk_workflow

    bulk = BulkWorkflowRequestFactory()
    check_bulk_workflow.enqueue(request_id=bulk.pk)
    run_database_tasks()
    bulk.refresh_from_db()
    assert bulk.phase == 2
    assert bulk.status == "completed"

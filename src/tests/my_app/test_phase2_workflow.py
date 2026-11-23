from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

import pytest
from freezegun import freeze_time
from phac_aspc.rules import patch_rules

from proj.util import MissingPreconditionError

from my_app.model_factories import (
    BulkWorkflowRequestFactory,
    CitationFactory,
    DocumentFactory,
    FigureExtractionResultFactory,
    L1HumanAnswerFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    L2ScreeningResultFactory,
    PdfFromDOIRequestFactory,
    Phase2CitationWorkflowRequestFactory,
    ReviewFactory,
    TextExtractionResultFactory,
)
from my_app.models import (
    BulkWorkflowRequest,
    FigureExtractionResult,
    L2CriticalScreeningResult,
    L2ScreeningResult,
    PdfFromDOIRequest,
    Phase2CitationWorkflowRequest,
    ScreeningActions,
    TextExtractionResult,
    WorkflowStatus,
)
from my_app.services.l2_screening import EnqueueL2ScreeningService
from my_app.services.phase2_workflow import (
    QueueBulkWorkflowService,
    QueueCitationWorkflowService,
    check_bulk_workflow_result,
    check_citation_workflow_result,
)
from my_app.tasks.l2_screening import (
    process_l2_critical_screening_task,
    process_l2_screening_task,
)

pytestmark = pytest.mark.backend


def screening_context():
    citation = CitationFactory(document=DocumentFactory())
    TextExtractionResultFactory(document=citation.document, status="completed")
    FigureExtractionResultFactory(
        document=citation.document, status="completed"
    )
    question = L2ScreeningQuestionFactory(review=citation.dataset.review)
    option = L2ScreeningQuestionOptionFactory(question=question)
    return citation, question, option


def queue_screening(citation):
    return QueueCitationWorkflowService(
        citation,
        should_download_pdf=False,
        should_process_pdf=False,
    ).perform()


def included_citation(review):
    citation = CitationFactory(dataset__review=review)
    question = L1ScreeningQuestionFactory(review=review)
    option = L1ScreeningQuestionOptionFactory(
        question=question, screening_action=ScreeningActions.ScreenIn
    )
    L1HumanAnswerFactory(
        citation=citation, question=question, selected_option=option
    )
    return citation


def test_queue_stores_options_and_dispatches_after_commit(
    django_capture_on_commit_callbacks, vanilla_user
):
    citation, question, _ = screening_context()
    with patch(
        "my_app.tasks.phase2_workflow.check_citation_workflow"
    ) as enqueue:
        with django_capture_on_commit_callbacks(execute=True):
            workflow = QueueCitationWorkflowService(
                citation, requested_by=vanilla_user
            ).perform()
            enqueue.enqueue.assert_not_called()
        enqueue.enqueue.assert_called_once_with(request_id=workflow.pk)
    assert workflow.requested_by == vanilla_user
    assert workflow.finished_at is None
    assert (
        workflow.should_download_pdf
        and workflow.should_process_pdf
        and workflow.should_run_l2
    )


def test_duplicate_request_is_rejected_and_database_enforces_it():
    citation = CitationFactory()
    Phase2CitationWorkflowRequestFactory(citation=citation)
    with pytest.raises(MissingPreconditionError, match="already pending"):
        QueueCitationWorkflowService(citation, should_run_l2=False).perform()
    with pytest.raises(IntegrityError), transaction.atomic():
        Phase2CitationWorkflowRequestFactory(citation=citation)


def test_completed_request_does_not_prevent_new_request():
    citation = CitationFactory()
    Phase2CitationWorkflowRequestFactory(citation=citation, status="completed")
    assert (
        QueueCitationWorkflowService(citation, should_run_l2=False)
        .perform()
        .status
        == "pending"
    )


@pytest.mark.parametrize(
    "options",
    [
        dict(
            should_download_pdf=False,
            should_process_pdf=False,
            should_run_l2=False,
        ),
        dict(should_run_l2=True),
    ],
)
def test_invalid_selection_creates_no_request(options):
    with pytest.raises(MissingPreconditionError):
        QueueCitationWorkflowService(CitationFactory(), **options).perform()
    assert not Phase2CitationWorkflowRequest.objects.exists()


@override_settings(
    TASKS={
        "default": {
            "BACKEND": "django.tasks.backends.immediate.ImmediateBackend"
        }
    }
)
def test_workflow_rejects_backend_without_deferred_tasks():
    with pytest.raises(MissingPreconditionError, match="deferred"):
        QueueCitationWorkflowService(
            CitationFactory(), should_run_l2=False
        ).perform()


def test_missing_pdf_without_download_fails():
    workflow = Phase2CitationWorkflowRequestFactory(
        should_download_pdf=False, should_run_l2=False
    )
    check_citation_workflow_result(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == "failed"
    assert "attached document" in workflow.error
    assert workflow.finished_at


def test_missing_doi_fails_without_leaving_download_request():
    workflow = Phase2CitationWorkflowRequestFactory(should_run_l2=False)
    check_citation_workflow_result(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == "failed"
    assert "valid DOI" in workflow.error
    assert not PdfFromDOIRequest.objects.exists()


def test_download_only_skips_existing_document_and_finishes():
    workflow = Phase2CitationWorkflowRequestFactory(
        citation__document=DocumentFactory(),
        should_process_pdf=False,
        should_run_l2=False,
    )
    check_citation_workflow_result(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == "completed"
    assert not PdfFromDOIRequest.objects.exists()


def test_download_is_started_then_rechecked_without_duplicate_dispatch(
    django_capture_on_commit_callbacks,
):
    workflow = Phase2CitationWorkflowRequestFactory(
        citation__doi="10.1234/example",
        should_process_pdf=False,
        should_run_l2=False,
    )
    with patch(
        "my_app.services.doi_pdf_service.QueueDoiPdfService.enqueue"
    ) as enqueue:
        with django_capture_on_commit_callbacks(execute=True):
            check_citation_workflow_result(workflow.pk)
        workflow.refresh_from_db()
        request = PdfFromDOIRequest.objects.get(citation=workflow.citation)
        assert workflow.current_process == "download_pdf"
        enqueue.assert_called_once()
        check_citation_workflow_result(workflow.pk)
        assert enqueue.call_count == 1
    workflow.citation.document = DocumentFactory()
    workflow.citation.save(update_fields=["document"])
    request.status = "fulfilled"
    request.save()
    check_citation_workflow_result(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == "completed"


@pytest.mark.parametrize(
    "status", ["pending", "failed", "fulfilled", "canceled"]
)
def test_existing_download_policy(status):
    request = PdfFromDOIRequestFactory(status=status)
    workflow = Phase2CitationWorkflowRequestFactory(
        citation=request.citation,
        should_process_pdf=False,
        should_run_l2=False,
    )
    check_citation_workflow_result(workflow.pk)
    workflow.refresh_from_db()
    if status == "pending":
        assert workflow.status == "failed"
        assert "already pending" in workflow.error
    else:
        assert workflow.status == "pending"
        request.refresh_from_db()
        assert request.status == "pending"
    assert PdfFromDOIRequest.objects.count() == 1


def test_pdf_processing_waits_for_both_tasks_and_advances_to_l2():
    citation, question, _ = screening_context()
    TextExtractionResult.objects.filter(document=citation.document).delete()
    FigureExtractionResult.objects.filter(document=citation.document).delete()
    workflow = QueueCitationWorkflowService(citation).perform()
    check_citation_workflow_result(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.current_process == "process_pdf"
    assert workflow.text_extraction_results.get().document == citation.document
    assert (
        workflow.figure_extraction_results.get().document == citation.document
    )
    check_citation_workflow_result(workflow.pk)
    assert not workflow.screening_results.exists()
    TextExtractionResult.objects.filter(document=citation.document).update(
        status="completed"
    )
    check_citation_workflow_result(workflow.pk)
    assert not workflow.screening_results.exists()
    FigureExtractionResult.objects.filter(document=citation.document).update(
        status="completed"
    )
    check_citation_workflow_result(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.current_process == "l2"
    assert list(
        workflow.screening_results.values_list("question_id", flat=True)
    ) == [question.pk]
    check_citation_workflow_result(workflow.pk)
    assert workflow.screening_results.count() == 1


@pytest.mark.parametrize("failed_extraction", ["text", "figures"])
@pytest.mark.parametrize("other_status", ["pending", "completed"])
def test_pdf_processing_failure_waits_for_both_extractions(
    failed_extraction, other_status
):
    document = DocumentFactory()
    text_status, figure_status = other_status, "failed"
    if failed_extraction == "text":
        text_status, figure_status = "failed", other_status
    TextExtractionResultFactory(document=document, status=text_status)
    FigureExtractionResultFactory(document=document, status=figure_status)
    workflow = Phase2CitationWorkflowRequestFactory(
        citation__document=document,
        current_process="process_pdf",
    )
    check_citation_workflow_result(workflow.pk)
    workflow.refresh_from_db()
    if other_status == "pending":
        assert workflow.status == "pending"
        TextExtractionResult.objects.filter(
            document=document, status="pending"
        ).update(status="completed")
        FigureExtractionResult.objects.filter(
            document=document, status="pending"
        ).update(status="completed")
        check_citation_workflow_result(workflow.pk)
        workflow.refresh_from_db()
    assert workflow.status == "failed"
    assert workflow.finished_at


def test_l2_waits_for_all_initial_and_critical_results_then_finishes():
    citation, question, option = screening_context()
    second = L2ScreeningQuestionFactory(review=citation.dataset.review)
    L2ScreeningQuestionOptionFactory(question=second)
    workflow = queue_screening(citation)
    check_citation_workflow_result(workflow.pk)
    for result in workflow.screening_results.all():
        result.status = "completed"
        result.selected_option = option
        result.save()
    check_citation_workflow_result(workflow.pk)
    workflow.refresh_from_db()
    assert (
        workflow.status == "pending"
    )  # Missing critical rows are not complete.
    for result in workflow.screening_results.all():
        L2CriticalScreeningResult.objects.create(
            initial_result=result, status="pending"
        )
    check_citation_workflow_result(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == "pending"
    L2CriticalScreeningResult.objects.update(status="completed")
    with freeze_time("2026-11-17 12:00:00"):
        check_citation_workflow_result(workflow.pk)
        workflow.refresh_from_db()
        assert workflow.status == "completed"
        assert workflow.finished_at == timezone.now()
    finished_at = workflow.finished_at
    check_citation_workflow_result(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.finished_at == finished_at


@pytest.mark.parametrize("failure", ["initial", "critical"])
def test_l2_terminal_failures(failure):
    citation, _, _ = screening_context()
    workflow = queue_screening(citation)
    check_citation_workflow_result(workflow.pk)
    result = workflow.screening_results.get()
    if failure == "initial":
        result.status = "abandoned"
        result.save()
    else:
        result.status = "completed"
        result.save()
        L2CriticalScreeningResult.objects.create(
            initial_result=result, status="abandoned"
        )
    check_citation_workflow_result(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == "failed"


@pytest.mark.parametrize("critical", [False, True])
def test_task_errors_set_workflow_owned_results_abandoned(critical):
    citation, question, _ = screening_context()
    workflow = queue_screening(citation)
    result = L2ScreeningResultFactory(
        citation=citation, question=question, workflow_request=workflow
    )
    task = process_l2_screening_task
    service = "my_app.tasks.l2_screening.ProcessL2ScreeningService.perform"
    if critical:
        result = L2CriticalScreeningResult.objects.create(
            initial_result=result
        )
        task = process_l2_critical_screening_task
        service = "my_app.services.critical_screening.ProcessL2CriticalScreeningService.perform"
    with (
        patch(service, side_effect=RuntimeError("API failed")),
        pytest.raises(RuntimeError),
    ):
        task.call(result_id=result.pk)
    result.refresh_from_db()
    assert result.status == "abandoned"
    assert result.abandoned_at


def test_checker_reschedules_incomplete_workflow(
    django_capture_on_commit_callbacks,
):
    request = PdfFromDOIRequestFactory()
    workflow = Phase2CitationWorkflowRequestFactory(
        citation=request.citation,
        current_process="download_pdf",
    )
    from django_tasks_db.models import DBTaskResult

    with freeze_time("2026-11-17 12:00:00"):
        with django_capture_on_commit_callbacks(execute=True):
            check_citation_workflow_result(workflow.pk)
        task = DBTaskResult.objects.get(
            task_path="my_app.tasks.phase2_workflow.check_citation_workflow"
        )
        assert task.run_after == timezone.now() + timedelta(seconds=5)


def test_bulk_selects_only_l1_included_and_prepares_all_children_before_dispatch(
    django_capture_on_commit_callbacks,
):
    review = ReviewFactory()
    citation = included_citation(review)
    CitationFactory(dataset=citation.dataset)
    included_citation(ReviewFactory())
    with (
        patch(
            "my_app.tasks.phase2_workflow.check_citation_workflow"
        ) as enqueue,
        patch(
            "my_app.tasks.phase2_workflow.check_bulk_workflow"
        ) as bulk_enqueue,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            bulk = QueueBulkWorkflowService(
                review, should_run_l2=False
            ).perform()
            enqueue.enqueue.assert_not_called()
            assert bulk.citation_requests.count() == 1
        enqueue.enqueue.assert_called_once_with(
            request_id=bulk.citation_requests.get().pk
        )
        bulk_enqueue.enqueue.assert_called_once_with(request_id=bulk.pk)
    assert bulk.citation_requests.get().citation == citation


def test_bulk_duplicate_selection_is_atomic():
    review = ReviewFactory()
    citation = included_citation(review)
    Phase2CitationWorkflowRequestFactory(citation=citation)
    with pytest.raises(MissingPreconditionError):
        QueueBulkWorkflowService(review, should_run_l2=False).perform()
    assert not BulkWorkflowRequest.objects.exists()


@pytest.mark.parametrize(
    "statuses,expected",
    [
        ([], "completed"),
        (["completed"], "completed"),
        (["failed", "completed"], "failed"),
        (["failed", "pending"], "pending"),
    ],
)
def test_bulk_completion_waits_for_all_children(statuses, expected):
    bulk = BulkWorkflowRequestFactory()
    for status in statuses:
        Phase2CitationWorkflowRequestFactory(bulk_request=bulk, status=status)
    check_bulk_workflow_result(bulk.pk)
    bulk.refresh_from_db()
    assert bulk.status == expected
    assert bool(bulk.finished_at) == (expected != "pending")
    finished_at = bulk.finished_at
    check_bulk_workflow_result(bulk.pk)
    bulk.refresh_from_db()
    assert bulk.finished_at == finished_at


def test_l2_bulk_validation_preserves_existing_answers():
    citation, question, _ = screening_context()
    result = L2ScreeningResultFactory(
        citation=citation, question=question, status="completed"
    )
    invalid_citation = CitationFactory(dataset=citation.dataset)
    with pytest.raises(MissingPreconditionError):
        EnqueueL2ScreeningService(
            [citation, invalid_citation], [question], overwrite_existing=True
        ).perform()
    assert L2ScreeningResult.objects.filter(pk=result.pk).exists()


@pytest.mark.parametrize("bulk", [False, True])
def test_full_download_processing_screening_pipeline_with_database_worker(
    run_database_tasks,
    django_capture_on_commit_callbacks,
    bulk,
):
    citation, question, option = screening_context()
    citation.document = None
    citation.doi = "10.1234/example"
    citation.save()

    def download(service):
        request = PdfFromDOIRequest.objects.get(citation=service.citation)
        service.citation.document = DocumentFactory()
        service.citation.save(update_fields=["document"])
        request.status = "fulfilled"
        request.save()
        return request

    def extract_text(service):
        result = service.document.text_extraction_result
        result.status = "completed"
        result.save()

    def extract_figures(service):
        result = service.document.figure_extraction_result
        result.status = "completed"
        result.save()

    def screen(*args, **kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(
            selected=option,
            confidence=0.95,
            explanation="Included",
            evidence_sentences=[],
            evidence_tables=[],
            evidence_figures=[],
        )

    def critical(*args, **kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(selected=None, confidence=0.95)

    with (
        freeze_time("2026-11-17 12:00:00") as clock,
        patch(
            "my_app.services.doi_pdf_service.DoiPdfService.perform",
            autospec=True,
            side_effect=download,
        ),
        patch(
            "my_app.services.text_extraction.TextExtractionService.perform",
            autospec=True,
            side_effect=extract_text,
        ),
        patch(
            "my_app.services.figure_extraction_service.FigureExtractionService.perform",
            autospec=True,
            side_effect=extract_figures,
        ),
        patch(
            "my_app.services.l2_screening.get_l2_screening_results",
            side_effect=screen,
        ),
        patch(
            "my_app.services.critical_screening.get_l2_screening_results",
            side_effect=critical,
        ),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            if bulk:
                l1_question = L1ScreeningQuestionFactory(
                    review=citation.dataset.review
                )
                l1_option = L1ScreeningQuestionOptionFactory(
                    question=l1_question,
                    screening_action=ScreeningActions.ScreenIn,
                )
                L1HumanAnswerFactory(
                    citation=citation,
                    question=l1_question,
                    selected_option=l1_option,
                )
                parent = QueueBulkWorkflowService(
                    citation.dataset.review
                ).perform()
                workflow = parent.citation_requests.get()
            else:
                workflow = QueueCitationWorkflowService(citation).perform()
        for _ in range(12):
            with django_capture_on_commit_callbacks(execute=True):
                run_database_tasks()
            clock.tick(timedelta(seconds=6))
        workflow.refresh_from_db()
        assert workflow.status == WorkflowStatus.COMPLETED
        assert workflow.finished_at
        result = workflow.screening_results.get()
        assert result.status == "completed"
        assert result.critical_result.status == "completed"
        assert result.selected_option == option
        if bulk:
            parent.refresh_from_db()
            assert parent.status == WorkflowStatus.COMPLETED
            assert parent.finished_at


def test_bulk_l2_preparation_uses_constant_queries(django_assert_num_queries):
    citation, question, _ = screening_context()
    rows = [citation] + [
        CitationFactory(dataset=citation.dataset, document=citation.document)
        for _ in range(12)
    ]
    second = L2ScreeningQuestionFactory(review=citation.dataset.review)
    with patch(
        "my_app.services.l2_screening.get_model_for_review", return_value=None
    ):
        # Fetch citations, existing pairs, bulk insert, and transaction savepoints.
        with django_assert_num_queries(5):
            results = EnqueueL2ScreeningService(
                rows, [question, second]
            ).perform()
    assert len(results) == 26


def test_l2_dispatch_failure_abandons_only_failed_result_and_dispatches_others(
    django_capture_on_commit_callbacks,
):
    citation, question, _ = screening_context()
    second = L2ScreeningQuestionFactory(review=citation.dataset.review)
    L2ScreeningQuestionOptionFactory(question=second)
    workflow = queue_screening(citation)
    with patch("my_app.tasks.l2_screening.process_l2_screening_task") as task:
        task.enqueue.side_effect = [RuntimeError("queue unavailable"), None]
        with django_capture_on_commit_callbacks(execute=True):
            check_citation_workflow_result(workflow.pk)
    assert task.enqueue.call_count == 2
    assert workflow.screening_results.filter(status="abandoned").count() == 1
    assert workflow.screening_results.filter(status="pending").count() == 1


def test_bulk_checker_reschedules_without_finishing(
    django_capture_on_commit_callbacks,
):
    from django_tasks_db.models import DBTaskResult

    bulk = BulkWorkflowRequestFactory()
    Phase2CitationWorkflowRequestFactory(bulk_request=bulk)
    with freeze_time("2026-11-17 12:00:00"):
        with django_capture_on_commit_callbacks(execute=True):
            check_bulk_workflow_result(bulk.pk)
        task = DBTaskResult.objects.get(
            task_path="my_app.tasks.phase2_workflow.check_bulk_workflow"
        )
        assert task.run_after == timezone.now() + timedelta(seconds=5)
    bulk.refresh_from_db()
    assert bulk.finished_at is None


def test_failed_critical_dispatch_does_not_leave_pending_result():
    citation, question, _ = screening_context()
    workflow = queue_screening(citation)
    result = L2ScreeningResultFactory(
        citation=citation, question=question, workflow_request=workflow
    )

    def perform(service):
        result.status = "completed"
        result.save()
        L2CriticalScreeningResult.objects.create(initial_result=result)
        raise RuntimeError("critical task dispatch failed")

    with (
        patch(
            "my_app.tasks.l2_screening.ProcessL2ScreeningService.perform",
            autospec=True,
            side_effect=perform,
        ),
        pytest.raises(RuntimeError),
    ):
        process_l2_screening_task.call(result_id=result.pk)
    result.refresh_from_db()
    assert result.critical_result.status == "abandoned"


def test_processing_only_workflow_finishes_without_dispatching_l2():
    citation, _, _ = screening_context()
    workflow = Phase2CitationWorkflowRequestFactory(
        citation=citation,
        current_process="process_pdf",
        should_download_pdf=False,
        should_run_l2=False,
    )
    check_citation_workflow_result(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == "completed"
    assert not workflow.screening_results.exists()


def test_unexpected_preparation_failure_rolls_back_and_marks_request_failed():
    citation = CitationFactory(document=DocumentFactory())
    workflow = Phase2CitationWorkflowRequestFactory(
        citation=citation, should_run_l2=False
    )
    with (
        patch(
            "my_app.services.process_document.TextExtractionResult.objects.get_or_create",
            side_effect=RuntimeError("unexpected failure"),
        ),
        pytest.raises(RuntimeError),
    ):
        check_citation_workflow_result(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == "failed"
    assert workflow.finished_at
    assert workflow.current_process == "not_started"
    assert not TextExtractionResult.objects.exists()
    assert not FigureExtractionResult.objects.exists()


def test_two_citation_workflows_share_document_extractions(
    django_capture_on_commit_callbacks,
):
    from django_tasks_db.models import DBTaskResult

    document = DocumentFactory()
    first = Phase2CitationWorkflowRequestFactory(
        citation__document=document,
        should_download_pdf=False,
        should_run_l2=False,
    )
    second = Phase2CitationWorkflowRequestFactory(
        citation__document=document,
        should_download_pdf=False,
        should_run_l2=False,
    )
    with django_capture_on_commit_callbacks(execute=True):
        check_citation_workflow_result(first.pk)
        check_citation_workflow_result(second.pk)
    assert (
        DBTaskResult.objects.filter(
            task_path__in=[
                "my_app.tasks.text_extraction_task.process_text_extraction_result",
                "my_app.tasks.figure_extraction_task.process_figure_extraction",
            ]
        ).count()
        == 2
    )
    text = TextExtractionResult.objects.get(document=document)
    figures = FigureExtractionResult.objects.get(document=document)
    assert text.workflow_request == figures.workflow_request == first
    check_citation_workflow_result(second.pk)
    second.refresh_from_db()
    assert second.status == "pending"
    text.status = "completed"
    text.save()
    figures.status = "completed"
    figures.save()
    check_citation_workflow_result(first.pk)
    check_citation_workflow_result(second.pk)
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == second.status == "completed"

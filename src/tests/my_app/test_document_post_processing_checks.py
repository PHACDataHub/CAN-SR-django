from unittest.mock import patch

from django.test import override_settings

import pytest
from django_tasks_db.models import DBTaskResult

from my_app.model_factories import (
    DocumentFactory,
    FigureExtractionResultFactory,
    Phase2CitationWorkflowRequestFactory,
    TextExtractionResultFactory,
)
from my_app.models import FigureExtractionResult, TextExtractionResult
from my_app.services.process_document import QueueProcessDocumentService

pytestmark = pytest.mark.backend


def test_queue_missing_extractions_independently_after_commit(
    django_capture_on_commit_callbacks,
):
    workflow = Phase2CitationWorkflowRequestFactory(
        citation__document=DocumentFactory()
    )
    document = workflow.citation.document
    with django_capture_on_commit_callbacks(execute=True):
        text, figures = QueueProcessDocumentService(
            document, workflow_request=workflow
        ).perform()
        assert not DBTaskResult.objects.exists()
    assert text.workflow_request == figures.workflow_request == workflow
    assert text.status == figures.status == "pending"
    assert set(DBTaskResult.objects.values_list("task_path", flat=True)) == {
        "my_app.tasks.text_extraction_task.process_text_extraction_result",
        "my_app.tasks.figure_extraction_task.process_figure_extraction",
    }


@pytest.mark.parametrize("status", ["pending", "completed", "failed"])
def test_existing_results_are_reused_without_dispatch_or_reset(
    status, django_capture_on_commit_callbacks
):
    owner = Phase2CitationWorkflowRequestFactory(
        citation__document=DocumentFactory()
    )
    document = owner.citation.document
    text = TextExtractionResultFactory(
        document=document, status=status, workflow_request=owner
    )
    figures = FigureExtractionResultFactory(
        document=document, status=status, workflow_request=owner
    )
    workflow = Phase2CitationWorkflowRequestFactory(
        citation__document=document
    )
    with django_capture_on_commit_callbacks(execute=True):
        results = QueueProcessDocumentService(
            document, workflow_request=workflow
        ).perform()
    assert results == (text, figures)
    for result in results:
        result.refresh_from_db()
        assert result.status == status
        assert result.workflow_request == owner
    assert not DBTaskResult.objects.exists()


@pytest.mark.parametrize("existing", ["text", "figures"])
def test_only_missing_extraction_is_queued(
    existing, django_capture_on_commit_callbacks
):
    document = DocumentFactory()
    if existing == "text":
        TextExtractionResultFactory(document=document, status="completed")
        expected_task = (
            "my_app.tasks.figure_extraction_task.process_figure_extraction"
        )
    else:
        FigureExtractionResultFactory(document=document, status="completed")
        expected_task = (
            "my_app.tasks.text_extraction_task.process_text_extraction_result"
        )
    with django_capture_on_commit_callbacks(execute=True):
        QueueProcessDocumentService(document).perform()
    assert DBTaskResult.objects.get().task_path == expected_task


@pytest.mark.parametrize(
    "backend",
    [
        "django.tasks.backends.immediate.ImmediateBackend",
        "django_tasks_db.DatabaseBackend",
    ],
)
def test_extractions_run_with_supported_backends(
    backend, run_database_tasks, django_capture_on_commit_callbacks
):
    with (
        override_settings(
            TASKS={"default": {"BACKEND": backend, "QUEUES": ["default"]}}
        ),
        patch(
            "my_app.services.text_extraction.TextExtractionService.perform"
        ) as text,
        patch(
            "my_app.services.figure_extraction_service.FigureExtractionService.perform"
        ) as figures,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            QueueProcessDocumentService(DocumentFactory()).perform()
        if backend == "django_tasks_db.DatabaseBackend":
            run_database_tasks()
        text.assert_called_once()
        figures.assert_called_once()


def test_dispatch_failure_does_not_prevent_other_extraction(
    django_capture_on_commit_callbacks,
):
    document = DocumentFactory()
    with patch(
        "my_app.tasks.text_extraction_task.process_text_extraction_result"
    ) as task:
        task.enqueue.side_effect = RuntimeError("queue unavailable")
        with django_capture_on_commit_callbacks(execute=True):
            QueueProcessDocumentService(document).perform()
    assert (
        TextExtractionResult.objects.get(document=document).status == "failed"
    )
    assert (
        FigureExtractionResult.objects.get(document=document).status
        == "pending"
    )
    assert (
        DBTaskResult.objects.get().task_path
        == "my_app.tasks.figure_extraction_task.process_figure_extraction"
    )

from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings

import pytest

from proj.models import TaskGroup
from proj.util import MissingPreconditionError

from my_app.model_factories import (
    CitationFactory,
    DocumentFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    ParameterCategoryFactory,
    ParameterFactory,
)
from my_app.services.process_document import QueueProcessDocumentService

pytestmark = pytest.mark.backend


def test_queue_process_document_prepares_and_groups_extractions():
    document = DocumentFactory()
    citation = CitationFactory(document=document)
    l2_question = L2ScreeningQuestionFactory(review=citation.dataset.review)
    L2ScreeningQuestionOptionFactory(question=l2_question)
    category = ParameterCategoryFactory(review=citation.dataset.review)
    ParameterFactory(category=category)

    with (
        patch(
            "my_app.services.process_document.TextExtractionService"
        ) as text_service,
        patch(
            "my_app.services.process_document.FigureExtractionService"
        ) as figure_service,
    ):
        group = QueueProcessDocumentService(
            document,
            should_run_l2_screening=True,
            should_run_parameter_extraction=True,
        ).perform()

    text_service.return_value.prepare.assert_called_once_with()
    figure_service.return_value.prepare.assert_called_once_with()
    assert group.key == f"process-document:{document.id}"
    assert set(group.members) == {"text_extraction", "figure_extraction"}
    assert group.callback_kwargs == {
        "citation_id": citation.id,
        "should_run_l2_screening": True,
        "should_run_parameter_extraction": True,
    }


def test_queue_process_document_allows_extraction_only_without_configuration():
    document = DocumentFactory()
    citation = CitationFactory(document=document)

    with (
        patch("my_app.services.process_document.TextExtractionService"),
        patch("my_app.services.process_document.FigureExtractionService"),
    ):
        group = QueueProcessDocumentService(document).perform()

    assert group.callback_kwargs == {
        "citation_id": citation.id,
        "should_run_l2_screening": False,
        "should_run_parameter_extraction": False,
    }


@pytest.mark.parametrize(
    ("service_kwargs", "error_message"),
    [
        (
            {"should_run_l2_screening": True},
            "L2 screening criteria must be configured",
        ),
        (
            {"should_run_parameter_extraction": True},
            "Parameters must be configured",
        ),
    ],
)
def test_queue_process_document_rejects_unconfigured_post_processing(
    service_kwargs,
    error_message,
):
    document = DocumentFactory()
    CitationFactory(document=document)

    with pytest.raises(MissingPreconditionError, match=error_message):
        QueueProcessDocumentService(document, **service_kwargs).perform()

    assert TaskGroup.objects.count() == 0


@pytest.mark.parametrize(
    "backend",
    [
        "django.tasks.backends.immediate.ImmediateBackend",
        "django_database_task.backends.DatabaseTaskBackend",
    ],
)
def test_process_document_group_completes_with_supported_backends(backend):
    document = DocumentFactory()
    CitationFactory(document=document)
    task_settings = {
        "default": {
            "BACKEND": backend,
            "QUEUES": [],
        }
    }

    with (
        override_settings(TASKS=task_settings),
        patch("my_app.services.text_extraction.TextExtractionService.perform"),
        patch(
            "my_app.services.figure_extraction_service.FigureExtractionService.perform"
        ),
    ):
        group = QueueProcessDocumentService(document).perform()
        if group.status == TaskGroup.Status.WAITING:
            call_command("run_database_tasks", verbosity=0)

    group.refresh_from_db()
    assert group.status == TaskGroup.Status.SUCCESSFUL
    assert group.results == {
        "text_extraction": None,
        "figure_extraction": None,
    }
    assert group.callback_task_result_id

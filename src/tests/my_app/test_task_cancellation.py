from unittest.mock import patch

from django.contrib.messages import get_messages
from django.test import override_settings
from django.urls import reverse

import pytest
from django_tasks_db.models import DBTaskResult
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    BulkWorkflowRequestFactory,
    CitationFactory,
    DocumentFactory,
    L1ScreeningQuestionOptionFactory,
    L1ScreeningResultFactory,
    ReviewFactory,
)
from my_app.models import (
    CancellationGeneration,
    ScreeningResultStatus,
    WorkflowStatus,
)
from my_app.services.bulk_workflow import check_bulk_workflow_result
from my_app.services.phase2_workflow import (
    QueueCitationWorkflowService,
    check_citation_workflow_result,
)
from my_app.services.process_document import QueueProcessDocumentService
from my_app.services.task_cancellation import (
    cancel_all_tasks,
    cancel_review_tasks,
)
from my_app.tasks.l1_screening import process_l1_screening_task


@pytest.mark.parametrize("global_scope", [False, True])
def test_task_cancellation_permissions_and_redirect(
    vanilla_client, global_scope
):
    review = ReviewFactory()
    if global_scope:
        url = reverse("cancel_all_tasks")
        return_url = reverse("review_list")
    else:
        url = reverse("cancel_review_tasks", args=[review.pk])
        return_url = reverse("review_detail", args=[review.pk])

    with patch_rules(is_admin=False, can_access_review=False):
        assert vanilla_client.get(url).status_code == 403
        assert vanilla_client.post(url).status_code == 403
    with patch_rules(is_admin=global_scope, can_access_review=True):
        assert vanilla_client.get(url).status_code == 200
        assert not CancellationGeneration.objects.exists()
        response = vanilla_client.post(url)

    assert response.status_code == 302
    assert response.url == return_url
    assert list(get_messages(response.wsgi_request))[0].level_tag == "success"
    cancellation = CancellationGeneration.objects.get()
    assert cancellation.review_id == (None if global_scope else review.pk)
    assert cancellation.created_at is not None


@override_settings(HAS_LLM=False)
def test_in_flight_initial_screening_finishes_but_critical_is_canceled(
    django_capture_on_commit_callbacks, run_database_tasks
):
    initial = L1ScreeningResultFactory()
    review = initial.citation.dataset.review
    L1ScreeningQuestionOptionFactory(question=initial.question)
    starting_cancellation = cancel_review_tasks(review)

    def screen(*args, **kwargs):
        cancel_review_tasks(review)
        return mock_screening(*args, **kwargs)

    from my_app.services.l1_screening import (
        get_l1_screening_results as mock_screening,
    )

    with patch(
        "my_app.services.l1_screening.get_l1_screening_results",
        side_effect=screen,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            process_l1_screening_task.call(
                result_id=initial.pk,
                cancellation_generation_id=starting_cancellation.pk,
            )
    initial.refresh_from_db()
    assert initial.status == ScreeningResultStatus.COMPLETED
    assert (
        DBTaskResult.objects.get().args_kwargs["kwargs"][
            "cancellation_generation_id"
        ]
        == starting_cancellation.pk
    )

    with patch(
        "my_app.services.critical_screening.ProcessL1CriticalScreeningService.perform"
    ) as critical:
        run_database_tasks()
        critical.assert_not_called()
    assert initial.critical_result.status == ScreeningResultStatus.ABANDONED


def test_review_and_global_cancellations_apply_to_older_workflows():
    review = ReviewFactory()
    other_review = ReviewFactory()
    older = BulkWorkflowRequestFactory(review=review)
    unrelated = BulkWorkflowRequestFactory(review=other_review)

    cancel_review_tasks(review)
    check_bulk_workflow_result(older.pk)
    older.refresh_from_db()
    unrelated.refresh_from_db()
    assert older.status == WorkflowStatus.CANCELED
    assert older.finished_at is not None
    assert unrelated.status == WorkflowStatus.PENDING

    citation = CitationFactory(dataset__review=review, doi="10.1000/test")
    newer = QueueCitationWorkflowService(
        citation, should_process_pdf=False, should_run_l2=False
    ).perform()
    with patch(
        "my_app.services.phase2_workflow.QueueDoiPdfService"
    ) as download:
        check_citation_workflow_result(newer.pk)
        assert (
            download.call_args.kwargs["cancellation_generation_id"]
            == newer.cancellation_generation_id
        )
        download.reset_mock()

        global_cancellation = cancel_all_tasks()
        assert global_cancellation.pk > newer.cancellation_generation_id
        check_citation_workflow_result(newer.pk)
        download.assert_not_called()

    check_bulk_workflow_result(unrelated.pk)
    newer.refresh_from_db()
    unrelated.refresh_from_db()
    assert newer.status == unrelated.status == WorkflowStatus.CANCELED


def test_shared_document_extractions_use_originating_review(
    django_capture_on_commit_callbacks, run_database_tasks
):
    document = DocumentFactory()
    origin = CitationFactory(document=document)
    other = CitationFactory(document=document)
    review = origin.dataset.review
    with (
        patch(
            "my_app.services.text_extraction.TextExtractionService.perform"
        ) as text,
        patch(
            "my_app.services.figure_extraction_service.FigureExtractionService.perform"
        ) as figures,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            text_result, figure_result = QueueProcessDocumentService(
                document, review_id=review.id
            ).perform()
        cancel_review_tasks(review)
        run_database_tasks()
        text.assert_not_called()
        figures.assert_not_called()
        text_result.refresh_from_db()
        figure_result.refresh_from_db()
        assert text_result.status == figure_result.status == "canceled"

        with django_capture_on_commit_callbacks(execute=True):
            QueueProcessDocumentService(
                document, review_id=other.dataset.review_id
            ).perform()
        # The first review's cancellation is scoped to that review.
        cancel_review_tasks(review)
        run_database_tasks()
        text.assert_called_once()
        figures.assert_called_once()

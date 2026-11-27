from datetime import timedelta
from functools import partial

from django.db import transaction
from django.tasks import default_task_backend
from django.utils import timezone

from proj.text import tdt
from proj.util import MissingPreconditionError

from my_app.models import (
    BulkWorkflowRequest,
    Citation,
    CitationStatus,
    L1ScreeningQuestion,
    Parameter,
    Review,
    ScreeningResultStatus,
    WorkflowStatus,
)
from my_app.services.l1_screening import EnqueueL1ScreeningService
from my_app.services.parameter_extraction import (
    EnqueueParameterExtractionService,
)
from my_app.services.task_cancellation import (
    current_cancellation_generation_id,
    task_was_canceled,
)
from my_app.services.workflow_scheduling import BULK_CHECK_PRIORITY

CHECK_INTERVAL = timedelta(seconds=5)
MAX_BULK_CITATIONS = 100


def bulk_checker_task(bulk, *, run_after=None):
    from my_app.tasks.bulk_workflow import check_bulk_workflow

    if bulk.phase == BulkWorkflowRequest.Phase.PARAMETERS:
        if run_after is None:
            return check_bulk_workflow
        return check_bulk_workflow.using(run_after=run_after)
    return check_bulk_workflow.using(
        priority=BULK_CHECK_PRIORITY, run_after=run_after
    )


def finish_request(request, status, error=""):
    request.status = status
    request.error = error
    request.finished_at = timezone.now()
    request.save(update_fields=["status", "error", "finished_at"])


def check_bulk_available(review, phase):
    # Called inside queue services' transactions to serialize submissions for a review.
    Review.objects.select_for_update().get(pk=review.pk)
    if BulkWorkflowRequest.objects.filter(
        review=review, phase=phase, status=WorkflowStatus.PENDING
    ).exists():
        raise MissingPreconditionError(
            tdt(
                "A bulk workflow for this phase is already pending for this review."
            )
        )


def screening_status(results):
    """Initial screening and its required critical review form one unit of work."""
    pending = False
    failed = False
    for result in results:
        if result.status == ScreeningResultStatus.ABANDONED:
            failed = True
        elif result.status != ScreeningResultStatus.COMPLETED:
            pending = True
        else:
            critical = getattr(result, "critical_result", None)
            if critical is None:
                pending = True
            elif critical.status == ScreeningResultStatus.ABANDONED:
                failed = True
            elif critical.status != ScreeningResultStatus.COMPLETED:
                pending = True
    if pending:
        return WorkflowStatus.PENDING
    if failed:
        return WorkflowStatus.FAILED
    return WorkflowStatus.COMPLETED


def parameter_status(results):
    statuses = {result.status for result in results}
    if statuses - {
        ScreeningResultStatus.COMPLETED,
        ScreeningResultStatus.ABANDONED,
    }:
        return WorkflowStatus.PENDING
    if ScreeningResultStatus.ABANDONED in statuses:
        return WorkflowStatus.FAILED
    return WorkflowStatus.COMPLETED


class QueueBulkResultsService:
    """Queue the independent citation/question or citation/parameter work for phases 1/3."""

    def __init__(self, review, phase, *, requested_by=None):
        self.review = review
        self.phase = phase
        self.requested_by = requested_by

    def perform(self):
        if self.phase not in (
            BulkWorkflowRequest.Phase.L1,
            BulkWorkflowRequest.Phase.PARAMETERS,
        ):
            raise ValueError("This service queues phase 1 or phase 3 results.")
        if not default_task_backend.supports_defer:
            raise MissingPreconditionError(
                tdt("Bulk workflows require a deferred task backend.")
            )
        with transaction.atomic():
            check_bulk_available(self.review, self.phase)
            citations = Citation.objects.filter(dataset__review=self.review)
            if self.phase == BulkWorkflowRequest.Phase.L1:
                questions = list(
                    L1ScreeningQuestion.active_objects.filter(
                        review=self.review,
                        disable_screening=False,
                    ).prefetch_related("options")
                )
                if not questions or any(
                    not any(
                        option.is_active for option in question.options.all()
                    )
                    for question in questions
                ):
                    raise MissingPreconditionError(
                        tdt(
                            "Configure L1 questions and options before starting the workflow."
                        )
                    )
                service = EnqueueL1ScreeningService
            else:
                citations = citations.add_l2_overall_status().filter(
                    l2_overall_status=CitationStatus.In
                )
                questions = list(
                    Parameter.active_objects.filter(review=self.review)
                )
                if not questions:
                    raise MissingPreconditionError(
                        tdt(
                            "Configure parameters before starting the workflow."
                        )
                    )
                service = EnqueueParameterExtractionService
            rows = list(
                citations.order_by("pk").select_for_update()[
                    :MAX_BULK_CITATIONS
                ]
            )
            bulk = BulkWorkflowRequest.objects.create(
                review=self.review,
                phase=self.phase,
                requested_by=self.requested_by,
                cancellation_generation_id=current_cancellation_generation_id(),
            )
            service(
                rows=rows,
                questions=questions,
                overwrite_existing=True,
                bulk_request=bulk,
            ).perform()
            transaction.on_commit(
                partial(bulk_checker_task(bulk).enqueue, request_id=bulk.pk)
            )
        return bulk


def check_bulk_workflow_result(request_id):
    with transaction.atomic():
        bulk = (
            BulkWorkflowRequest.objects.select_for_update()
            .filter(pk=request_id)
            .first()
        )
        if bulk is None or bulk.status != WorkflowStatus.PENDING:
            return
        if task_was_canceled(
            bulk.cancellation_generation_id, review_ids=[bulk.review_id]
        ):
            finish_request(bulk, WorkflowStatus.CANCELED)
            return
        if bulk.phase == BulkWorkflowRequest.Phase.L1:
            status = screening_status(
                bulk.l1_results.select_related("critical_result").only(
                    "status", "critical_result__status"
                )
            )
        elif bulk.phase == BulkWorkflowRequest.Phase.PARAMETERS:
            status = parameter_status(bulk.parameter_results.only("status"))
        else:
            children = bulk.citation_requests.all()
            status = WorkflowStatus.COMPLETED
            if children.filter(status=WorkflowStatus.PENDING).exists():
                status = WorkflowStatus.PENDING
            elif children.filter(
                status__in=[WorkflowStatus.FAILED, WorkflowStatus.CANCELED]
            ).exists():
                status = WorkflowStatus.FAILED
        if status == WorkflowStatus.PENDING:
            transaction.on_commit(
                partial(
                    bulk_checker_task(
                        bulk, run_after=timezone.now() + CHECK_INTERVAL
                    ).enqueue,
                    request_id=bulk.pk,
                )
            )
            return
        finish_request(bulk, status)

from django.conf import settings
from django.db import models
from django.db.models import Q

from proj.model_util import add_to_admin
from proj.text import tdt


class WorkflowStatus(models.TextChoices):
    PENDING = "pending", tdt("Pending")
    COMPLETED = "completed", tdt("Completed")
    FAILED = "failed", tdt("Failed")


class WorkflowRequest(models.Model):
    status = models.CharField(
        max_length=20,
        choices=WorkflowStatus.choices,
        default=WorkflowStatus.PENDING,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        abstract = True


@add_to_admin
class BulkWorkflowRequest(WorkflowRequest):
    class Phase(models.IntegerChoices):
        L1 = 1, tdt("Phase 1")
        L2 = 2, tdt("Phase 2")
        PARAMETERS = 3, tdt("Phase 3")

    phase = models.PositiveSmallIntegerField(
        choices=Phase.choices, default=Phase.L2
    )
    review = models.ForeignKey("my_app.Review", on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["review", "phase"],
                condition=Q(status=WorkflowStatus.PENDING),
                name="one_pending_bulk_workflow_per_phase",
            ),
        ]


@add_to_admin
class Phase2CitationWorkflowRequest(WorkflowRequest):
    class Process(models.TextChoices):
        NOT_STARTED = "not_started", tdt("Not started")
        DOWNLOAD_PDF = "download_pdf", tdt("PDF download")
        PROCESS_PDF = "process_pdf", tdt("PDF processing")
        L2 = "l2", tdt("L2 screening")

    citation = models.ForeignKey("my_app.Citation", on_delete=models.CASCADE)
    bulk_request = models.ForeignKey(
        BulkWorkflowRequest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="citation_requests",
    )
    should_download_pdf = models.BooleanField(default=True)
    should_process_pdf = models.BooleanField(default=True)
    should_run_l2 = models.BooleanField(default=True)
    current_process = models.CharField(
        max_length=20, choices=Process.choices, default=Process.NOT_STARTED
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["citation"],
                condition=Q(status=WorkflowStatus.PENDING),
                name="one_pending_workflow_per_citation",
            ),
        ]

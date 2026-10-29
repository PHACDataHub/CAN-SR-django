import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from phac_aspc.django import fields

from proj.model_util import add_to_admin
from proj.text import tdt


class PdfFromDOIStatus(models.TextChoices):
    PENDING = "pending", tdt("Pending")
    FULFILLED = "fulfilled", tdt("Fulfilled")
    FAILED = "failed", tdt("Failed")
    CANCELED = "canceled", tdt("Canceled")


@add_to_admin
class PdfFromDOIRequest(models.Model):
    Status = PdfFromDOIStatus

    citation = fields.OneToOneField(
        "my_app.Citation",
        related_name="pdf_from_doi_request",
        on_delete=models.CASCADE,
        verbose_name=tdt("Citation"),
    )
    requesting_user = fields.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name=tdt("Requesting user"),
    )
    request_dt = models.DateTimeField(default=timezone.now)
    updated_dt = models.DateTimeField(auto_now=True)
    selected_url = models.URLField(max_length=4096, null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=PdfFromDOIStatus.choices,
        default=PdfFromDOIStatus.PENDING,
    )
    error = models.TextField(blank=True)
    run_id = models.UUIDField(default=uuid.uuid4, editable=False)

    def __str__(self):
        return f"{self.citation_id} DOI PDF request: {self.status}"

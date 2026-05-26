from django.db import models

from phac_aspc.django import fields

from proj.model_util import add_to_admin, track_versions
from proj.models import User
from proj.text import tdt


@add_to_admin
class Document(models.Model):
    class Meta:
        ordering = ["-uploaded_at", "-id"]

    document_type = fields.CharField(
        max_length=100, verbose_name=tdt("Document type")
    )
    file = fields.FileField(
        upload_to="documents/", verbose_name=tdt("Document file")
    )
    source_url = fields.URLField(
        blank=True, null=True, verbose_name=tdt("Source URL")
    )
    uploaded_by = fields.ForeignKey(
        User,
        related_name="documents",
        on_delete=models.CASCADE,
        verbose_name=tdt("Associated user"),
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True, verbose_name=tdt("Upload date")
    )

    def __str__(self):
        return f"{self.document_type}: {self.file.name}"


@add_to_admin
class DocumentMetadata(models.Model):
    document = fields.OneToOneField(
        Document,
        related_name="document_metadata",
        on_delete=models.CASCADE,
        verbose_name=tdt("Document"),
    )
    pages = models.JSONField(default=dict, blank=True)
    coordinates = models.JSONField(default=dict, blank=True)
    raw_xml = models.TextField(blank=True, verbose_name=tdt("Raw XML"))

    def __str__(self):
        return f"{self.document_id} metadata"

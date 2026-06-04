from django.db import models

from phac_aspc.django import fields

from proj.model_util import add_to_admin, track_versions
from proj.text import tdt


@add_to_admin
class Document(models.Model):
    class Meta:
        ordering = ["-uploaded_at", "-id"]

    file = fields.FileField(
        upload_to="documents/", verbose_name=tdt("Document file")
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True, verbose_name=tdt("Upload date")
    )

    def __str__(self):
        return self.file.name


class DocumentProcessingStatus(models.TextChoices):
    NOT_STARTED = ("not_started", tdt("Not Started"))
    PENDING = ("pending", tdt("Pending"))
    COMPLETED = ("completed", tdt("Completed"))
    FAILED = ("failed", tdt("Failed"))


@add_to_admin
class DocumentMetadata(models.Model):
    DocumentProcessingStatus = DocumentProcessingStatus

    document = fields.OneToOneField(
        Document,
        related_name="document_metadata",
        on_delete=models.CASCADE,
        verbose_name=tdt("Document"),
    )
    status = models.CharField(
        max_length=20,
        choices=DocumentProcessingStatus.choices,
        default=DocumentProcessingStatus.PENDING,
        null=False,
    )
    pages = models.JSONField(default=dict, blank=True)
    coordinates = models.JSONField(default=dict, blank=True)
    raw_xml = models.TextField(blank=True, verbose_name=tdt("Raw XML"))

    def __str__(self):
        return f"{self.document_id} metadata"

    def get_sentence_list(self):
        coordinates = self.coordinates
        annotations = [
            a for a in coordinates if a.get("type") == "s" and a.get("text")
        ]
        full_text_arr = self._ordered_set([a["text"] for a in annotations])
        return full_text_arr

    def get_sentences(self):
        full_text_arr = self.get_sentence_list()
        full_text_str = "\n\n".join(
            [f"[{i}] {x}" for i, x in enumerate(full_text_arr)]
        )
        return full_text_str

    @staticmethod
    def _ordered_set(lst):
        # unique and preserve order
        return list(dict.fromkeys(lst))

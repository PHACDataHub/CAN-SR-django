from django.core.validators import MinValueValidator
from django.db import models

from phac_aspc.django import fields

from proj.model_util import add_to_admin
from proj.text import tdt

from my_app.pdf.text_extraction.sentences import (
    get_sentence_list,
    get_sentences,
)
from my_app.pdf.types import normalize_pdf_coordinates


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


class TextExtractionStatus(models.TextChoices):
    NOT_STARTED = ("not_started", tdt("Not Started"))
    PENDING = ("pending", tdt("Pending"))
    COMPLETED = ("completed", tdt("Completed"))
    FAILED = ("failed", tdt("Failed"))


class BoundingBoxJSONField(models.JSONField):
    def get_prep_value(self, value):
        return super().get_prep_value(normalize_pdf_coordinates(value))

    def validate(self, value, model_instance):
        super().validate(value, model_instance)
        normalize_pdf_coordinates(value)


class FigureExtractionStatus(models.TextChoices):
    NOT_STARTED = ("not_started", tdt("Not Started"))
    PENDING = ("pending", tdt("Pending"))
    COMPLETED = ("completed", tdt("Completed"))
    FAILED = ("failed", tdt("Failed"))


@add_to_admin
class TextExtractionResult(models.Model):
    TextExtractionStatus = TextExtractionStatus

    document = fields.OneToOneField(
        Document,
        related_name="text_extraction_result",
        on_delete=models.CASCADE,
        verbose_name=tdt("Document"),
    )
    status = models.CharField(
        max_length=20,
        choices=TextExtractionStatus.choices,
        default=TextExtractionStatus.PENDING,
        null=False,
    )
    pages = models.JSONField(default=dict, blank=True)
    coordinates = models.JSONField(default=dict, blank=True)
    raw_xml = models.TextField(blank=True, verbose_name=tdt("Raw XML"))

    def __str__(self):
        return f"{self.document_id} text extraction result"

    def get_sentence_list(self):
        return get_sentence_list(self.coordinates)

    def get_sentences(self):
        return get_sentences(self.coordinates)

    @staticmethod
    def _ordered_set(lst):
        # unique and preserve order
        return list(dict.fromkeys(lst))


class AbstractArtifact(models.Model):
    class Meta:
        abstract = True
        ordering = ["document_id", "index", "id"]

    document = fields.ForeignKey(
        Document,
        related_name="%(class)ss",
        on_delete=models.CASCADE,
        verbose_name=tdt("Document"),
    )
    caption = models.TextField(
        null=True, blank=True, verbose_name=tdt("Caption")
    )
    bounding_box = BoundingBoxJSONField(default=list, blank=True)
    description = models.TextField(
        null=True, blank=True, verbose_name=tdt("Description")
    )
    index = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name=tdt("Index"),
    )

    def __str__(self):
        return f"{self.document_id}: {self._meta.verbose_name} {self.index}"


@add_to_admin
class DocumentTable(AbstractArtifact):
    table_markdown = models.TextField(verbose_name=tdt("Table markdown"))


@add_to_admin
class DocumentFigure(AbstractArtifact):
    file = fields.FileField(
        upload_to="",
        blank=True,
        verbose_name=tdt("Figure file"),
    )


@add_to_admin
class FigureExtractionResult(models.Model):
    Status = FigureExtractionStatus

    document = fields.OneToOneField(
        Document,
        related_name="figure_extraction_result",
        on_delete=models.CASCADE,
        verbose_name=tdt("Document"),
    )
    status = models.CharField(
        max_length=20,
        choices=FigureExtractionStatus.choices,
        default=FigureExtractionStatus.PENDING,
        null=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.document_id} figure extraction: {self.status}"

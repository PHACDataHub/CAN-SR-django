from django.db import models

from phac_aspc.django import fields

from proj.model_util import add_to_admin
from proj.text import tdt

from .systematic_review import SystematicReview


@add_to_admin
class CitationDataset(models.Model):
    systematic_review = fields.ForeignKey(
        SystematicReview,
        related_name="citation_datasets",
        on_delete=models.CASCADE,
        verbose_name=tdt("Systematic review"),
    )

    def __str__(self):
        return f"{self.systematic_review_id} citation dataset"


@add_to_admin
class CitationDatasetColumn(models.Model):
    dataset = fields.ForeignKey(
        CitationDataset,
        related_name="columns",
        on_delete=models.CASCADE,
        verbose_name=tdt("Dataset"),
    )
    name = fields.CharField(max_length=255, verbose_name=tdt("Name"))

    def __str__(self):
        return self.name


@add_to_admin
class CitationDatasetRow(models.Model):
    class Meta:
        ordering = ["order", "id"]

    dataset = fields.ForeignKey(
        CitationDataset,
        related_name="rows",
        on_delete=models.CASCADE,
        verbose_name=tdt("Dataset"),
    )
    order = fields.IntegerField(verbose_name=tdt("Insertion order"))

    def __str__(self):
        return f"{self.dataset_id} row {self.order}"


@add_to_admin
class CitationDatasetCell(models.Model):
    row = fields.ForeignKey(
        CitationDatasetRow,
        related_name="cells",
        on_delete=models.CASCADE,
        verbose_name=tdt("Row"),
    )
    column = fields.ForeignKey(
        CitationDatasetColumn,
        related_name="cells",
        on_delete=models.CASCADE,
        verbose_name=tdt("Column"),
    )
    value = fields.CharField(max_length=1000, verbose_name=tdt("Value"))

    def __str__(self):
        return f"{self.row_id}:{self.column_id}"

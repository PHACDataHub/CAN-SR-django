from django.db import models
from phac_aspc.django import fields

from proj.model_util import add_to_admin
from proj.text import tdt

from .systematic_review import SystematicReview


@add_to_admin
class CitationDataset(models.Model):
    systematic_review = fields.OneToOneField(
        SystematicReview,
        related_name="citation_dataset",
        on_delete=models.CASCADE,
        verbose_name=tdt("Systematic review"),
    )

    screening_columns = fields.ManyToManyField(
        # columns to include in the L1 screening
        "my_app.CitationDatasetColumn",
        related_name="screening_column_selections",
        verbose_name=tdt("Columns to include in L1 screening"),
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
    title = fields.TextField(blank=True, default="", verbose_name=tdt("Title"))
    abstract = fields.TextField(
        blank=True, default="", verbose_name=tdt("Abstract")
    )
    data = models.JSONField(default=dict, blank=True, verbose_name=tdt("Data"))
    order = fields.IntegerField(verbose_name=tdt("Insertion order"))

    def __str__(self):
        return f"{self.dataset_id} row {self.order}"

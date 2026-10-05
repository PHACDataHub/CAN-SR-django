from django.db import models

from phac_aspc.django import fields

from proj.model_util import add_to_admin

from shortcuts import tdt

from .review import Review


@add_to_admin
class CitationDataset(models.Model):
    review = fields.OneToOneField(
        Review,
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
        return f"{self.review_id} citation dataset"


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

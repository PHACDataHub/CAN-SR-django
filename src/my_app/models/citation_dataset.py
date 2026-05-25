from django.db import models

from phac_aspc.django import fields

from proj.model_util import add_to_admin

from shortcuts import List, tdt

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


@add_to_admin
class Citation(models.Model):
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

    def serialize_for_prompt(self, columns: List[CitationDatasetColumn]):
        # could be used to flexibly include different columns in the prompt
        column_data = [
            (col.name, self.data.get(col.name, "")) for col in columns
        ]
        included_data = [
            ("Title", self.title),
            ("Abstract", self.abstract),
            *column_data,
        ]

        return "\n".join([f"{pair[0]}: {pair[1]}" for pair in included_data])

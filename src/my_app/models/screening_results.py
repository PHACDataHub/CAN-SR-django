from django.db import models

from phac_aspc.django import fields

from proj.model_util import add_to_admin
from proj.text import tdt

from .screening_criteria import (
    L1ScreeningQuestion,
    L2ScreeningQuestion,
    ParameterQuestion,
)
from .systematic_review import SystematicReview


class ScreeningResultStatus(models.TextChoices):
    # Screening is considered not-started if a result doesn't exist
    # i.e. not_started will never be in the DB
    # but this type is re-used elsewhere
    NOT_STARTED = "not_started"
    PENDING = "pending"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class CitationQueryResult(models.Model):
    class Meta:
        abstract = True

    citation = models.ForeignKey(
        "CitationDatasetRow", on_delete=models.CASCADE
    )

    # question =  models.ForeignKey(... override)
    # selected_option = models.ForeignKey(... override)

    status = models.CharField(
        max_length=20,
        choices=ScreeningResultStatus.choices,
        default=ScreeningResultStatus.PENDING,
        null=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    abandoned_at = models.DateTimeField(null=True, blank=True)

    confidence = models.FloatField(null=True, blank=True)
    explanation = models.TextField(null=True, blank=True)


class L1ScreeningResult(CitationQueryResult):
    question = models.ForeignKey(
        "L1ScreeningQuestion", on_delete=models.CASCADE
    )
    selected_option = models.ForeignKey(
        "L1ScreeningQuestionOption",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    class Meta:
        unique_together = ("citation", "question")


class L2ScreeningResult(CitationQueryResult):
    question = models.ForeignKey(
        "L2ScreeningQuestion", on_delete=models.CASCADE
    )
    selected_option = models.ForeignKey(
        "L2ScreeningQuestionOption",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    class Meta:
        unique_together = ("citation", "question")


class ParameterExtractionResult(CitationQueryResult):
    question = models.ForeignKey("ParameterQuestion", on_delete=models.CASCADE)
    selected_option = models.ForeignKey(
        "ParameterQuestionOption",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    class Meta:
        unique_together = ("citation", "question")

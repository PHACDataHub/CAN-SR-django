from django.conf import settings
from django.db import models

from phac_aspc.django import fields

from proj.model_util import add_to_admin
from proj.text import tdt

from .review import Review
from .screening_criteria import (
    L1ScreeningQuestion,
    L2ScreeningQuestion,
    ParameterCategory,
)


class ScreeningResultStatus(models.TextChoices):
    # Screening is considered not-started if a result doesn't exist
    # i.e. not_started will never be in the DB
    # but this type is re-used elsewhere
    NOT_STARTED = ("not_started", tdt("Not Started"))
    PENDING = ("pending", tdt("Pending"))
    COMPLETED = ("completed", tdt("Completed"))
    ABANDONED = ("abandoned", tdt("Abandoned"))


class CitationQueryResult(models.Model):
    class Meta:
        abstract = True

    citation = models.ForeignKey("Citation", on_delete=models.CASCADE)
    language_model = models.ForeignKey(
        "LanguageModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
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


class HumanValidatedScreeningResult(CitationQueryResult):
    class Meta:
        abstract = True

    human_validation_timestamp = models.DateTimeField(
        null=True,
        default=None,
        verbose_name=tdt("Human validation timestamp"),
    )
    human_validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=tdt("Human validated by"),
    )
    human_notes = models.TextField(
        null=True,
        blank=True,
        verbose_name=tdt("Human notes"),
    )


class L1ScreeningResult(HumanValidatedScreeningResult):
    question = models.ForeignKey(
        "L1ScreeningQuestion", on_delete=models.CASCADE
    )
    selected_option = models.ForeignKey(
        "L1ScreeningQuestionOption",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    human_selected_answer = models.ForeignKey(
        "L1ScreeningQuestionOption",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=tdt("Human selected answer"),
    )

    class Meta:
        unique_together = ("citation", "question")


class L2ScreeningResult(HumanValidatedScreeningResult):
    question = models.ForeignKey(
        "L2ScreeningQuestion", on_delete=models.CASCADE
    )
    selected_option = models.ForeignKey(
        "L2ScreeningQuestionOption",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    human_selected_answer = models.ForeignKey(
        "L2ScreeningQuestionOption",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=tdt("Human selected answer"),
    )

    evidence_sentences = models.JSONField(
        default=list,
        blank=True,
    )
    evidence_tables = models.JSONField(
        default=list,
        blank=True,
    )
    evidence_figures = models.JSONField(
        default=list,
        blank=True,
    )

    class Meta:
        unique_together = ("citation", "question")


class ParameterExtractionResult(CitationQueryResult):
    question = models.ForeignKey("Parameter", on_delete=models.CASCADE)
    found = models.BooleanField(default=False)
    value = models.TextField(null=True, blank=True)
    explanation = models.TextField(null=True, blank=True)
    evidence_sentences = models.JSONField(
        default=list,
        blank=True,
    )
    evidence_tables = models.JSONField(
        default=list,
        blank=True,
    )
    evidence_figures = models.JSONField(
        default=list,
        blank=True,
    )

    class Meta:
        unique_together = ("citation", "question")

from django.db import models

from phac_aspc.django import fields

from proj.model_util import add_to_admin
from proj.text import tdt

from .review import Review


class AbstractScreeningQuestion(models.Model):
    class Meta:
        abstract = True

    question_text = fields.TextField(verbose_name=tdt("Question text"))

    def __str__(self):
        return self.question_text

    @property
    def title(self):
        return self.question_text


@add_to_admin
class L1ScreeningQuestion(AbstractScreeningQuestion):
    review = fields.ForeignKey(
        Review,
        related_name="l1_screening_questions",
        on_delete=models.CASCADE,
        verbose_name=tdt("Systematic review"),
    )


@add_to_admin
class L2ScreeningQuestion(AbstractScreeningQuestion):
    review = fields.ForeignKey(
        Review,
        related_name="l2_screening_questions",
        on_delete=models.CASCADE,
        verbose_name=tdt("Systematic review"),
    )


SCREENED_IN = "screen_id"
SCREENED_OUT = "screen_out"
SCREENING_DISABLED = "screening_disabled"


class ScreeningActions(models.TextChoices):
    ScreenIn = (SCREENED_IN, "Screen In")
    ScreenOut = (SCREENED_OUT, "Screen Out")
    ScreeningDisabled = (
        SCREENING_DISABLED,
        "Don't use this question to filter citations",
    )


class AbstractScreeningQuestionOption(models.Model):
    class Meta:
        abstract = True

    option_text = fields.CharField(
        # this is the high level label,
        # e.g. 'yes', 'yes, primary research',
        max_length=255,
        verbose_name=tdt("Option text"),
    )
    option_value = fields.TextField(verbose_name=tdt("Option value"))

    screening_action = fields.CharField(
        max_length=255,
        null=False,
        default=ScreeningActions.ScreeningDisabled,
        choices=ScreeningActions.choices,
    )

    def __str__(self):
        return self.option_text

    @property
    def title(self):
        return self.option_text

    @property
    def description(self):
        return self.option_value


class L1ScreeningQuestionOption(AbstractScreeningQuestionOption):
    question = fields.ForeignKey(
        L1ScreeningQuestion,
        related_name="options",
        on_delete=models.CASCADE,
        verbose_name=tdt("Screening question"),
    )


class L2ScreeningQuestionOption(AbstractScreeningQuestionOption):
    question = fields.ForeignKey(
        L2ScreeningQuestion,
        related_name="options",
        on_delete=models.CASCADE,
        verbose_name=tdt("Screening question"),
    )


@add_to_admin
class Parameter(models.Model):
    class OptionType(models.TextChoices):
        FREE_TEXT = ("free_text", tdt("Free text"))
        SELECT = ("select", tdt("Select from list"))

    review = fields.ForeignKey(
        Review,
        related_name="parameters",
        on_delete=models.CASCADE,
        verbose_name=tdt("Systematic review"),
    )
    name = fields.CharField(max_length=255, verbose_name=tdt("Parameter name"))
    description = fields.TextField(verbose_name=tdt("Parameter description"))
    option_type = fields.CharField(
        max_length=20,
        choices=OptionType.choices,
        default=OptionType.FREE_TEXT,
        verbose_name=tdt("Answer type"),
    )
    units_and_reporting_instructions = fields.TextField(
        blank=True,
        default="",
        verbose_name=tdt("Units and reporting instructions"),
    )
    calculation_instructions = fields.TextField(
        blank=True,
        default="",
        verbose_name=tdt("Calculation instructions"),
    )

    def __str__(self):
        return self.name

    @property
    def title(self):
        return self.name


@add_to_admin
class ParameterOption(models.Model):
    parameter = fields.ForeignKey(
        Parameter,
        related_name="options",
        on_delete=models.CASCADE,
        verbose_name=tdt("Parameter"),
    )
    name = fields.CharField(max_length=255, verbose_name=tdt("Option name"))
    context = fields.TextField(
        blank=True,
        default="",
        verbose_name=tdt("Context or guidance"),
    )

    def __str__(self):
        return self.name

    @property
    def title(self):
        return self.name

    @property
    def description(self):
        return self.context

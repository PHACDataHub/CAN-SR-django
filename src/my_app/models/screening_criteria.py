from django.db import models

from phac_aspc.django import fields

from proj.model_util import add_to_admin
from proj.text import tdt

from .systematic_review import SystematicReview


class ScreeningType(models.TextChoices):
    L1 = "L1", tdt("Level 1")
    L2 = "L2", tdt("Level 2")


@add_to_admin
class ScreeningQuestion(models.Model):
    ScreeningType = ScreeningType

    review = fields.ForeignKey(
        SystematicReview,
        related_name="screening_questions",
        on_delete=models.CASCADE,
        verbose_name=tdt("Systematic review"),
    )
    screening_type = models.CharField(
        max_length=2,
        choices=ScreeningType.choices,
        verbose_name=tdt("Screening type"),
    )
    question_text = fields.TextField(verbose_name=tdt("Question text"))

    def __str__(self):
        return f"{self.review_id} {self.screening_type}"


@add_to_admin
class ScreeningQuestionOption(models.Model):

    question = fields.ForeignKey(
        ScreeningQuestion,
        related_name="options",
        on_delete=models.CASCADE,
        verbose_name=tdt("Question"),
    )
    option_text = fields.CharField(
        max_length=255, verbose_name=tdt("Option text")
    )
    option_value = fields.TextField(verbose_name=tdt("Option value"))

    def __str__(self):
        return self.option_text


@add_to_admin
class ParameterQuestion(models.Model):
    review = fields.ForeignKey(
        SystematicReview,
        related_name="parameter_questions",
        on_delete=models.CASCADE,
        verbose_name=tdt("Systematic review"),
    )
    question_text = fields.TextField(verbose_name=tdt("Question text"))

    def __str__(self):
        return f"{self.review_id} parameter question"


@add_to_admin
class ParameterQuestionOption(models.Model):
    question = fields.ForeignKey(
        ParameterQuestion,
        related_name="options",
        on_delete=models.CASCADE,
        verbose_name=tdt("Question"),
    )
    param_name = fields.CharField(
        max_length=255, verbose_name=tdt("Parameter name")
    )
    param_description = fields.TextField(
        verbose_name=tdt("Parameter description")
    )

    def __str__(self):
        return self.param_name

from django.db import models

from phac_aspc.django import fields

from proj.model_util import add_to_admin
from proj.text import tdt

from .systematic_review import SystematicReview


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
        SystematicReview,
        related_name="l1_screening_questions",
        on_delete=models.CASCADE,
        verbose_name=tdt("Systematic review"),
    )


@add_to_admin
class L2ScreeningQuestion(AbstractScreeningQuestion):
    review = fields.ForeignKey(
        SystematicReview,
        related_name="l2_screening_questions",
        on_delete=models.CASCADE,
        verbose_name=tdt("Systematic review"),
    )


class AbstractScreeningQuestionOption(models.Model):
    class Meta:
        abstract = True

    option_text = fields.CharField(
        max_length=255, verbose_name=tdt("Option text")
    )
    option_value = fields.TextField(verbose_name=tdt("Option value"))

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
class ParameterQuestion(models.Model):
    review = fields.ForeignKey(
        SystematicReview,
        related_name="parameter_questions",
        on_delete=models.CASCADE,
        verbose_name=tdt("Systematic review"),
    )
    question_text = fields.TextField(verbose_name=tdt("Parameter question"))

    def __str__(self):
        return f"{self.review_id} parameter question"

    @property
    def title(self):
        return self.question_text


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

    @property
    def title(self):
        return self.param_name

    @property
    def description(self):
        return self.param_description

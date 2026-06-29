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
class ParameterCategory(models.Model):
    review = fields.ForeignKey(
        Review,
        related_name="parameter_categories",
        on_delete=models.CASCADE,
        verbose_name=tdt("Systematic review"),
    )
    name = fields.CharField(
        max_length=255, verbose_name=tdt("Parameter category name")
    )

    def __str__(self):
        return self.name

    @property
    def title(self):
        return self.name


@add_to_admin
class Parameter(models.Model):
    category = fields.ForeignKey(
        ParameterCategory,
        related_name="parameters",
        on_delete=models.CASCADE,
        verbose_name=tdt("Parameter category"),
    )
    name = fields.CharField(max_length=255, verbose_name=tdt("Parameter name"))
    description = fields.TextField(verbose_name=tdt("Parameter description"))

    def __str__(self):
        return self.name

    @property
    def title(self):
        return self.name

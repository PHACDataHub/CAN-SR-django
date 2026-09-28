from django.db import models

from phac_aspc.django import fields

from proj.model_util import SoftDeleteMixin, add_to_admin
from proj.text import tdt

from .review import Review


class AbstractScreeningQuestion(SoftDeleteMixin, models.Model):
    class Meta:
        abstract = True

    question_text = fields.TextField(verbose_name=tdt("Question text"))
    disable_screening = fields.BooleanField(
        default=False,
        verbose_name=tdt("Disable screening"),
        help_text=tdt("Don't use this question's results to filter citations"),
    )

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

    def sync_to_l2(self):
        question, _ = L2ScreeningQuestion.objects.update_or_create(
            l1_question=self,
            defaults={
                "review": self.review,
                "question_text": self.question_text,
                "disable_screening": self.disable_screening,
                "deletion_time": self.deletion_time,
            },
        )
        return question

    def soft_delete(self):
        super().soft_delete()
        mirrored_questions = L2ScreeningQuestion.objects.filter(
            l1_question=self
        )
        for question in mirrored_questions:
            question.soft_delete()


@add_to_admin
class L2ScreeningQuestion(AbstractScreeningQuestion):
    l1_question = fields.ForeignKey(
        # When this is set, the L2 questions is a
        # 'redundant' or 'mirrored' question
        # hidden from forms, and automatically managed based on the L1 question
        L1ScreeningQuestion,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="l2_copies",
    )
    review = fields.ForeignKey(
        Review,
        related_name="l2_screening_questions",
        on_delete=models.CASCADE,
        verbose_name=tdt("Systematic review"),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["l1_question"], name="unique_l2_l1_question"
            )
        ]


SCREENED_IN = "screen_in"
SCREENED_OUT = "screen_out"


class ScreeningActions(models.TextChoices):
    ScreenIn = (SCREENED_IN, "Screen In")
    ScreenOut = (SCREENED_OUT, "Screen Out")


class AbstractScreeningQuestionOption(
    SoftDeleteMixin,
    models.Model,
):
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
        default=ScreeningActions.ScreenIn,
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

    def sync_to_l2(self):
        l2_question = L2ScreeningQuestion.objects.get(
            l1_question=self.question
        )
        option, _ = L2ScreeningQuestionOption.objects.update_or_create(
            l1_option=self,
            defaults={
                "question": l2_question,
                "option_text": self.option_text,
                "option_value": self.option_value,
                "screening_action": self.screening_action,
                "deletion_time": self.deletion_time,
            },
        )
        return option

    def soft_delete(self):
        super().soft_delete()
        mirrored_options = L2ScreeningQuestionOption.objects.filter(
            l1_option=self
        )
        for option in mirrored_options:
            option.soft_delete()


class L2ScreeningQuestionOption(AbstractScreeningQuestionOption):
    l1_option = fields.ForeignKey(
        # like the parent question, when this is set, the option mirrors
        # an L1 option, and will be hidden from forms, managed automatically
        L1ScreeningQuestionOption,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="l2_copies",
    )
    question = fields.ForeignKey(
        L2ScreeningQuestion,
        related_name="options",
        on_delete=models.CASCADE,
        verbose_name=tdt("Screening question"),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["l1_option"], name="unique_l2_l1_option"
            )
        ]


@add_to_admin
class Parameter(SoftDeleteMixin, models.Model):
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
class ParameterOption(SoftDeleteMixin, models.Model):
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

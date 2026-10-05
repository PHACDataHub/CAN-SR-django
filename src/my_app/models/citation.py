from django.db import models
from django.db.models import Exists, F, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from phac_aspc.django import fields

from proj.model_util import add_to_admin

from my_app.constants import DEFAULT_CONFIDENCE
from shortcuts import List, tdt

from .citation_dataset import CitationDataset, CitationDatasetColumn
from .screening_criteria import (
    L1ScreeningQuestion,
    L2ScreeningQuestion,
    ScreeningActions,
)
from .screening_results import (
    L1HumanAnswer,
    L1ScreeningResult,
    L2HumanAnswer,
    L2ScreeningResult,
    ScreeningResultStatus,
)


class CitationAIStatus(models.TextChoices):
    NotScreenedYet = ("not_screened_yet", tdt("Not screened yet"))
    AutoExcluded = ("auto_excluded", tdt("Auto excluded"))
    ConfidentlyIncluded = (
        "confidently_included",
        tdt("Confidently included"),
    )
    AmbiguouslyIncluded = (
        "ambiguously_included",
        tdt("Ambiguously included"),
    )


class CitationHumanStatus(models.TextChoices):
    In = ("in", tdt("In"))
    Out = ("out", tdt("Out"))
    Unanswered = ("unanswered", tdt("Unanswered"))


class CitationStatus(models.TextChoices):
    In = ("in", tdt("In"))
    Out = ("out", tdt("Out"))
    Unanswered = ("unanswered", tdt("Unanswered"))
    Ambiguous = ("ambiguous", tdt("Ambiguous"))


class CitationQuerySet(models.QuerySet):
    def _annotate_stage_overall_status(
        self, question_model, answer_model, result_model, field_name
    ):
        active_questions = question_model.objects.filter(
            review_id=OuterRef("dataset__review_id"),
            deletion_time__isnull=True,
            disable_screening=False,
        )
        latest_answer = answer_model.objects.filter(
            citation_id=OuterRef("citation_id"),
            question_id=OuterRef("question_id"),
        ).order_by("-updated_at", "-id")
        human_answers = answer_model.objects.filter(
            citation_id=OuterRef(OuterRef("pk")),
            question_id=OuterRef("pk"),
        )
        valid_human_answers = human_answers.filter(
            pk=Subquery(latest_answer.values("pk")[:1]),
            selected_option__deletion_time__isnull=True,
            selected_option__question_id=F("question_id"),
        )
        ai_answers = result_model.objects.filter(
            citation_id=OuterRef(OuterRef("pk")),
            question_id=OuterRef("pk"),
        )
        threshold = Coalesce(
            F("question__confidence"),
            F("question__review__confidence"),
            Value(DEFAULT_CONFIDENCE),
        )
        confident_ai_answers = ai_answers.filter(
            status=ScreeningResultStatus.COMPLETED,
            confidence__gte=threshold,
            selected_option__deletion_time__isnull=True,
            selected_option__question_id=F("question_id"),
            critical_result__status=ScreeningResultStatus.COMPLETED,
            critical_result__confidence__gte=threshold,
            critical_result__selected_option__isnull=True,
        )
        human_in = Exists(
            valid_human_answers.filter(
                selected_option__screening_action=ScreeningActions.ScreenIn
            )
        )
        human_out = Exists(
            valid_human_answers.filter(
                selected_option__screening_action=ScreeningActions.ScreenOut
            )
        )
        ai_in = Exists(
            confident_ai_answers.filter(
                selected_option__screening_action=ScreeningActions.ScreenIn
            )
        )
        ai_out = Exists(
            confident_ai_answers.filter(
                selected_option__screening_action=ScreeningActions.ScreenOut
            )
        )
        excluded_questions = active_questions.filter(
            human_out | (ai_out & ~human_in)
        )
        questions_without_inclusion = active_questions.filter(
            ~(human_in | (ai_in & ~human_out))
        )
        answered_questions = active_questions.filter(
            Exists(human_answers) | Exists(ai_answers)
        )
        return self.annotate(
            **{
                field_name: models.Case(
                    models.When(
                        Exists(excluded_questions),
                        then=Value(CitationStatus.Out),
                    ),
                    models.When(
                        ~Exists(answered_questions),
                        then=Value(CitationStatus.Unanswered),
                    ),
                    models.When(
                        ~Exists(questions_without_inclusion),
                        then=Value(CitationStatus.In),
                    ),
                    default=Value(CitationStatus.Ambiguous),
                    output_field=models.CharField(),
                )
            }
        )

    def add_l1_overall_status(self):
        return self._annotate_stage_overall_status(
            L1ScreeningQuestion,
            L1HumanAnswer,
            L1ScreeningResult,
            "l1_overall_status",
        )

    def add_l2_overall_status(self):
        return self._annotate_stage_overall_status(
            L2ScreeningQuestion,
            L2HumanAnswer,
            L2ScreeningResult,
            "l2_overall_status",
        )

    def _annotate_stage_human_status(
        self, question_model, answer_model, field_name
    ):
        active_questions = question_model.objects.filter(
            review_id=OuterRef("dataset__review_id"),
            deletion_time__isnull=True,
            disable_screening=False,
        )
        latest_answer = answer_model.objects.filter(
            citation_id=OuterRef("citation_id"),
            question_id=OuterRef("question_id"),
        ).order_by("-updated_at", "-id")
        valid_answers = answer_model.objects.filter(
            citation_id=OuterRef(OuterRef("pk")),
            question_id=OuterRef("pk"),
            pk=Subquery(latest_answer.values("pk")[:1]),
            selected_option__deletion_time__isnull=True,
            selected_option__question_id=F("question_id"),
        )
        excluded_questions = active_questions.filter(
            Exists(
                valid_answers.filter(
                    selected_option__screening_action=ScreeningActions.ScreenOut
                )
            )
        )
        unanswered_questions = active_questions.filter(
            ~Exists(
                valid_answers.filter(
                    selected_option__screening_action=ScreeningActions.ScreenIn
                )
            )
        )
        return self.annotate(
            **{
                field_name: models.Case(
                    models.When(
                        Exists(excluded_questions),
                        then=Value(CitationHumanStatus.Out),
                    ),
                    models.When(
                        ~Exists(active_questions)
                        | Exists(unanswered_questions),
                        then=Value(CitationHumanStatus.Unanswered),
                    ),
                    default=Value(CitationHumanStatus.In),
                    output_field=models.CharField(),
                )
            }
        )

    def add_l1_human_status(self):
        return self._annotate_stage_human_status(
            L1ScreeningQuestion, L1HumanAnswer, "l1_human_status"
        )

    def add_l2_human_status(self):
        return self._annotate_stage_human_status(
            L2ScreeningQuestion, L2HumanAnswer, "l2_human_status"
        )

    def _annotate_stage_ai_status(
        self, question_model, result_model, field_name
    ):
        active_questions = question_model.objects.filter(
            review_id=OuterRef("dataset__review_id"),
            deletion_time__isnull=True,
            disable_screening=False,
        )
        threshold = Coalesce(
            F("question__confidence"),
            F("question__review__confidence"),
            Value(DEFAULT_CONFIDENCE),
        )
        results = result_model.objects.filter(
            citation_id=OuterRef("pk"),
            question__review_id=F("citation__dataset__review_id"),
            question__deletion_time__isnull=True,
            question__disable_screening=False,
        ).alias(confidence_threshold=threshold)
        confident_results = results.filter(
            status=ScreeningResultStatus.COMPLETED,
            confidence__gte=F("confidence_threshold"),
            selected_option__deletion_time__isnull=True,
            selected_option__question_id=F("question_id"),
            critical_result__status=ScreeningResultStatus.COMPLETED,
            critical_result__confidence__gte=F("confidence_threshold"),
            critical_result__selected_option__isnull=True,
        )
        auto_excluded = confident_results.filter(
            selected_option__screening_action=ScreeningActions.ScreenOut
        )

        question_results = result_model.objects.filter(
            citation_id=OuterRef(OuterRef("pk")),
            question_id=OuterRef("pk"),
        )
        unfinished_questions = active_questions.filter(
            ~Exists(question_results)
        )
        pending_results = results.filter(
            status__in=[
                ScreeningResultStatus.PENDING,
                ScreeningResultStatus.NOT_STARTED,
            ]
        )
        confident_inclusions = question_results.filter(
            status=ScreeningResultStatus.COMPLETED,
            confidence__gte=threshold,
            selected_option__deletion_time__isnull=True,
            selected_option__question_id=F("question_id"),
            selected_option__screening_action=ScreeningActions.ScreenIn,
            critical_result__status=ScreeningResultStatus.COMPLETED,
            critical_result__confidence__gte=threshold,
            critical_result__selected_option__isnull=True,
        )
        questions_without_confident_inclusion = active_questions.filter(
            ~Exists(confident_inclusions)
        )

        return self.annotate(
            **{
                field_name: models.Case(
                    models.When(
                        Exists(auto_excluded),
                        then=Value(CitationAIStatus.AutoExcluded),
                    ),
                    models.When(
                        ~Exists(active_questions),
                        then=Value(CitationAIStatus.NotScreenedYet),
                    ),
                    models.When(
                        Exists(unfinished_questions) | Exists(pending_results),
                        then=Value(CitationAIStatus.NotScreenedYet),
                    ),
                    models.When(
                        ~Exists(questions_without_confident_inclusion),
                        then=Value(CitationAIStatus.ConfidentlyIncluded),
                    ),
                    default=Value(CitationAIStatus.AmbiguouslyIncluded),
                    output_field=models.CharField(),
                )
            }
        )

    def add_l1_ai_status(self):
        return self._annotate_stage_ai_status(
            L1ScreeningQuestion, L1ScreeningResult, "l1_ai_status"
        )

    def add_l2_ai_status(self):
        return self._annotate_stage_ai_status(
            L2ScreeningQuestion, L2ScreeningResult, "l2_ai_status"
        )


class CitationManager(models.Manager.from_queryset(CitationQuerySet)):
    pass


@add_to_admin
class Citation(models.Model):
    objects = CitationManager()

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

    document = fields.ForeignKey(
        "my_app.Document",
        related_name="citations",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=tdt("Linked document"),
    )

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

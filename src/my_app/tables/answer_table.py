from typing import Literal

from django.db.models import OuterRef, Subquery

from proj.text import tdt

from my_app.models import Citation, ScreeningResultStatus

from .common import (
    AnnotateCitationStatuses,
    DetailColumn,
    QuestionColumn,
    ReviewTableDef,
    StatusColumns,
)
from .table_framework import (
    AbbreviatedAttributeColumn,
    AttributeColumn,
    ChoiceAttributeColumn,
    NumericAttributeColumn,
)


class AnswerTableDef(ReviewTableDef):
    stage: Literal["l1", "l2"] = None
    result_model = None
    answer_model = None
    model = None
    default_ordering = ("citation_id", "question_id", "pk")

    def get_columns(self):
        return [
            AttributeColumn("id", tdt("Answer ID"), sort_field="pk"),
            AttributeColumn(
                "citation_id", tdt("Citation ID"), sort_field="citation_id"
            ),
            AbbreviatedAttributeColumn(
                "title",
                tdt("Title"),
                attribute="citation.title",
                sort_field="citation__title",
            ),
            AbbreviatedAttributeColumn(
                "abstract",
                tdt("Abstract"),
                attribute="citation.abstract",
                default_enabled=False,
            ),
            QuestionColumn(stage=self.stage),
            *self.answer_columns(),
            *StatusColumns(stage=self.stage, attribute_prefix=""),
            DetailColumn(stage=self.stage),
        ]

    def answer_columns(self):
        raise NotImplementedError

    def ai_columns(self, prefix=""):
        return [
            ChoiceAttributeColumn(
                "job_status",
                tdt("AI job status"),
                attribute=f"{prefix}status",
                choices=ScreeningResultStatus,
            ),
            AttributeColumn(
                "ai_answer",
                tdt("AI answer"),
                attribute=f"{prefix}selected_option.option_text",
            ),
            NumericAttributeColumn(
                "ai_confidence",
                tdt("AI confidence"),
                attribute=f"{prefix}confidence",
            ),
            AbbreviatedAttributeColumn(
                "ai_explanation",
                tdt("AI explanation"),
                attribute=f"{prefix}explanation",
            ),
            ChoiceAttributeColumn(
                "critical_status",
                tdt("Critical-agent job status"),
                attribute=f"{prefix}critical_result.status",
                choices=ScreeningResultStatus,
            ),
            AttributeColumn(
                "critical_answer",
                tdt("Critical-agent answer"),
                attribute=f"{prefix}critical_result.selected_option.option_text",
            ),
            NumericAttributeColumn(
                "critical_confidence",
                tdt("Critical-agent confidence"),
                attribute=f"{prefix}critical_result.confidence",
            ),
            AttributeColumn(
                "critical_error",
                tdt("Critical-agent error"),
                attribute=f"{prefix}critical_result.error",
                default_enabled=False,
            ),
        ]

    def human_columns(self, prefix=""):
        return [
            AttributeColumn(
                "human_answer",
                tdt("Human answer"),
                attribute=f"{prefix}selected_option.option_text",
            ),
            AttributeColumn(
                "human_user", tdt("Answered by"), attribute=f"{prefix}user"
            ),
            AbbreviatedAttributeColumn(
                "human_notes", tdt("Human notes"), attribute=f"{prefix}notes"
            ),
        ]

    def get_base_queryset(self):
        return self.model.objects.filter(
            citation__dataset__review=self.review,
            question__review=self.review,
        ).select_related("citation", "question", "selected_option")

    def annotate_queryset(self, queryset):
        keys = {column.key for column in self.enabled_columns}
        citations = AnnotateCitationStatuses(
            Citation.objects.filter(pk=OuterRef("citation_id")), keys
        )
        return queryset.annotate(
            **{
                column.key: Subquery(citations.values(column.key)[:1])
                for column in self.enabled_columns
                if column.key.endswith("_status")
                and column.key.startswith(("l1_", "l2_"))
            }
        )

    def prepare_page(self, records):
        if not records:
            return
        citation_ids = {record.citation_id for record in records}
        question_ids = {record.question_id for record in records}
        results = {
            (result.citation_id, result.question_id): result
            for result in self.result_model.objects.filter(
                citation_id__in=citation_ids,
                question_id__in=question_ids,
            ).select_related(
                "selected_option", "critical_result__selected_option"
            )
        }
        # As in citation status calculations, display the latest human answer per pair.
        answers = {}
        for answer in (
            self.answer_model.objects.filter(
                citation_id__in=citation_ids,
                question_id__in=question_ids,
            )
            .select_related("selected_option", "user")
            .order_by("updated_at", "pk")
        ):
            answers[(answer.citation_id, answer.question_id)] = answer
        for record in records:
            pair = (record.citation_id, record.question_id)
            record.table_ai = results.get(pair)
            record.table_human = answers.get(pair)

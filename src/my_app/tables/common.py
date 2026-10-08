from dataclasses import dataclass
from typing import Literal

from django import forms

import htpy as h

from proj.form_util import StandardFormMixin
from proj.text import tdt

from my_app.models import (
    CitationAIStatus,
    CitationDatasetColumn,
    CitationHumanStatus,
    CitationStatus,
    L1ScreeningQuestion,
    L2ScreeningQuestion,
)
from my_app.queries import get_review_from_context
from shortcuts import reverse

from .table_framework import (
    AttributeColumn,
    ChoiceAttributeColumn,
    Column,
    TableDef,
)


class StatusFilterForm(StandardFormMixin, forms.Form):
    status = forms.ChoiceField(label=tdt("Status"), required=False)


@dataclass
class CitationStatusColumn(ChoiceAttributeColumn):
    filter_form_class: type = StatusFilterForm

    def get_filter_form(self, data=None):
        form = super().get_filter_form(data)
        form.fields["status"].label = self.render_plaintext_header()
        form.fields["status"].choices = [
            ("", tdt("All statuses")),
            *self.choices.choices,
        ]
        return form

    def filter_queryset(self, queryset, cleaned_data):
        if cleaned_data["status"]:
            return queryset.filter(**{self.key: cleaned_data["status"]})
        return queryset


def StatusColumns(*, stage=None, attribute_prefix="", filters=False):
    stages = [stage]
    if stage is None:
        stages = ["l1", "l2"]
    column_class = ChoiceAttributeColumn
    if filters:
        column_class = CitationStatusColumn
    return [
        column_class(
            key=f"{level}_{kind}_status",
            header=header,
            attribute=f"{attribute_prefix}{level}_{kind}_status",
            sort_field=f"{level}_{kind}_status",
            choices=choices,
        )
        for level in stages
        for kind, header, choices in (
            ("ai", tdt(f"{level.upper()} AI status"), CitationAIStatus),
            (
                "human",
                tdt(f"{level.upper()} human status"),
                CitationHumanStatus,
            ),
            (
                "overall",
                tdt(f"{level.upper()} overall status"),
                CitationStatus,
            ),
        )
    ]


def AnnotateCitationStatuses(queryset, keys):
    for key in keys:
        if key in {
            "l1_ai_status",
            "l1_human_status",
            "l1_overall_status",
            "l2_ai_status",
            "l2_human_status",
            "l2_overall_status",
        }:
            queryset = getattr(queryset, f"add_{key}")()
    return queryset


@dataclass
class GetJsonDataColumn(Column):
    data_key: str = ""
    attribute: str = "data"
    default_enabled: bool = False

    def render_cell(self, record):
        for part in self.attribute.split("."):
            record = getattr(record, part)
        value = record.get(self.data_key)
        if value is None:
            return ""
        return str(value)


class ReviewTableDef(TableDef):
    def __init__(self, *, review, **kwargs):
        self.review = review
        super().__init__(**kwargs)

    def dataset_columns(self, *, attribute="data"):
        return [
            GetJsonDataColumn(
                key=f"dataset_{column.pk}",
                header=column.name,
                data_key=column.name,
                attribute=attribute,
            )
            for column in CitationDatasetColumn.objects.filter(
                dataset__review=self.review
            ).order_by("pk")
        ]


@dataclass
class DetailColumn(Column):
    key: str = "view"
    header: object = tdt("Details")
    disableable: bool = False
    exportable: bool = False
    stage: str = None

    def render_cell(self, record):
        if self.stage == "l1":
            url = reverse(
                "l1_answer_detail_modal",
                args=[record.citation_id, record.question_id],
            )
        elif self.stage == "l2":
            url = reverse(
                "l2_answer_detail_modal",
                args=[record.citation_id, record.question_id],
            )
        else:
            url = reverse("citation_detail_modal", args=[record.pk])
        return h.button(
            ".btn.btn-outline-primary.btn-sm",
            type="button",
            hx_get=url,
            hx_target="#modal-slot",
            hx_swap="innerHTML",
        )[tdt("View")]


@dataclass(kw_only=True)
class QuestionColumn(AttributeColumn):
    stage: Literal["l1", "l2"]
    key: str = "question"
    header: object = tdt("Question")
    attribute: str = "question.question_text"
    sort_field: str = "question__question_text"

    class L1QuestionSelectionForm(StandardFormMixin, forms.Form):
        question = forms.ModelChoiceField(
            queryset=L1ScreeningQuestion.objects.all(),
            required=False,
            label=tdt("Question"),
        )

    class L2QuestionSelectionForm(StandardFormMixin, forms.Form):
        question = forms.ModelChoiceField(
            queryset=L2ScreeningQuestion.objects.all(),
            required=False,
            label=tdt("Question"),
        )

    def get_filter_form_class(self):
        if self.stage == "l1":
            return self.L1QuestionSelectionForm
        elif self.stage == "l2":
            return self.L2QuestionSelectionForm
        return None

    def get_filter_form(self, data=None):
        review = get_review_from_context()
        if not review:
            return None

        form = super().get_filter_form(data)
        qs = form.fields["question"].queryset
        form.fields["question"].queryset = qs.filter(review=review)

        return form

    def filter_queryset(self, queryset, cleaned_data):
        if cleaned_data["question"]:
            return queryset.filter(**{self.key: cleaned_data["question"]})
        return queryset

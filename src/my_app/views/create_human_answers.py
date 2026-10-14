from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseFormSet, formset_factory
from django.http import HttpResponseRedirect
from django.views.generic import TemplateView

import htpy as h
from markupsafe import Markup

from my_app.models import (
    CitationDatasetColumn,
    L1ScreeningQuestion,
    L2ScreeningQuestion,
)
from my_app.router import route
from my_app.services.create_human_answers import create_human_answers
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import (
    BasePageTemplate,
    GenericForm,
    HtpyTemplateMixin,
    StandardFormMixin,
)
from shortcuts import breadcrumbs as bc
from shortcuts import cached_property, get_token, reverse, tdt


class DatasetColumnChoiceField(forms.ModelChoiceField):
    """Render and validate against preloaded review columns without per-row queries."""

    def __init__(self, columns=()):
        super().__init__(
            queryset=CitationDatasetColumn.objects.none(),
            required=False,
            label=tdt("Dataset column"),
            empty_label=tdt("Leave unchanged"),
        )
        self.set_columns(columns)

    def set_columns(self, columns):
        self.columns = {str(column.pk): column for column in columns}
        self.queryset = CitationDatasetColumn.objects.filter(
            pk__in=self.columns
        )
        self.choices = [
            ("", self.empty_label),
            *[(column.pk, column.name) for column in columns],
        ]

    def to_python(self, value):
        if value in self.empty_values:
            return None
        column = self.columns.get(str(value))
        if column is None:
            raise ValidationError(
                self.error_messages["invalid_choice"],
                code="invalid_choice",
                params={"value": value},
            )
        return column


class HumanAnswerMappingForm(StandardFormMixin):
    column = DatasetColumnChoiceField()

    def __init__(self, *args, question, columns, **kwargs):
        super().__init__(*args, **kwargs)
        self.question = question
        self.fields["column"].set_columns(columns)


class HumanAnswerMappingFormSet(BaseFormSet):
    def __init__(self, *args, questions, columns, **kwargs):
        self.questions = questions
        self.columns = columns
        super().__init__(
            *args, initial=[{} for question in questions], **kwargs
        )

    def get_form_kwargs(self, index):
        return {"question": self.questions[index], "columns": self.columns}

    def total_form_count(self):
        # Rows are determined by the review, never by submitted management data.
        return len(self.questions)

    def clean(self):
        super().clean()
        if self.management_form.cleaned_data.get("TOTAL_FORMS") != len(
            self.questions
        ):
            raise ValidationError(
                tdt(
                    "The questions have changed. Reload this page and try again."
                )
            )


MappingFormSet = formset_factory(
    HumanAnswerMappingForm, formset=HumanAnswerMappingFormSet, extra=0
)


class CreateHumanAnswersPage(BasePageTemplate):
    def title(self):
        return tdt("Create human answers in bulk")

    def content(self):
        review = self.context["review"]
        formsets = self.context["formsets"]
        return [
            bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(
                    label=tdt("Screening criteria"),
                    href=reverse("screening_criteria", args=[review.pk]),
                ),
                bc.BreadcrumbItem(label=self.title()),
            ],
            h.h1[self.title()],
            h.p[
                tdt(
                    "Choose a dataset column for each question to create or overwrite imported human answers for all citations. Leave a dropdown empty to leave that question unchanged. Empty column values clear existing imported answers. Answers entered by named users are preserved."
                )
            ],
            h.form(method="post")[
                h.input(
                    type="hidden",
                    name="csrfmiddlewaretoken",
                    value=get_token(self.request),
                ),
                [
                    h.section[
                        h.h2(".h5.mt-3")[label],
                        (
                            h.div(".alert.alert-danger", role="alert")[
                                Markup(str(formset.non_form_errors()))
                            ]
                            if formset.non_form_errors()
                            else None
                        ),
                        Markup(str(formset.management_form)),
                        [
                            h.fieldset(".border.rounded.p-3.mb-3")[
                                h.legend(".h6")[form.question.question_text],
                                GenericForm(form, include_csrf=False),
                            ]
                            for form in formset
                        ],
                    ]
                    for label, formset in zip(
                        (
                            tdt("L1 screening questions"),
                            tdt("L2 screening questions"),
                        ),
                        formsets,
                    )
                ],
                h.button(".btn.btn-primary", type="submit")[
                    tdt("Create human answers")
                ],
            ],
        ]


@route(
    "reviews/<int:review_id>/human-answers/bulk/", name="create_human_answers"
)
class CreateHumanAnswersView(
    MustAccessReviewMixin, HtpyTemplateMixin, TemplateView
):
    template_component = CreateHumanAnswersPage

    @cached_property
    def formsets(self):
        columns = list(
            CitationDatasetColumn.objects.filter(
                dataset__review=self.review
            ).order_by("id")
        )
        return [
            MappingFormSet(
                self.request.POST if self.request.method == "POST" else None,
                prefix=prefix,
                questions=list(questions.order_by("id")),
                columns=columns,
            )
            for prefix, questions in (
                (
                    "l1",
                    L1ScreeningQuestion.active_objects.filter(
                        review=self.review
                    ),
                ),
                (
                    "l2",
                    L2ScreeningQuestion.active_objects.filter(
                        review=self.review, l1_question__isnull=True
                    ),
                ),
            )
        ]

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            "formsets": self.formsets,
        }

    def post(self, request, *args, **kwargs):
        valid = [formset.is_valid() for formset in self.formsets]
        if all(valid):
            mappings = [
                (form.question, form.cleaned_data["column"])
                for formset in self.formsets
                for form in formset
                if form.cleaned_data.get("column") is not None
            ]
            try:
                create_human_answers(self.review, mappings)
            except ValidationError as error:
                self.formsets[0]._non_form_errors = self.formsets[
                    0
                ].error_class(error.messages, error_class="nonform")
            else:
                return HttpResponseRedirect(
                    reverse("screening_criteria", args=[self.review.pk])
                )
        return self.render_to_response(self.get_context_data())

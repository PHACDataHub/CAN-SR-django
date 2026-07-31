from django import forms
from django.http import HttpResponse
from django.utils import timezone
from django.views import View

import htpy as h

from proj.htpy.modal_component import ModalComponent

from my_app.models import (
    Citation,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    L1ScreeningResult,
)
from my_app.router import route
from my_app.services.l1_screening import DeferredL1ScreeningService
from my_app.views.screening.l1.detail import (
    l1_human_review_control_id,
    render_l1_human_review_control,
    render_l1_screening_control,
)
from my_app.views.screening.l1.list import CitationRowDisplay
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import (
    GenericForm,
    StandardFormMixin,
    cached_property,
    get_object_or_404,
    reverse,
    tdt,
)


class L1HumanAnswerForm(forms.ModelForm, StandardFormMixin):
    class Meta:
        model = L1ScreeningResult
        fields = ["human_selected_answer", "human_notes"]
        labels = {
            "human_selected_answer": tdt("Human answer"),
            "human_notes": tdt("Notes"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["human_selected_answer"].queryset = (
            L1ScreeningQuestionOption.objects.filter(
                question=self.instance.question
            )
        )
        self.fields["human_selected_answer"].required = True


@route(
    "/reviews/<int:review_id>/screening_l1/rows/<int:row_pk>/",
    name="l1_citation_process_screening",
)
class ScreenL1RowView(MustAccessReviewMixin, View):
    @cached_property
    def citation_row(self):
        return Citation.objects.get(
            pk=self.kwargs["row_pk"],
            dataset__review=self.review,
        )

    @cached_property
    def screening_questions(self):
        return list(
            L1ScreeningQuestion.objects.filter(
                review=self.review
            ).prefetch_related("options")
        )

    def post(self, request, *args, **kwargs):
        DeferredL1ScreeningService(
            rows=[self.citation_row],
            questions=self.screening_questions,
            overwrite_existing=True,
        ).perform()

        # render multiple components at top level,
        # client uses this view in two context
        # it will select applicable markup with hx-select
        resp_content = h.fragment[
            CitationRowDisplay(self.citation_row, self.review),
            render_l1_screening_control(self.citation_row, self.review),
        ]

        return HttpResponse(str(resp_content))


class L1CitationMixin(MustAccessReviewMixin, View):
    @cached_property
    def citation_row(self):
        return get_object_or_404(
            Citation,
            pk=self.kwargs["row_pk"],
            dataset__review=self.review,
        )

    @cached_property
    def screening_questions(self):
        return list(L1ScreeningQuestion.objects.filter(review=self.review))


class L1HumanReviewMixin(MustAccessReviewMixin, View):
    @cached_property
    def result(self):
        return get_object_or_404(
            L1ScreeningResult.objects.select_related(
                "question",
                "selected_option",
                "human_selected_answer",
                "human_validated_by",
            ),
            pk=self.kwargs["result_pk"],
            citation__dataset__review=self.review,
        )

    def render_control(self):
        return str(render_l1_human_review_control(self.result, self.review))


@route(
    "/reviews/<int:review_id>/screening_l1/results/<int:result_pk>/validate/",
    name="l1_citation_validate_correct",
)
class L1ValidateCorrectView(L1HumanReviewMixin):
    def post(self, request, *args, **kwargs):
        self.result.human_validation_timestamp = timezone.now()
        self.result.human_validated_by = request.user
        self.result.human_selected_answer = None
        self.result.human_notes = None
        self.result.save(
            update_fields=[
                "human_validation_timestamp",
                "human_validated_by",
                "human_selected_answer",
                "human_notes",
            ]
        )
        return HttpResponse(self.render_control())


@route(
    "/reviews/<int:review_id>/screening_l1/results/<int:result_pk>/undo-validation/",
    name="l1_citation_undo_validation",
)
class L1UndoValidationView(L1HumanReviewMixin):
    def post(self, request, *args, **kwargs):
        self.result.human_validation_timestamp = None
        self.result.human_validated_by = None
        self.result.save(
            update_fields=[
                "human_validation_timestamp",
                "human_validated_by",
            ]
        )
        return HttpResponse(self.render_control())


@route(
    "/reviews/<int:review_id>/screening_l1/results/<int:result_pk>/human-answer/",
    name="l1_citation_human_answer",
)
class L1HumanAnswerView(L1HumanReviewMixin):
    @cached_property
    def form(self):
        return L1HumanAnswerForm(
            self.request.POST or None,
            instance=self.result,
        )

    def render_modal(self):
        form_id = f"l1-human-answer-form-{self.result.id}"
        footer = h.fragment[
            h.button(
                ".btn.btn-secondary",
                type="button",
                **{"data-modal-close": True},
            )[tdt("Cancel")],
            h.button(
                ".btn.btn-primary",
                type="submit",
                form=form_id,
                **{"hx-disabled-elt": "this"},
            )[tdt("Save")],
        ]
        return str(
            ModalComponent(
                title=tdt("Manually answer screening"),
                modal_id=f"l1-human-answer-modal-{self.result.id}",
                footer=footer,
            )[
                h.form(
                    id=form_id,
                    hx_post=reverse(
                        "l1_citation_human_answer",
                        args=[self.review.id, self.result.id],
                    ),
                    hx_target="#modal-slot",
                    hx_swap="innerHTML",
                )[GenericForm(self.form)]
            ]
        )

    def get(self, request, *args, **kwargs):
        return HttpResponse(self.render_modal())

    def post(self, request, *args, **kwargs):
        if not self.form.is_valid():
            return HttpResponse(self.render_modal())

        result = self.form.save(commit=False)
        result.human_validation_timestamp = None
        result.human_validated_by = None
        result.save()

        response = HttpResponse(self.render_control())
        response["HX-Retarget"] = f"#{l1_human_review_control_id(self.result)}"
        response["HX-Reswap"] = "outerHTML"
        response["HX-Trigger-After-Settle"] = "modal-close"
        return response

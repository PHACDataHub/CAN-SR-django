from django import forms
from django.http import HttpResponse

import htpy as h

from proj.htpy.modal_component import ModalComponent

from my_app.models import Citation, ScreeningResultStatus
from my_app.views.screening.question_panels import (
    QuestionPanels,
    question_panel_id,
)
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import (
    GenericForm,
    StandardFormMixin,
    View,
    cached_property,
    get_object_or_404,
    tdt,
)


class ScreeningHumanAnswerForm(forms.ModelForm, StandardFormMixin):
    class Meta:
        fields = ["selected_option", "notes"]
        labels = {
            "selected_option": tdt("Human answer"),
            "notes": tdt("Notes"),
        }

    def __init__(self, *args, question, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["selected_option"].queryset = (
            self._meta.model._meta.get_field(
                "selected_option"
            ).remote_field.model.active_objects.filter(question=question)
        )


class ScreeningHumanAnswerViewMixin(MustAccessReviewMixin, View):
    result_model = None
    answer_model = None
    form_class = None
    prefix = None
    stage = None
    result_select_related = (
        "citation",
        "question",
        "selected_option",
    )
    modal_title = tdt("Your screening answer")

    @cached_property
    def result(self):
        return get_object_or_404(
            self.result_model.objects.select_related(
                *self.result_select_related
            ),
            pk=self.kwargs["result_pk"],
            citation__dataset__review=self.review,
            question__review=self.review,
        )

    @property
    def citation(self):
        return self.result.citation

    @property
    def question(self):
        return self.result.question

    @property
    def form_identifier(self):
        return str(self.result.pk)

    @property
    def control_id(self):
        return question_panel_id(
            self.stage, self.citation.pk, self.question.pk
        )

    @cached_property
    def current_answer(self):
        return (
            self.answer_model.objects.filter(
                citation=self.citation,
                question=self.question,
                user=self.request.user,
            )
            .order_by("-updated_at", "-id")
            .first()
        )

    def render_control(self):
        panels = QuestionPanels(
            self.citation, self.review, self.request.user, self.stage
        )
        return str(panels.panel(self.question).render())

    def can_validate(self):
        return (
            self.result is not None
            and self.result.status == ScreeningResultStatus.COMPLETED
            and self.result.selected_option_id is not None
        )

    def validated_answer_values(self):
        return {"selected_option": self.result.selected_option}

    def human_answer_form_kwargs(self):
        return {"question": self.question}


class ValidateAIAnswerView:
    def post(self, request, *args, **kwargs):
        answers = self.answer_model.objects.filter(
            citation=self.citation,
            question=self.question,
        )
        if not answers.exists() and self.can_validate():
            self.answer_model.objects.create(
                citation=self.citation,
                question=self.question,
                user=request.user,
                **self.validated_answer_values(),
            )
        return HttpResponse(self.render_control())


class HumanAnswerFormView:
    @cached_property
    def answer(self):
        if self.current_answer is not None:
            return self.current_answer
        return self.answer_model(
            citation=self.citation,
            question=self.question,
            user=self.request.user,
        )

    @cached_property
    def form(self):
        return self.form_class(
            self.request.POST or None,
            instance=self.answer,
            **self.human_answer_form_kwargs(),
        )

    def render_modal(self):
        form_id = f"{self.prefix}-human-answer-form-{self.form_identifier}"
        footer = h.fragment[
            h.button(
                ".btn.btn-secondary",
                id=f"{self.prefix}-human-answer-cancel-{self.form_identifier}",
                type="button",
                **{"data-modal-close": True},
            )[tdt("Cancel")],
            h.button(
                ".btn.btn-primary",
                id=f"{self.prefix}-human-answer-save-{self.form_identifier}",
                type="submit",
                form=form_id,
                **{"hx-disabled-elt": "this"},
            )[tdt("Save")],
        ]
        return str(
            ModalComponent(
                title=self.modal_title,
                modal_id=f"{self.prefix}-human-answer-modal-{self.form_identifier}",
                footer=footer,
            )[
                h.h2(".h5.mb-3")[self.question.title],
                h.form(
                    id=form_id,
                    hx_post=self.request.path,
                    hx_target="#modal-slot",
                    hx_swap="innerHTML",
                )[GenericForm(self.form)],
            ]
        )

    def get(self, request, *args, **kwargs):
        return HttpResponse(self.render_modal())

    def post(self, request, *args, **kwargs):
        if not self.form.is_valid():
            return HttpResponse(self.render_modal())

        self.form.save()
        response = HttpResponse(self.render_control())
        response["HX-Retarget"] = f"#{self.control_id}"
        response["HX-Reswap"] = "morph:outerHTML"
        response["HX-Trigger-After-Settle"] = "modal-close"
        return response


class QuestionHumanAnswerViewMixin:
    question_model = None

    @cached_property
    def citation(self):
        return get_object_or_404(
            Citation.objects.select_related("dataset", "document"),
            pk=self.kwargs["citation_id"],
            dataset__review=self.review,
        )

    @cached_property
    def question(self):
        return get_object_or_404(
            self.question_model.active_objects,
            pk=self.kwargs["question_id"],
            review=self.review,
        )

    @cached_property
    def result(self):
        return (
            self.result_model.objects.filter(
                citation=self.citation, question=self.question
            )
            .select_related("selected_option")
            .first()
        )

    @property
    def form_identifier(self):
        return f"{self.citation.pk}-{self.question.pk}"

from django import forms
from django.http import HttpResponse

import htpy as h

from proj.htpy.modal_component import ModalComponent

from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import (
    GenericForm,
    StandardFormMixin,
    View,
    cached_property,
    get_object_or_404,
    reverse,
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
    route_name = None
    render_control_component = None
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
        )

    @cached_property
    def current_answer(self):
        return (
            self.answer_model.objects.filter(
                citation=self.result.citation,
                question=self.result.question,
                user=self.request.user,
            )
            .order_by("-updated_at", "-id")
            .first()
        )

    def render_control(self):
        return str(
            self.render_control_component(
                self.result,
                self.review,
                self.request.user,
            )
        )

    def can_validate(self):
        return self.result.selected_option_id is not None

    def validated_answer_values(self):
        return {"selected_option": self.result.selected_option}

    def human_answer_form_kwargs(self):
        return {"question": self.result.question}


class ValidateAIAnswerView:
    def post(self, request, *args, **kwargs):
        answers = self.answer_model.objects.filter(
            citation=self.result.citation,
            question=self.result.question,
        )
        if not answers.exists() and self.can_validate():
            self.answer_model.objects.create(
                citation=self.result.citation,
                question=self.result.question,
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
            citation=self.result.citation,
            question=self.result.question,
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
        form_id = f"{self.prefix}-human-answer-form-{self.result.id}"
        footer = h.fragment[
            h.button(
                ".btn.btn-secondary",
                id=f"{self.prefix}-human-answer-cancel-{self.result.id}",
                type="button",
                **{"data-modal-close": True},
            )[tdt("Cancel")],
            h.button(
                ".btn.btn-primary",
                id=f"{self.prefix}-human-answer-save-{self.result.id}",
                type="submit",
                form=form_id,
                **{"hx-disabled-elt": "this"},
            )[tdt("Save")],
        ]
        return str(
            ModalComponent(
                title=self.modal_title,
                modal_id=f"{self.prefix}-human-answer-modal-{self.result.id}",
                footer=footer,
            )[
                h.form(
                    id=form_id,
                    hx_post=reverse(
                        self.route_name,
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

        self.form.save()
        response = HttpResponse(self.render_control())
        response["HX-Retarget"] = (
            f"#{self.prefix}-human-review-{self.result.id}"
        )
        response["HX-Reswap"] = "morph:outerHTML"
        response["HX-Trigger-After-Settle"] = "modal-close"
        return response

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
from my_app.views.screening.l1_screening_templating import (
    CitationRowDisplay,
    L1CitationScreeningPage,
    L1ScreeningComponent,
    L1ScreeningPageTemplate,
    badge_id,
    l1_human_review_control_id,
    render_l1_human_review_control,
    render_l1_screening_control,
)
from my_app.views.view_utils import MustAccessReviewMixin, url_with_same_params
from shortcuts import (
    DetailView,
    GenericForm,
    HtpyTemplateMixin,
    ListView,
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


class L1ScreeningBaseView(MustAccessReviewMixin, ListView):
    paginate_by = 10

    def get_queryset(self):
        return Citation.objects.filter(dataset__review=self.review).order_by(
            "order"
        )


@route("/reviews/<int:review_id>/screening_l1/", name="screening_l1")
class ScreeningL1PageView(L1ScreeningBaseView, HtpyTemplateMixin):
    template_component = L1ScreeningPageTemplate


@route(
    "/reviews/<int:review_id>/screening_l1/component/",
    name="screening_l1_component",
)
class ScreeningL1ComponentView(L1ScreeningBaseView):
    def render_to_response(self, context, **response_kwargs):
        page_obj = context["page_obj"]
        component = L1ScreeningComponent(
            review=self.review,
            page_obj=page_obj,
            request=self.request,
        )

        new_page_url = reverse("screening_l1", args=[self.review.id])
        response_headers = {
            "HX-Push-Url": url_with_same_params(
                self.request,
                path=new_page_url,
                page=page_obj.number,
            )
        }

        return HttpResponse(
            str(component.render()),
            headers=response_headers,
            **response_kwargs,
        )


@route(
    "/reviews/<int:review_id>/screening_l1/rows/<int:row_pk>/",
    name="screen_l1_row",
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
        ).perform()

        headers = {
            "HX-Refocus": "#" + badge_id(self.citation_row),
        }

        return HttpResponse(
            str(CitationRowDisplay(self.citation_row, self.review)),
            headers=headers,
        )


@route(
    "/reviews/<int:review_id>/screening_l1/rows/<int:row_pk>/details/",
    name="screen_l1_row_details",
)
class L1CitationScreeningView(
    MustAccessReviewMixin, DetailView, HtpyTemplateMixin
):
    model = Citation
    pk_url_kwarg = "row_pk"
    template_component = L1CitationScreeningPage

    def get_queryset(self):
        return (
            Citation.objects.filter(dataset__review=self.review)
            .select_related("dataset")
            .prefetch_related("dataset__screening_columns")
            .order_by("order")
        )


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


@route(
    "/reviews/<int:review_id>/screening_l1/rows/<int:row_pk>/process/",
    name="screen_l1_row_process",
)
class L1CitationScreeningProcessView(L1CitationMixin):
    def post(self, request, *args, **kwargs):
        DeferredL1ScreeningService(
            rows=[self.citation_row],
            questions=self.screening_questions,
            overwrite_existing=True,
        ).perform()

        return HttpResponse(
            str(render_l1_screening_control(self.citation_row, self.review))
        )


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
    name="screen_l1_validate_correct",
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
    name="screen_l1_undo_validation",
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
    name="screen_l1_human_answer",
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
                        "screen_l1_human_answer",
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

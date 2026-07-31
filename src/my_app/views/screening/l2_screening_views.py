from django import forms
from django.http import HttpResponse
from django.utils import timezone

import htpy as h

from proj.htpy.modal_component import ModalComponent

from my_app.models import (
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    L2ScreeningResult,
)
from my_app.router import route
from my_app.services.l2_screening import DeferredL2ScreeningService
from my_app.views.pdf_views import PdfCitationMetadataView
from my_app.views.screening.l2_common_components import (
    l2_human_review_control_id,
    render_l2_human_review_control,
)
from my_app.views.screening.l2_screening_index_templating import (
    L2ScreeningComponent,
    L2ScreeningPageTemplate,
)
from my_app.views.screening.l2_screening_pdf_templating import (
    L2PdfScreeningPage,
    render_l2_screening_control,
)
from my_app.views.screening.view_utils import (
    DocumentCitationDetailView,
    DocumentCitationListView,
    DocumentCitationMixin,
)
from my_app.views.view_utils import (
    MustAccessReviewMixin,
    paginated_component_response,
)
from shortcuts import (
    GenericForm,
    HtpyTemplateMixin,
    StandardFormMixin,
    View,
    cached_property,
    get_object_or_404,
    reverse,
    tdt,
)

from .util import can_start_l2_screening


class L2HumanAnswerForm(forms.ModelForm, StandardFormMixin):
    class Meta:
        model = L2ScreeningResult
        fields = ["human_selected_answer", "human_notes"]
        labels = {
            "human_selected_answer": tdt("Human answer"),
            "human_notes": tdt("Notes"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["human_selected_answer"].queryset = (
            L2ScreeningQuestionOption.objects.filter(
                question=self.instance.question
            )
        )
        self.fields["human_selected_answer"].required = True


class L2ScreeningBaseView(DocumentCitationListView):
    pass


@route("/reviews/<int:review_id>/screening_l2/", name="l2_citations_list")
class ScreeningL2PageView(L2ScreeningBaseView, HtpyTemplateMixin):
    template_component = L2ScreeningPageTemplate


@route(
    "/reviews/<int:review_id>/screening_l2/component/",
    name="l2_citations_list_partial",
)
class ScreeningL2ComponentView(L2ScreeningBaseView):
    def render_to_response(self, context, **response_kwargs):
        page_obj = context["page_obj"]
        component = L2ScreeningComponent(
            review=self.review,
            page_obj=page_obj,
            request=self.request,
        )

        return paginated_component_response(
            self.request,
            page_obj,
            component.render(),
            reverse("l2_citations_list", args=[self.review.id]),
            **response_kwargs,
        )


@route(
    "/reviews/<int:review_id>/screening_l2/rows/<int:row_pk>/details/",
    name="l2_citation_detail",
)
class L2PdfScreeningView(DocumentCitationDetailView):
    template_component = L2PdfScreeningPage


class L2HumanReviewMixin(MustAccessReviewMixin, View):
    @cached_property
    def result(self):
        return get_object_or_404(
            L2ScreeningResult.objects.select_related(
                "question",
                "human_selected_answer",
                "human_validated_by",
            ),
            pk=self.kwargs["result_pk"],
            citation__dataset__review=self.review,
        )

    def render_control(self):
        return str(render_l2_human_review_control(self.result, self.review))


@route(
    "/reviews/<int:review_id>/screening_l2/results/<int:result_pk>/validate/",
    name="l2_citation_validate_correct",
)
class L2ValidateCorrectView(L2HumanReviewMixin):
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
    "/reviews/<int:review_id>/screening_l2/results/<int:result_pk>/undo-validation/",
    name="l2_citation_undo_validation",
)
class L2UndoValidationView(L2HumanReviewMixin):
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
    "/reviews/<int:review_id>/screening_l2/results/<int:result_pk>/human-answer/",
    name="l2_citation_human_answer",
)
class L2HumanAnswerView(L2HumanReviewMixin):
    @cached_property
    def form(self):
        return L2HumanAnswerForm(
            self.request.POST or None,
            instance=self.result,
        )

    def render_modal(self):
        form_id = f"l2-human-answer-form-{self.result.id}"
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
                modal_id=f"l2-human-answer-modal-{self.result.id}",
                footer=footer,
            )[
                h.form(
                    id=form_id,
                    hx_post=reverse(
                        "l2_citation_human_answer",
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
        response["HX-Retarget"] = f"#{l2_human_review_control_id(self.result)}"
        response["HX-Reswap"] = "outerHTML"
        response["HX-Trigger-After-Settle"] = "modal-close"
        return response


@route(
    "/reviews/<int:review_id>/screening_l2/rows/<int:row_pk>/process/",
    name="l2_citation_process_screening",
)
class L2PdfScreeningProcessView(DocumentCitationMixin):
    @cached_property
    def screening_questions(self):
        return list(L2ScreeningQuestion.objects.filter(review=self.review))

    def post(self, request, *args, **kwargs):
        if not can_start_l2_screening(self.citation_row):
            return HttpResponse(
                str(
                    render_l2_screening_control(
                        self.citation_row,
                        self.review,
                    )
                ),
                status=409,
            )

        DeferredL2ScreeningService(
            rows=[self.citation_row],
            questions=self.screening_questions,
            overwrite_existing=True,
        ).perform()

        return HttpResponse(
            str(render_l2_screening_control(self.citation_row, self.review))
        )


@route(
    "/reviews/<int:review_id>/screening_l2/rows/<int:row_pk>/pdf-metadata/",
    name="l2_citation_pdf_metadata",
)
class L2PdfCitationMetadataView(PdfCitationMetadataView):
    result_model = L2ScreeningResult

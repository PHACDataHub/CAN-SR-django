from django import forms
from django.http import HttpResponse

import htpy as h

from proj.htpy.modal_component import ModalComponent

from my_app.models import Parameter, ParameterExtractionResult
from my_app.router import route
from my_app.services.parameter_extraction import (
    DeferredParameterExtractionService,
)
from my_app.views.parameter_extraction_templating import (
    ParameterExtractionComponent,
    ParameterExtractionPageTemplate,
    ParameterExtractionPdfPage,
    parameter_extraction_human_review_control_id,
    render_parameter_extraction_control,
)
from my_app.views.pdf_views import PdfCitationMetadataView
from my_app.views.screening.util import can_start_parameter_extraction
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


class ParameterExtractionHumanAnswerForm(
    forms.ModelForm,
    StandardFormMixin,
):
    human_found = forms.TypedChoiceField(
        label=tdt("Human found"),
        choices=((True, tdt("Yes")), (False, tdt("No"))),
        coerce=lambda value: value == "True",
        widget=forms.RadioSelect,
    )

    class Meta:
        model = ParameterExtractionResult
        fields = ["human_found", "human_value"]
        labels = {
            "human_found": tdt("Human found"),
            "human_value": tdt("Human value"),
        }

    def clean_human_value(self):
        return self.cleaned_data["human_value"] or None


class ParameterExtractionBaseView(DocumentCitationListView):
    pass


@route(
    "/reviews/<int:review_id>/parameter_extraction/",
    name="parameter_extraction_citations_list",
)
class ParameterExtractionPageView(
    ParameterExtractionBaseView,
    HtpyTemplateMixin,
):
    template_component = ParameterExtractionPageTemplate


@route(
    "/reviews/<int:review_id>/parameter_extraction/component/",
    name="parameter_extraction_citations_list_partial",
)
class ParameterExtractionComponentView(ParameterExtractionBaseView):
    def render_to_response(self, context, **response_kwargs):
        page_obj = context["page_obj"]
        component = ParameterExtractionComponent(
            review=self.review,
            page_obj=page_obj,
            request=self.request,
        )

        return paginated_component_response(
            self.request,
            page_obj,
            component.render(),
            reverse(
                "parameter_extraction_citations_list", args=[self.review.id]
            ),
            **response_kwargs,
        )


@route(
    "/reviews/<int:review_id>/parameter_extraction/rows/<int:row_pk>/details/",
    name="parameter_extraction_citation_detail",
)
class ParameterExtractionPdfView(DocumentCitationDetailView):
    template_component = ParameterExtractionPdfPage


@route(
    "/reviews/<int:review_id>/parameter_extraction/rows/<int:row_pk>/process/",
    name="parameter_extraction_citation_process_extraction",
)
class ParameterExtractionProcessView(DocumentCitationMixin):
    @cached_property
    def parameters(self):
        return list(Parameter.objects.filter(category__review=self.review))

    def post(self, request, *args, **kwargs):
        if not can_start_parameter_extraction(self.citation_row):
            return HttpResponse(
                str(
                    render_parameter_extraction_control(
                        self.citation_row,
                        self.review,
                    )
                ),
                status=409,
            )

        DeferredParameterExtractionService(
            rows=[self.citation_row],
            questions=self.parameters,
            overwrite_existing=True,
        ).perform()

        return HttpResponse(
            str(
                render_parameter_extraction_control(
                    self.citation_row,
                    self.review,
                )
            )
        )


class ParameterExtractionHumanReviewMixin(MustAccessReviewMixin, View):
    @cached_property
    def result(self):
        return get_object_or_404(
            ParameterExtractionResult.objects.select_related(
                "citation",
                "question",
                "question__category",
            ),
            pk=self.kwargs["result_pk"],
            citation__dataset__review=self.review,
        )

    def render_control(self):
        component = ParameterExtractionPdfPage(
            context={"object": self.result.citation, "review": self.review},
            request=self.request,
        )
        return str(component.render_human_review_control(self.result))


@route(
    "/reviews/<int:review_id>/parameter_extraction/results/<int:result_pk>/validate-ai-answer/",
    name="parameter_extraction_citation_validate_ai_answer",
)
class ParameterExtractionValidateAiAnswerView(
    ParameterExtractionHumanReviewMixin
):
    def post(self, request, *args, **kwargs):
        self.result.human_found = self.result.found
        self.result.human_value = self.result.value
        self.result.save(update_fields=["human_found", "human_value"])
        return HttpResponse(self.render_control())


@route(
    "/reviews/<int:review_id>/parameter_extraction/results/<int:result_pk>/human-answer/",
    name="parameter_extraction_citation_human_answer",
)
class ParameterExtractionHumanAnswerView(ParameterExtractionHumanReviewMixin):
    @cached_property
    def form(self):
        return ParameterExtractionHumanAnswerForm(
            self.request.POST or None,
            instance=self.result,
        )

    def render_modal(self):
        form_id = f"parameter-extraction-human-answer-form-{self.result.id}"
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
                title=tdt("Modify human values"),
                modal_id=f"parameter-extraction-human-answer-modal-{self.result.id}",
                footer=footer,
            )[
                h.form(
                    id=form_id,
                    hx_post=reverse(
                        "parameter_extraction_citation_human_answer",
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
            f"#{parameter_extraction_human_review_control_id(self.result)}"
        )
        response["HX-Reswap"] = "outerHTML"
        response["HX-Trigger-After-Settle"] = "modal-close"
        return response


@route(
    "/reviews/<int:review_id>/parameter_extraction/rows/<int:row_pk>/pdf-metadata/",
    name="parameter_extraction_citation_pdf_metadata",
)
class ParameterExtractionPdfCitationMetadataView(PdfCitationMetadataView):
    result_model = ParameterExtractionResult

from django import forms
from django.core.validators import FileExtensionValidator
from django.http import HttpResponse

import htpy as h

from proj.htpy.modal_component import ModalComponent

from my_app.models import (
    Citation,
    Document,
    L1ScreeningResult,
    L2ScreeningResult,
    Parameter,
    ParameterExtractionResult,
)
from my_app.router import route
from my_app.services.parameter_extraction import (
    DeferredParameterExtractionService,
)
from my_app.services.process_document import QueueProcessDocumentService
from my_app.views.parameter_extraction_templating import (
    ParameterExtractionComponent,
    ParameterExtractionPageTemplate,
    ParameterExtractionPdfPage,
    parameter_extraction_human_review_control_id,
    render_parameter_extraction_control,
)
from my_app.views.pdf_components import DocumentUploadModal
from my_app.views.pdf_views import PdfCitationFileView, PdfCitationMetadataView
from my_app.views.screening.util import can_start_parameter_extraction
from my_app.views.view_utils import MustAccessReviewMixin, url_with_same_params
from shortcuts import (
    DetailView,
    GenericForm,
    HtpyTemplateMixin,
    ListView,
    StandardFormMixin,
    View,
    cached_property,
    get_object_or_404,
    reverse,
    tdt,
    transaction,
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


class ParameterExtractionDocumentUploadForm(StandardFormMixin):
    document_file = forms.FileField(
        label=tdt("PDF document"),
        validators=[FileExtensionValidator(["pdf"])],
        widget=forms.FileInput(attrs={"accept": ".pdf,application/pdf"}),
    )
    confirm_replace = forms.BooleanField(
        label=tdt(
            "I understand this will delete the existing document, text extraction result, and screening results before uploading the replacement."
        ),
        required=True,
    )

    def __init__(self, *args, existing_document=False, **kwargs):
        self.existing_document = existing_document
        super().__init__(*args, **kwargs)

        if not self.existing_document:
            self.fields.pop("confirm_replace", None)


class ParameterExtractionBaseView(MustAccessReviewMixin, ListView):
    paginate_by = 10

    def get_queryset(self):
        return (
            Citation.objects.filter(dataset__review=self.review)
            .select_related("document", "document__text_extraction_result")
            .order_by("order")
        )


@route(
    "/reviews/<int:review_id>/parameter_extraction/",
    name="parameter_extraction",
)
class ParameterExtractionPageView(
    ParameterExtractionBaseView,
    HtpyTemplateMixin,
):
    template_component = ParameterExtractionPageTemplate


@route(
    "/reviews/<int:review_id>/parameter_extraction/component/",
    name="parameter_extraction_component",
)
class ParameterExtractionComponentView(ParameterExtractionBaseView):
    def render_to_response(self, context, **response_kwargs):
        page_obj = context["page_obj"]
        component = ParameterExtractionComponent(
            review=self.review,
            page_obj=page_obj,
            request=self.request,
        )

        new_page_url = reverse("parameter_extraction", args=[self.review.id])
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


class ParameterExtractionDocumentUploadViewMixin(MustAccessReviewMixin):
    @cached_property
    def citation_row(self):
        return get_object_or_404(
            Citation,
            pk=self.kwargs["row_pk"],
            dataset__review=self.review,
        )

    @cached_property
    def existing_document(self):
        return self.citation_row.document

    @cached_property
    def form(self):
        return ParameterExtractionDocumentUploadForm(
            self.request.POST or None,
            self.request.FILES or None,
            existing_document=self.existing_document is not None,
        )

    @cached_property
    def modal(self):
        return DocumentUploadModal(
            form=self.form,
            review=self.review,
            citation_row=self.citation_row,
            existing_document=self.existing_document,
            route_name="parameter_extraction_row_upload",
            prefix="parameter-extraction",
        )

    def render_modal(self):
        return self.modal.render()

    def delete_existing_content(self):
        L1ScreeningResult.objects.filter(citation=self.citation_row).delete()
        L2ScreeningResult.objects.filter(citation=self.citation_row).delete()
        ParameterExtractionResult.objects.filter(
            citation=self.citation_row
        ).delete()

        existing_document = self.existing_document
        if existing_document is not None:
            existing_document.delete()

    def attach_new_document(self):
        document = Document.objects.create(
            file=self.form.cleaned_data["document_file"]
        )
        self.citation_row.document = document
        self.citation_row.save(update_fields=["document"])
        QueueProcessDocumentService(document=document).perform()

    def form_valid(self):
        with transaction.atomic():
            self.delete_existing_content()
            self.attach_new_document()

        response = HttpResponse("")
        response["HX-Trigger"] = "citations-update"
        response["HX-Trigger-After-Settle"] = "modal-close"
        response["HX-Reswap"] = "none"
        return response

    def form_invalid(self):
        response = HttpResponse(self.render_modal())
        response["HX-Refocus"] = "#form-error-summary"
        return response

    def post(self, *args, **kwargs):
        if self.form.is_valid():
            return self.form_valid()

        return self.form_invalid()


@route(
    "/reviews/<int:review_id>/parameter_extraction/rows/<int:row_pk>/upload/",
    name="parameter_extraction_row_upload",
)
class ParameterExtractionRowUploadView(
    ParameterExtractionDocumentUploadViewMixin,
    View,
):
    def get(self, *args, **kwargs):
        return HttpResponse(self.render_modal())


@route(
    "/reviews/<int:review_id>/parameter_extraction/rows/<int:row_pk>/details/",
    name="parameter_extraction_row_details",
)
class ParameterExtractionPdfView(
    MustAccessReviewMixin,
    DetailView,
    HtpyTemplateMixin,
):
    model = Citation
    pk_url_kwarg = "row_pk"
    template_component = ParameterExtractionPdfPage

    def get_queryset(self):
        return (
            Citation.objects.filter(dataset__review=self.review)
            .select_related("document", "document__text_extraction_result")
            .order_by("order")
        )


@route(
    "/reviews/<int:review_id>/parameter_extraction/rows/<int:row_pk>/process/",
    name="parameter_extraction_row_process",
)
class ParameterExtractionProcessView(MustAccessReviewMixin, View):
    @cached_property
    def citation_row(self):
        return get_object_or_404(
            Citation.objects.select_related(
                "document",
                "document__text_extraction_result",
                "document__figure_extraction_result",
            ),
            pk=self.kwargs["row_pk"],
            dataset__review=self.review,
        )

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
    name="parameter_extraction_validate_ai_answer",
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
    name="parameter_extraction_human_answer",
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
                        "parameter_extraction_human_answer",
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
    "/reviews/<int:review_id>/parameter_extraction/rows/<int:row_pk>/pdf/",
    name="parameter_extraction_row_pdf",
)
class ParameterExtractionPdfCitationView(PdfCitationFileView):
    pass


@route(
    "/reviews/<int:review_id>/parameter_extraction/rows/<int:row_pk>/pdf-metadata/",
    name="parameter_extraction_row_pdf_metadata",
)
class ParameterExtractionPdfCitationMetadataView(PdfCitationMetadataView):
    result_model = ParameterExtractionResult

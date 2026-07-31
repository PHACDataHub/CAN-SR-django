from django import forms
from django.core.validators import FileExtensionValidator
from django.http import FileResponse, HttpResponse

from my_app.models import (
    Document,
    L1ScreeningResult,
    L2ScreeningResult,
    ParameterExtractionResult,
)
from my_app.router import route
from my_app.services.process_document import QueueProcessDocumentService
from my_app.views.pdf_components import (
    CitationDocumentUploadModal as BaseCitationDocumentUploadModal,
)
from my_app.views.screening.document_util_components import (
    DocumentCitationMixin,
)
from shortcuts import StandardFormMixin, cached_property, tdt, transaction


class CitationDocumentUploadModal(BaseCitationDocumentUploadModal):
    pass


class CitationDocumentUploadForm(StandardFormMixin):
    document_file = forms.FileField(
        label=tdt("PDF document"),
        validators=[FileExtensionValidator(["pdf"])],
        widget=forms.FileInput(attrs={"accept": ".pdf,application/pdf"}),
    )
    should_run_l2_screening = forms.BooleanField(
        label=tdt("Run L2 screening immediately"),
        required=False,
    )
    should_run_parameter_extraction = forms.BooleanField(
        label=tdt("Run parameter extraction immediately"),
        required=False,
    )
    confirm_replace = forms.BooleanField(
        label=tdt(
            "I understand this will delete the existing document, text extraction result, and screening results before uploading the replacement."
        ),
        required=True,
    )

    def __init__(
        self,
        *args,
        existing_document=False,
        l2_screening_configured=False,
        parameter_extraction_configured=False,
        **kwargs,
    ):
        self.existing_document = existing_document
        super().__init__(*args, **kwargs)

        if not self.existing_document:
            self.fields.pop("confirm_replace", None)

        if not l2_screening_configured:
            field = self.fields["should_run_l2_screening"]
            field.disabled = True
            field.help_text = tdt(
                "L2 screening criteria have not been configured for this review."
            )

        if not parameter_extraction_configured:
            field = self.fields["should_run_parameter_extraction"]
            field.disabled = True
            field.help_text = tdt(
                "Parameters have not been configured for this review."
            )


@route(
    "/reviews/<int:review_id>/citations/<int:row_pk>/document/pdf/",
    name="citation_download_pdf_document",
)
class CitationDocumentPdfView(DocumentCitationMixin):
    def get(self, request, *args, **kwargs):
        document_file = self.document.file
        return FileResponse(
            document_file.open("rb"),
            content_type="application/pdf",
            as_attachment=False,
            filename=document_file.name,
        )


@route(
    "/reviews/<int:review_id>/citations/<int:row_pk>/document/upload/",
    name="citation_upload_pdf_document_modal",
)
class CitationDocumentUploadView(DocumentCitationMixin):
    @cached_property
    def existing_document(self):
        return self.citation_row.document

    @cached_property
    def l2_screening_configured(self):
        return self.review.l2_screening_questions.filter(
            options__isnull=False
        ).exists()

    @cached_property
    def parameter_extraction_configured(self):
        return self.review.parameter_categories.filter(
            parameters__isnull=False
        ).exists()

    @cached_property
    def form(self):
        return CitationDocumentUploadForm(
            self.request.POST or None,
            self.request.FILES or None,
            existing_document=self.existing_document is not None,
            l2_screening_configured=self.l2_screening_configured,
            parameter_extraction_configured=(
                self.parameter_extraction_configured
            ),
        )

    @cached_property
    def modal(self):
        return CitationDocumentUploadModal(
            form=self.form,
            review=self.review,
            citation_row=self.citation_row,
            existing_document=self.existing_document,
        )

    def get(self, *args, **kwargs):
        return HttpResponse(self.render_modal())

    def post(self, *args, **kwargs):
        if self.form.is_valid():
            return self.form_valid()

        return self.form_invalid()

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
        QueueProcessDocumentService(
            document=document,
            should_run_l2_screening=self.form.cleaned_data[
                "should_run_l2_screening"
            ],
            should_run_parameter_extraction=self.form.cleaned_data[
                "should_run_parameter_extraction"
            ],
        ).perform()

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

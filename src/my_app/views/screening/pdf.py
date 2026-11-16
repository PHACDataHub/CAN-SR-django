import logging

from django import forms
from django.core.validators import FileExtensionValidator
from django.http import FileResponse, Http404, HttpResponse

from proj.util import MissingPreconditionError

from my_app.models import (
    Citation,
    Document,
    L1ScreeningResult,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    L2ScreeningResult,
    Parameter,
    ParameterExtractionResult,
    PdfFromDOIRequest,
)
from my_app.router import route
from my_app.services.doi_pdf_service import (
    DoiPdfConfigurationError,
    DoiPdfError,
    PdfFromDOIAlreadyPendingError,
    PendingDocumentProcessingError,
    QueueDoiPdfService,
    delete_stored_file,
    ensure_no_pending_processing,
    is_doi_pdf_configured,
    log_doi_pdf_event,
)
from my_app.services.process_document import QueueProcessDocumentService
from my_app.views.delete_confirmation import DeleteConfirmation
from my_app.views.pdf_components import (
    CitationDocumentUploadModal as BaseCitationDocumentUploadModal,
)
from my_app.views.pdf_components import DoiPdfDownloadControl
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
    "/reviews/<int:review_id>/citations/<int:row_pk>/document/download-from-doi/",
    name="citation_download_pdf_from_doi",
)
class CitationDoiPdfDownloadView(DocumentCitationMixin):
    def post(self, request, *args, **kwargs):
        error = None
        log_doi_pdf_event(
            "frontend_download_requested",
            citation_id=self.citation_row.pk,
            requesting_user_id=request.user.pk,
        )
        with transaction.atomic():
            citation = Citation.objects.select_for_update().get(
                pk=self.citation_row.pk
            )
            if citation.document_id is None:
                try:
                    if not is_doi_pdf_configured():
                        log_doi_pdf_event(
                            "frontend_download_not_configured",
                            level=logging.WARNING,
                            citation_id=citation.pk,
                        )
                        raise DoiPdfConfigurationError(
                            tdt("Automatic PDF download is not configured.")
                        )
                    QueueDoiPdfService(
                        citation, requesting_user=request.user
                    ).perform()
                except PdfFromDOIAlreadyPendingError:
                    pass
                except DoiPdfConfigurationError as exc:
                    error = str(exc)
                except (DoiPdfError, ValueError) as exc:
                    log_doi_pdf_event(
                        "frontend_doi_rejected",
                        level=logging.WARNING,
                        citation_id=citation.pk,
                        error=str(exc),
                    )
                    error = tdt(
                        "A valid DOI is required for automatic PDF download."
                    )
            else:
                log_doi_pdf_event(
                    "frontend_pdf_already_attached",
                    citation_id=citation.pk,
                    document_id=citation.document_id,
                )
        citation.refresh_from_db()
        return HttpResponse(
            str(DoiPdfDownloadControl(citation, self.review, error=error))
        )


@route(
    "/reviews/<int:review_id>/citations/<int:row_pk>/document/<int:document_id>/delete/",
    name="citation_delete_pdf",
)
class CitationDocumentDeleteView(DocumentCitationMixin):
    def render_confirmation(self, *, error=None):
        return HttpResponse(
            DeleteConfirmation(
                tdt("Delete PDF"),
                tdt(
                    "This will delete the PDF, its extracted text, figures and tables, "
                    "and the AI results for L2 screening and parameter extraction. "
                    "The citation, L1 results and human answers will be kept."
                ),
                self.request.path,
                error=error,
            )
        )

    def get(self, *args, **kwargs):
        if self.citation_row.document_id != self.kwargs["document_id"]:
            raise Http404
        return self.render_confirmation()

    def post(self, *args, **kwargs):
        try:
            with transaction.atomic():
                self.delete_document()
        except PendingDocumentProcessingError:
            return self.render_confirmation(
                error=tdt(
                    "Wait for processing to finish before deleting the PDF."
                )
            )
        except MissingPreconditionError as exc:
            return self.render_confirmation(error=str(exc))
        return HttpResponse(
            headers={"HX-Trigger": "citations-update", "HX-Reswap": "none"}
        )

    def delete_document(self):
        citation = Citation.objects.select_for_update().get(
            pk=self.citation_row.pk
        )
        if citation.document_id != self.kwargs["document_id"]:
            raise MissingPreconditionError(
                tdt("The attached PDF has changed.")
            )

        document = Document.objects.select_for_update().get(
            pk=citation.document_id
        )
        if document.citations.exclude(pk=citation.pk).exists():
            raise MissingPreconditionError(
                tdt(
                    "This PDF is shared by another citation and cannot be deleted here."
                )
            )
        if PdfFromDOIRequest.objects.filter(
            citation=citation, status=PdfFromDOIRequest.Status.PENDING
        ).exists():
            raise MissingPreconditionError(
                tdt(
                    "Wait for the PDF download to finish before deleting the PDF."
                )
            )
        ensure_no_pending_processing(citation)

        files = [
            document.file,
            *(figure.file for figure in document.documentfigures.all()),
        ]
        L2ScreeningResult.objects.filter(citation=citation).delete()
        ParameterExtractionResult.objects.filter(citation=citation).delete()
        document.delete()
        for file in files:
            if file.name:
                transaction.on_commit(
                    lambda storage=file.storage, name=file.name: delete_stored_file(
                        storage, name, reason="deleted_document_file"
                    )
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
        return L2ScreeningQuestionOption.active_objects.filter(
            question__review=self.review,
            deletion_time__isnull=True,
            question__deletion_time__isnull=True,
        ).exists()

    @cached_property
    def parameter_extraction_configured(self):
        return Parameter.active_objects.filter(review=self.review).exists()

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

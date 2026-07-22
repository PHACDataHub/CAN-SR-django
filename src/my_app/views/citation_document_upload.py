from dataclasses import dataclass

from django import forms
from django.core.validators import FileExtensionValidator
from django.http import HttpResponse

import htpy as h

from proj.htpy.form_components import ErrorSummary
from proj.htpy.modal_component import ModalComponent

from my_app.models import (
    Citation,
    Document,
    L1ScreeningResult,
    L2ScreeningResult,
    ParameterExtractionResult,
    Review,
)
from my_app.router import route
from my_app.services.process_document import QueueProcessDocumentService
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import (
    GenericForm,
    StandardFormMixin,
    View,
    cached_property,
    get_object_or_404,
    reverse,
    tdt,
    transaction,
)


@dataclass
class DocumentUploadModal:
    form: object
    review: Review
    citation_row: Citation
    existing_document: Document | None
    route_name: str
    prefix: str

    @property
    def modal_id(self):
        return f"{self.prefix}-upload-modal-{self.citation_row.id}"

    @property
    def form_id(self):
        return f"{self.prefix}-upload-form-{self.citation_row.id}"

    def render(self):
        title = (
            tdt("Replace document")
            if self.existing_document is not None
            else tdt("Upload document")
        )

        footer = h.fragment[
            h.button(
                {
                    "type": "button",
                    "class": "btn btn-secondary",
                    "data-modal-close": True,
                }
            )[tdt("Cancel")],
        ]

        return ModalComponent(
            title=title,
            modal_id=self.modal_id,
            footer=footer,
        )[self.render_form_body()]

    def render_form_body(self):
        return h.form(
            id=self.form_id,
            method="post",
            enctype="multipart/form-data",
            novalidate=True,
            hx_post=reverse(
                self.route_name,
                args=[self.review.id, self.citation_row.id],
            ),
            hx_target="#modal-slot",
            hx_swap="innerHTML",
            hx_encoding="multipart/form-data",
        )[
            ErrorSummary([self.form]),
            GenericForm(self.form),
            h.div(".mt-3.text-end")[
                h.button(
                    ".btn.btn-primary",
                    type="submit",
                    **{"hx-disabled-elt": "this"},
                )[
                    (
                        tdt("Replace document")
                        if self.existing_document is not None
                        else tdt("Upload document")
                    )
                ]
            ],
        ]


class CitationDocumentUploadForm(StandardFormMixin):
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


@route(
    "/reviews/<int:review_id>/citations/<int:row_pk>/document/upload/",
    name="citation_document_upload",
)
class CitationDocumentUploadView(MustAccessReviewMixin, View):
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
        return CitationDocumentUploadForm(
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
            route_name="citation_document_upload",
            prefix="citation-document",
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

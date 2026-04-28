from pathlib import Path

from django import forms
from django.contrib import messages
from django.core.validators import FileExtensionValidator
from django.http import HttpResponseRedirect
from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils.text import get_valid_filename
from django.utils.timezone import localtime
from django.views.generic import DetailView, FormView, ListView

import htpy as h

from proj.htpy.base_page import BasePageTemplate
from proj.htpy.generic_form import GenericForm
from proj.htpy.util import HtpyTemplateMixin
from proj.text import tdt, tm

from my_app.models import Document, DocumentMetadata
from my_app.router import route


class UploadPdfForm(forms.Form):
    pdf_file = forms.FileField(
        label=tm("pdf_file"),
        validators=[FileExtensionValidator(["pdf"])],
        widget=forms.FileInput(attrs={"accept": "application/pdf"}),
    )


class PdfUploadPage(BasePageTemplate):
    def title(self):
        return tm("upload_pdf_title")

    def content(self):
        return [
            h.h1[tm("upload_pdf_title")],
            h.p(".text-muted")[tm("upload_pdf_instructions")],
            h.form(
                method="post", enctype="multipart/form-data", novalidate=True
            )[
                GenericForm(
                    self.context["form"], get_token(self.request)
                ).render(),
                h.div(".text-end.mt-3")[
                    h.button(".btn.btn-primary", type="submit")[
                        tm("upload_pdf_submit")
                    ],
                ],
            ],
            h.div(".mt-3")[
                h.a(
                    href=reverse("document_list"),
                    class_="btn btn-outline-secondary",
                )[tm("back_to_list")],
            ],
        ]


class DocumentListPage(BasePageTemplate):
    def title(self):
        return tm("document_list_title")

    def content(self):
        documents = self.context["object_list"]

        return [
            h.h1[tm("document_list_title")],
            h.div(".mb-3")[
                h.a(
                    href=reverse("upload_pdf"),
                    class_="btn btn-primary",
                )[tm("upload_new_pdf")],
            ],
            (
                h.p(".text-muted")[tm("no_documents_yet")]
                if not documents
                else h.table(".table.table-striped.align-middle")[
                    h.thead[
                        h.tr[
                            h.th[tm("document_type_label")],
                            h.th[tm("document_file_label")],
                            h.th[tdt("Metadata")],
                            h.th[tm("associated_user_label")],
                            h.th[tm("upload_date_label")],
                        ]
                    ],
                    h.tbody[
                        [
                            self._render_document_row(document)
                            for document in documents
                        ]
                    ],
                ]
            ),
        ]

    def _render_document_row(self, document):
        return h.tr[
            h.td[document.document_type],
            h.td[
                h.a(href=reverse("document_detail", args=[document.id]))[
                    document.file.name
                ]
            ],
            h.td[self._render_document_metadata(document)],
            h.td[document.uploaded_by.username],
            h.td[localtime(document.uploaded_at).strftime("%Y-%m-%d %H:%M")],
        ]

    def _render_document_metadata(self, document):
        document_metadata = self._get_document_metadata(document)
        if document_metadata is None:
            return h.span(".text-muted")[tdt("No metadata available.")]
        return self._render_json_value(document_metadata.metadata)

    def _get_document_metadata(self, document):
        try:
            return document.document_metadata
        except DocumentMetadata.DoesNotExist:
            return None

    def _render_json_value(self, value):
        if isinstance(value, dict):
            if not value:
                return h.span(".text-muted")[tdt("Empty")]
            return h.dl(".row.mb-0")[
                [
                    rendered
                    for key, item in value.items()
                    for rendered in (
                        h.dt(".col-sm-4.mb-0")[key],
                        h.dd(".col-sm-8.mb-0")[self._render_json_value(item)],
                    )
                ]
            ]

        if isinstance(value, list):
            if not value:
                return h.span(".text-muted")[tdt("Empty")]
            return h.ul(".mb-0.ps-3")[
                [h.li[self._render_json_value(item)] for item in value]
            ]

        if value is None:
            return h.span(".text-muted")["null"]

        if isinstance(value, bool):
            return tm("yes") if value else tm("no")

        return value


class DocumentDetailPage(BasePageTemplate):
    def title(self):
        return tm("document_detail_title")

    def content(self):
        document = self.context["object"]
        document_metadata = self._get_document_metadata(document)

        return [
            h.h1[tm("document_detail_title")],
            h.div(".mb-3")[
                h.a(
                    href=reverse("document_list"),
                    class_="btn btn-outline-secondary",
                )[tm("back_to_documents")],
            ],
            h.table(".table")[
                h.tbody[
                    h.tr[
                        h.th[tm("document_type_label")],
                        h.td[document.document_type],
                    ],
                    h.tr[
                        h.th[tm("document_file_label")],
                        h.td[
                            h.a(href=document.file.url)[tm("open_file")],
                            h.div(".text-muted.small")[document.file.name],
                        ],
                    ],
                    h.tr[
                        h.th[tm("source_url_label")],
                        h.td[document.source_url or "-"],
                    ],
                    h.tr[
                        h.th[tm("associated_user_label")],
                        h.td[document.uploaded_by.username],
                    ],
                    h.tr[
                        h.th[tm("upload_date_label")],
                        h.td[
                            localtime(document.uploaded_at).strftime(
                                "%Y-%m-%d %H:%M"
                            )
                        ],
                    ],
                ]
            ],
            h.h2(".h4.mt-4")[tdt("Document metadata")],
            (
                h.p(".text-muted")[tdt("No metadata available.")]
                if document_metadata is None
                else h.div(".border.rounded.p-3.bg-body-tertiary")[
                    self._render_json_value(document_metadata.metadata)
                ]
            ),
        ]

    def _get_document_metadata(self, document):
        try:
            return document.document_metadata
        except DocumentMetadata.DoesNotExist:
            return None

    def _render_json_value(self, value):
        if isinstance(value, dict):
            if not value:
                return h.span(".text-muted")[tdt("Empty")]
            return h.dl(".row.mb-0")[
                [
                    rendered
                    for key, item in value.items()
                    for rendered in (
                        h.dt(".col-sm-3.mb-0")[key],
                        h.dd(".col-sm-9.mb-0")[self._render_json_value(item)],
                    )
                ]
            ]

        if isinstance(value, list):
            if not value:
                return h.span(".text-muted")[tdt("Empty")]
            return h.ul(".mb-0.ps-3")[
                [h.li[self._render_json_value(item)] for item in value]
            ]

        if value is None:
            return h.span(".text-muted")["null"]

        if isinstance(value, bool):
            return tm("yes") if value else tm("no")

        return value


@route("upload-pdf/", name="upload_pdf")
class UploadPdfView(FormView, HtpyTemplateMixin):
    form_class = UploadPdfForm
    template_component = PdfUploadPage

    def form_valid(self, form):
        uploaded = form.cleaned_data["pdf_file"]
        filename = get_valid_filename(Path(uploaded.name).name)
        uploaded.name = filename
        Document.objects.create(
            uploaded_by=self.request.user,
            document_type="pdf",
            file=uploaded,
        )
        messages.success(self.request, tm("pdf_uploaded"))
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("document_list")


@route("documents/", name="document_list")
class DocumentListView(ListView, HtpyTemplateMixin):
    template_component = DocumentListPage
    model = Document

    def get_queryset(self):
        return Document.objects.select_related(
            "uploaded_by", "document_metadata"
        )


@route("documents/<int:pk>/", name="document_detail")
class DocumentDetailView(DetailView, HtpyTemplateMixin):
    template_component = DocumentDetailPage
    model = Document

    def get_queryset(self):
        return Document.objects.select_related(
            "uploaded_by", "document_metadata"
        )

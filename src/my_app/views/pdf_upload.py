from pathlib import Path

from django import forms
from django.contrib import messages
from django.core.validators import FileExtensionValidator
from django.http import HttpResponseRedirect
from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils.text import get_valid_filename
from django.views.generic import FormView

import htpy as h

from proj.htpy.base_page import BasePageTemplate
from proj.htpy.generic_form import GenericForm
from proj.htpy.util import HtpyTemplateMixin
from proj.text import tm

from my_app.models import Document
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
                    href=reverse("list_projects"),
                    class_="btn btn-outline-secondary",
                )[tm("back_to_list")],
            ],
        ]


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
        return reverse("upload_pdf")

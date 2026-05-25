from functools import cached_property

from django import forms
from django.core.validators import FileExtensionValidator

import htpy as h

from proj.form_util import StandardFormMixin

from my_app.models import Review
from my_app.router import route
from my_app.services.upload_citation_dataset_service import (
    import_citation_dataset,
)
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import (
    BasePageTemplate,
    FormView,
    GenericForm,
    HtpyTemplateMixin,
    HttpResponseRedirect,
    messages,
    reverse,
    tdt,
)


class CitationUploadForm(StandardFormMixin):
    citation_file = forms.FileField(
        label=tdt("Citation dataset CSV"),
        validators=[FileExtensionValidator(["csv"])],
        widget=forms.FileInput(attrs={"accept": ".csv,text/csv"}),
    )


class CitationUploadPage(BasePageTemplate):
    def title(self):
        return tdt("Import citation dataset")

    def content(self):
        review = self.context["review"]

        return [
            h.h1[tdt("Import citation dataset")],
            h.p(".text-muted")[
                tdt("Upload a CSV file to create a citation dataset.")
            ],
            h.form(
                method="post",
                enctype="multipart/form-data",
                novalidate=True,
            )[
                GenericForm(self.context["form"]),
                h.div(".text-end.mt-3")[
                    h.button(".btn.btn-primary", type="submit")[
                        tdt("Import citation dataset")
                    ],
                ],
            ],
            h.div(".mt-3")[
                h.a(
                    href=reverse("review_detail", args=[review.id]),
                    class_="btn btn-outline-secondary",
                )[tdt("Back to systematic review")],
            ],
        ]


@route(
    "reviews/<int:review_id>/citation-upload/",
    name="citation_upload",
)
class CitationUploadView(MustAccessReviewMixin, FormView, HtpyTemplateMixin):
    form_class = CitationUploadForm
    template_component = CitationUploadPage

    def form_valid(self, form):
        try:
            result = import_citation_dataset(
                self.review,
                form.cleaned_data["citation_file"],
            )
        except ValueError as exc:
            form.add_error("citation_file", str(exc))
            return self.form_invalid(form)

        messages.success(
            self.request,
            tdt(
                "Imported citation dataset with {rows} {row_label} and {columns} {column_label}."
            ).format(
                rows=result.row_count,
                row_label=tdt("row") if result.row_count == 1 else tdt("rows"),
                columns=result.column_count,
                column_label=(
                    tdt("column")
                    if result.column_count == 1
                    else tdt("columns")
                ),
            ),
        )
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("review_detail", args=[self.review.id])

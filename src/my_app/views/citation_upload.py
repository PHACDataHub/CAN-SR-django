import base64
import binascii
from functools import cached_property

from django import forms
from django.core.validators import FileExtensionValidator
from django.forms import BaseFormSet, formset_factory
from django.middleware.csrf import get_token

import htpy as h
from markupsafe import Markup

from proj.form_util import StandardFormMixin
from proj.htpy.util import static_no_cache

from my_app.models import CitationDataset
from my_app.router import route
from my_app.services.upload_citation_dataset_service import (
    import_citation_dataset,
    parse_citation_dataset_source,
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
    format = forms.ChoiceField(
        label=tdt("Format"),
        choices=[("csv", "CSV"), ("ris", "RIS")],
    )
    citation_file = forms.FileField(
        label=tdt("Citation dataset file"),
        validators=[FileExtensionValidator(["csv", "ris", "txt"])],
        widget=forms.FileInput(attrs={"accept": ".csv,.ris,text/csv,.txt"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        citation_file = cleaned_data.get("citation_file")
        selected_format = cleaned_data.get("format")
        if citation_file and selected_format:
            extension = citation_file.name.rsplit(".", 1)[-1].lower()
            if extension == "txt":
                # they like to use .txt for RIS files
                extension = "ris"
            if extension != selected_format:
                self.add_error(
                    "citation_file",
                    tdt("File extension must match the selected format."),
                )
        return cleaned_data


class CitationUploadPage(BasePageTemplate):
    def title(self):
        return tdt("Import citation dataset")

    def content(self):
        review = self.context["review"]

        return [
            h.h1[tdt("Import citation dataset")],
            h.p(".text-muted")[
                tdt(
                    "Upload a CSV or RIS file to add citations to the dataset."
                )
            ],
            h.form(
                method="post",
                enctype="multipart/form-data",
                novalidate=True,
            )[
                GenericForm(self.context["form"]),
                h.div(".text-end.mt-3")[
                    h.button(".btn.btn-primary", type="submit")[
                        tdt("Continue to column mapping")
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
        content = form.cleaned_data["citation_file"].read()
        try:
            parse_citation_dataset_source(content, form.cleaned_data["format"])
        except ValueError as exc:
            form.add_error("citation_file", str(exc))
            return self.form_invalid(form)

        self.request.session[import_session_key(self.review.id)] = {
            "content": base64.b64encode(content).decode("ascii"),
            "format": form.cleaned_data["format"],
        }
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("citation_upload_mapping", args=[self.review.id])


def import_session_key(review_id):
    return f"citation_import_{review_id}"


class ColumnMappingForm(StandardFormMixin):
    existing_column = forms.ChoiceField(
        label=tdt("Existing dataset column"), required=False
    )
    name = forms.CharField(
        label=tdt("Column name"), max_length=255, required=False
    )
    include = forms.BooleanField(
        label=tdt("Include"), required=False, initial=True
    )

    def __init__(self, *args, existing_columns=(), **kwargs):
        super().__init__(*args, **kwargs)
        if not existing_columns:
            self.fields["existing_column"].widget = forms.HiddenInput()
        self.fields["existing_column"].choices = [
            ("", tdt("Create by name")),
            ("title", tdt("Title")),
            ("abstract", tdt("Abstract")),
            *[
                (f"column:{column.id}", column.name)
                for column in existing_columns
            ],
        ]
        self.existing_columns = {
            f"column:{column.id}": column.name for column in existing_columns
        }
        self.existing_names = {
            column.name.strip().casefold() for column in existing_columns
        }

    def clean(self):
        data = super().clean()
        if (
            data.get("include")
            and not data.get("existing_column")
            and not data.get("name", "").strip()
        ):
            self.add_error(
                "name",
                tdt("Enter a column name or choose an existing column."),
            )
        if (
            data.get("include")
            and not data.get("existing_column")
            and data.get("name", "").strip().casefold() in self.existing_names
        ):
            self.add_error(
                "existing_column",
                tdt("Select the existing dataset column."),
            )
        return data

    @property
    def mapped_name(self):
        data = self.cleaned_data
        if not data["include"]:
            return None
        selected = data["existing_column"]
        if selected in ("title", "abstract"):
            return selected
        if selected:
            return self.existing_columns[selected]
        return data["name"].strip()


class BaseColumnMappingFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        names = [form.mapped_name for form in self.forms if form.mapped_name]
        if len({name.casefold() for name in names}) != len(names):
            raise forms.ValidationError(
                tdt(
                    "Multiple uploaded columns map to the same dataset column."
                )
            )


ColumnMappingFormSet = formset_factory(
    ColumnMappingForm, formset=BaseColumnMappingFormSet, extra=0
)


class CitationMappingPage(BasePageTemplate):
    def title(self):
        return tdt("Map citation columns")

    def content(self):
        review = self.context["review"]
        formset = self.context["formset"]
        return [
            h.h1[tdt("Map citation columns")],
            h.p[
                tdt("Rows to import: {count}").format(
                    count=self.context["row_count"]
                )
            ],
            h.div(".text-muted")[
                tdt(
                    "Choose an existing column or create one by name for each uploaded column. Title and abstract are stored separately."
                )
            ],
            h.div(".alert.alert-warning.p-1.fw-bold")[
                tdt(
                    "Please ensure at least one column is named 'title' and another is named 'abstract'"
                )
            ],
            h.form(method="post", novalidate=True)[
                h.input(
                    type="hidden",
                    name="csrfmiddlewaretoken",
                    value=get_token(self.request),
                ),
                Markup(str(formset.management_form)),
                [
                    h.div(".alert.alert-danger")[str(error)]
                    for error in formset.non_form_errors()
                ],
                h.div(".table-responsive")[
                    h.table(".table.table-striped.align-middle")[
                        h.thead[
                            h.tr[
                                h.th[tdt("Uploaded column")],
                                h.th[tdt("Existing dataset column")],
                                h.th[tdt("Column name")],
                                h.th[tdt("Include")],
                            ]
                        ],
                        h.tbody[
                            [
                                self._mapping_row(name, form)
                                for name, form in zip(
                                    self.context["column_names"], formset.forms
                                )
                            ]
                        ],
                    ]
                ],
                h.div(".text-end.mt-3")[
                    h.button(".btn.btn-primary", type="submit")[
                        tdt("Import citations")
                    ]
                ],
            ],
            h.a(
                href=reverse("citation_upload", args=[review.id]),
                class_="btn btn-outline-secondary mt-3",
            )[tdt("Back to upload")],
            h.script(
                src=static_no_cache("citation_column_mapping.js"),
                type="module",
            ),
        ]

    def _mapping_row(self, name, form):
        return h.tr(data_column_mapping_row=True)[
            h.th(scope="row")[name],
            h.td[
                Markup(
                    str(
                        form["existing_column"].as_widget(
                            attrs={
                                "aria-label": tdt(
                                    "Existing column for {column}"
                                ).format(column=name),
                                "data-column-existing": "",
                            }
                        )
                    )
                ),
                Markup(str(form["existing_column"].errors)),
            ],
            h.td[
                Markup(
                    str(
                        form["name"].as_widget(
                            attrs={
                                "aria-label": tdt(
                                    "Column name for {column}"
                                ).format(column=name),
                                "data-column-name": "",
                            }
                        )
                    )
                ),
                Markup(str(form["name"].errors)),
            ],
            h.td[
                Markup(
                    str(
                        form["include"].as_widget(
                            attrs={
                                "aria-label": tdt("Include {column}").format(
                                    column=name
                                ),
                                "data-column-include": "",
                            }
                        )
                    )
                ),
                Markup(str(form["include"].errors)),
            ],
        ]


@route(
    "reviews/<int:review_id>/citation-upload/map/",
    name="citation_upload_mapping",
)
class CitationMappingView(
    MustAccessReviewMixin,
    HtpyTemplateMixin,
):
    template_component = CitationMappingPage

    @cached_property
    def source(self):
        pending = self.request.session.get(import_session_key(self.review.id))
        if not pending:
            return None
        try:
            content = base64.b64decode(pending["content"], validate=True)
            return parse_citation_dataset_source(content, pending["format"])
        except (KeyError, ValueError, binascii.Error):
            return None

    @cached_property
    def existing_columns(self):
        dataset = CitationDataset.objects.filter(review=self.review).first()
        if dataset is None:
            return []
        return list(dataset.columns.order_by("id"))

    @cached_property
    def formset(self):
        data = self.request.POST if self.request.method == "POST" else None
        return ColumnMappingFormSet(
            data,
            initial=self.get_initial_mappings(),
            form_kwargs={"existing_columns": self.existing_columns},
        )

    def get(self, request, *args, **kwargs):
        if self.source is None:
            return HttpResponseRedirect(
                reverse("citation_upload", args=[self.review.id])
            )
        return self.render_to_response(self.get_context_data())

    def post(self, request, *args, **kwargs):
        if self.source is None:
            return HttpResponseRedirect(
                reverse("citation_upload", args=[self.review.id])
            )
        if self.formset.total_form_count() != len(
            self.source.get_column_names()
        ):
            self.formset.is_valid()
            self.formset._non_form_errors = self.formset.error_class(
                [
                    tdt(
                        "The uploaded columns changed. Please upload the file again."
                    )
                ]
            )
            return self.render_to_response(self.get_context_data())
        if not self.formset.is_valid():
            return self.render_to_response(self.get_context_data())

        pending = request.session[import_session_key(self.review.id)]
        try:
            result = import_citation_dataset(
                self.review,
                base64.b64decode(pending["content"]),
                format=pending["format"],
                mappings=[form.mapped_name for form in self.formset.forms],
            )
        except ValueError as exc:
            self.formset._non_form_errors = self.formset.error_class(
                [str(exc)]
            )
            return self.render_to_response(self.get_context_data())

        del request.session[import_session_key(self.review.id)]
        messages.success(
            request,
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
        return HttpResponseRedirect(
            reverse("citation_dataset_detail", args=[self.review.id])
        )

    def get_context_data(self, **kwargs):
        context = {
            **super().get_context_data(**kwargs),
            "column_names": self.source.get_column_names(),
            "row_count": self.source.get_row_count(),
            "formset": self.formset,
        }
        return context

    def get_initial_mappings(self):
        existing_by_name = {
            column.name.strip().casefold(): f"column:{column.id}"
            for column in self.existing_columns
        }
        if self.existing_columns:
            existing_by_name["title"] = "title"
            existing_by_name["abstract"] = "abstract"
        return [
            {
                "name": name,
                "existing_column": existing_by_name.get(
                    name.strip().casefold(), ""
                ),
            }
            for name in self.source.get_column_names()
        ]

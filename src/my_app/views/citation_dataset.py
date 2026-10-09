from functools import cached_property

from django import forms
from django.core.exceptions import SuspiciousOperation
from django.http import HttpResponseBadRequest

import htpy as h

from my_app.models import CitationDataset
from my_app.router import route
from my_app.tables.citation_table import CitationDatasetTableDef
from my_app.tables.table_framework import TableComponent
from my_app.views.tables.common import ReviewTableView
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import (
    BasePageTemplate,
    FormView,
    GenericForm,
    HtpyTemplateMixin,
    HttpResponseRedirect,
)
from shortcuts import breadcrumbs as bc
from shortcuts import (
    messages,
    reverse,
    tdt,
)


class DeleteCitationDatasetForm(forms.Form):
    confirm = forms.BooleanField(
        label=tdt("I confirm that I want to delete this dataset."),
        required=True,
    )


class CitationDatasetDetailPage(BasePageTemplate):
    def title(self):
        return tdt("Dataset")

    def content(self):
        review = self.context["review"]
        dataset = self._get_dataset(review)
        columns = list(dataset.columns.all())
        delete_url = reverse("delete_citation_dataset", args=[review.id])

        return [
            bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(label=tdt("Dataset"))
            ],
            h.h1[tdt("Dataset")],
            h.div(".d-flex.gap-2.justify-content-end.mb-3")[
                h.a(
                    href=reverse("citation_upload", args=[review.id]),
                    class_="btn btn-primary",
                )[tdt("Upload more citations")],
                h.a(
                    href=delete_url,
                    class_="btn btn-outline-danger",
                )[tdt("Delete dataset")],
            ],
            h.div(".border.rounded.p-3.h-100")[
                h.h2(".h5")[tdt("Dataset summary")],
                h.p(".mb-2")[
                    h.strong[tdt("Number of rows")],
                    ": ",
                    self.context["page_obj"].paginator.count,
                ],
                h.div[
                    h.strong[tdt("Columns")],
                    h.ul(".mb-0.mt-2")[
                        [h.li[column.name] for column in columns]
                    ],
                ],
            ],
            h.div(".border.rounded.p-3.h-100")[
                h.h2(".h5")[tdt("All data")],
                TableComponent(
                    page_obj=self.context["page_obj"],
                    columns=self.context["columns"],
                    column_selection_form=self.context[
                        "column_selection_form"
                    ],
                    filter_forms=[],
                    sort_form=None,
                    request=self.request,
                    title=tdt("Dataset"),
                ),
            ],
            h.p(".mt-3")[
                tdt("Sort, filter and see progress on these citations in the"),
                " ",
                h.a(href=reverse("citation_table", args=[review.id]))[
                    tdt("citation table page")
                ],
                ".",
            ],
        ]

    def _get_dataset(self, review):
        cached_dataset = getattr(review, "_citation_dataset", None)
        if cached_dataset is not None:
            return cached_dataset

        return (
            CitationDataset.objects.select_related("review")
            .prefetch_related("columns")
            .get(review=review)
        )


class DeleteCitationDatasetPage(BasePageTemplate):
    def title(self):
        return tdt("Delete dataset")

    def content(self):
        review = self.context["object"]
        detail_url = reverse("citation_dataset_detail", args=[review.id])
        delete_url = reverse("delete_citation_dataset", args=[review.id])

        return [
            bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(label=tdt("Dataset"), href=detail_url),
                bc.BreadcrumbItem(label=tdt("Delete")),
            ],
            h.h1[tdt("Delete dataset")],
            h.p(".text-danger")[
                tdt("This will delete the dataset, rows, and columns.")
            ],
            h.form(
                method="post",
                action=delete_url,
            )[
                GenericForm(self.context["form"]),
                h.div(".d-flex.gap-2.justify-content-end.mt-3")[
                    h.a(
                        href=detail_url,
                        class_="btn btn-outline-secondary",
                    )[tdt("Cancel")],
                    h.button(
                        ".btn.btn-danger",
                        type="submit",
                    )[tdt("Delete dataset")],
                ],
            ],
        ]


@route("reviews/<int:review_id>/dataset/", name="citation_dataset_detail")
class CitationDatasetDetailView(ReviewTableView):
    table_def_class = CitationDatasetTableDef
    template_component = CitationDatasetDetailPage

    def get_queryset(self):
        try:
            self.review.citation_dataset
        except CitationDataset.DoesNotExist:
            raise SuspiciousOperation(tdt("Dataset not found."))
        return super().get_queryset()


@route(
    "reviews/<int:review_id>/dataset/delete/",
    name="delete_citation_dataset",
)
class DeleteCitationDatasetView(
    MustAccessReviewMixin, FormView, HtpyTemplateMixin
):
    form_class = DeleteCitationDatasetForm
    template_component = DeleteCitationDatasetPage

    def get(self, request, *args, **kwargs):
        if self._get_dataset() is None:
            return HttpResponseBadRequest(tdt("Dataset not found."))
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self._get_dataset() is None:
            return HttpResponseBadRequest(tdt("Dataset not found."))
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object"] = self.review
        return context

    def form_valid(self, form):
        self._get_dataset().delete()
        messages.success(self.request, tdt("Dataset deleted."))
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse("review_detail", args=[self.review.id])

    @cached_property
    def _dataset(self):
        try:
            return self.review.citation_dataset
        except CitationDataset.DoesNotExist:
            return None

    def _get_dataset(self):
        return self._dataset

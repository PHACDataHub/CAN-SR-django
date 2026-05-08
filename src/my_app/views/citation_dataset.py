from functools import cached_property

import htpy as h
from django import forms
from django.db.models import Count, Prefetch
from django.http import HttpResponseBadRequest

from my_app.models import (
    CitationDataset,
    CitationDatasetCell,
    SystematicReview,
)
from my_app.router import route
from my_app.views.view_utils import MustAccessSystematicReviewMixin
from shortcuts import (
    BasePageTemplate,
    DetailView,
    FormView,
    GenericForm,
    HtpyTemplateMixin,
    HttpResponseRedirect,
)
from shortcuts import breadcrumbs as bc
from shortcuts import messages, reverse, tdt


class DeleteCitationDatasetForm(forms.Form):
    pass


class CitationDatasetDetailPage(BasePageTemplate):
    def title(self):
        return tdt("Dataset")

    def content(self):
        review = self.context["object"]
        dataset = self._get_dataset(review)
        rows = self._get_rows(dataset)
        columns = list(dataset.columns.all())
        delete_url = reverse("delete_citation_dataset", args=[review.id])

        return [
            bc.BreadcrumbTrailForSystematicReview(review)[
                bc.BreadcrumbItem(label=tdt("Dataset"))
            ],
            h.h1[tdt("Dataset")],
            h.div(".d-flex.gap-2.justify-content-end.mb-3")[
                h.a(
                    href=delete_url,
                    class_="btn btn-outline-danger",
                )[tdt("Delete dataset")]
            ],
            h.div(".border.rounded.p-3.h-100")[
                h.h2(".h5")[tdt("Dataset summary")],
                h.p(".mb-2")[
                    h.strong[tdt("Number of rows")],
                    ": ",
                    dataset.row_count,
                ],
                h.div[
                    h.strong[tdt("Columns")],
                    h.ul(".mb-0.mt-2")[
                        [h.li[column.name] for column in columns]
                    ],
                ],
            ],
            h.div(".border.rounded.p-3.h-100")[
                h.h2(".h5")[tdt("Preview")],
                (
                    h.p(".text-muted.mb-0")[tdt("Showing the first 100 rows.")]
                    if dataset.row_count > 100
                    else h.p(".text-muted.mb-0")[tdt("Showing all rows.")]
                ),
                self._render_table(columns, rows),
            ],
        ]

    def _get_dataset(self, review):
        cached_dataset = getattr(review, "_citation_dataset", None)
        if cached_dataset is not None:
            return cached_dataset

        return (
            CitationDataset.objects.select_related("systematic_review")
            .prefetch_related("columns")
            .annotate(row_count=Count("rows"))
            .get(systematic_review=review)
        )

    def _get_rows(self, dataset):
        return list(
            dataset.rows.order_by("order", "id").prefetch_related(
                Prefetch(
                    "cells",
                    queryset=CitationDatasetCell.objects.select_related(
                        "column"
                    ).order_by("id"),
                )
            )[:100]
        )

    def _render_table(self, columns, rows):
        if not rows:
            return h.p(".mt-3.mb-0")[tdt("No rows in dataset.")]

        return h.div(".table-responsive.mt-3")[
            h.table(".table.table-striped.table-sm.align-middle")[
                h.thead[h.tr[[h.th[column.name] for column in columns]]],
                h.tbody[[self._render_row(columns, row) for row in rows]],
            ]
        ]

    def _render_row(self, columns, row):
        cells_by_column_id = {
            cell.column_id: cell.value for cell in row.cells.all()
        }
        return h.tr[
            [h.td[cells_by_column_id.get(column.id, "")] for column in columns]
        ]


class DeleteCitationDatasetPage(BasePageTemplate):
    def title(self):
        return tdt("Delete dataset")

    def content(self):
        review = self.context["object"]
        detail_url = reverse("citation_dataset_detail", args=[review.id])
        delete_url = reverse("delete_citation_dataset", args=[review.id])

        return [
            bc.BreadcrumbTrailForSystematicReview(review)[
                bc.BreadcrumbItem(label=tdt("Dataset"), href=detail_url),
                bc.BreadcrumbItem(label=tdt("Delete")),
            ],
            h.h1[tdt("Delete dataset")],
            h.p(".text-danger")[
                tdt("This will delete the dataset, rows, columns, and cells.")
            ],
            h.form(method="post", action=delete_url, novalidate=True)[
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


@route("systematic-reviews/<int:pk>/dataset/", name="citation_dataset_detail")
class CitationDatasetDetailView(
    MustAccessSystematicReviewMixin, DetailView, HtpyTemplateMixin
):
    model = SystematicReview
    template_component = CitationDatasetDetailPage

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        try:
            self.object._citation_dataset = self.object.citation_dataset
        except CitationDataset.DoesNotExist:
            return HttpResponseBadRequest(tdt("Dataset not found."))
        return super().get(request, *args, **kwargs)


@route(
    "systematic-reviews/<int:pk>/dataset/delete/",
    name="delete_citation_dataset",
)
class DeleteCitationDatasetView(
    MustAccessSystematicReviewMixin, FormView, HtpyTemplateMixin
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
        context["object"] = self.systematic_review
        context["systematic_review"] = self.systematic_review
        return context

    def form_valid(self, form):
        self._get_dataset().delete()
        messages.success(self.request, tdt("Dataset deleted."))
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse(
            "systematic_review_detail", args=[self.systematic_review.id]
        )

    @cached_property
    def _dataset(self):
        try:
            return self.systematic_review.citation_dataset
        except CitationDataset.DoesNotExist:
            return None

    def _get_dataset(self):
        return self._dataset

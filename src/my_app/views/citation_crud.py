from django import forms
from django.db import transaction
from django.db.models import Max
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.functional import cached_property

import htpy as h
from django_htmx.http import HttpResponseClientRedirect
from markupsafe import Markup

from proj.htpy.modal_component import ModalComponent

from my_app.models import Citation, CitationDataset
from my_app.router import route
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import (
    BasePageTemplate,
    DetailView,
    FormView,
    GenericForm,
    HtpyTemplateMixin,
    StandardFormMixin,
)
from shortcuts import breadcrumbs as bc
from shortcuts import messages, reverse, tdt


class CitationForm(StandardFormMixin, forms.ModelForm):
    title = forms.CharField(label=tdt("Title"))
    abstract = forms.CharField(label=tdt("Abstract"), widget=forms.Textarea)

    class Meta:
        model = Citation
        fields = ("title", "abstract", "doi")
        widgets = {"doi": forms.TextInput}


class CitationColumnForm(StandardFormMixin, forms.Form):
    value = forms.CharField(
        required=False, strip=False, widget=forms.Textarea(attrs={"rows": 2})
    )


class CitationColumnFormSet(forms.BaseFormSet):
    def __init__(self, *args, columns, **kwargs):
        self.columns = columns
        super().__init__(*args, **kwargs)

    def add_prefix(self, index):
        return f"{self.prefix}-{self.columns[index].pk}"

    def _construct_form(self, i, **kwargs):
        form = super()._construct_form(i, **kwargs)
        form.fields["value"].label = self.columns[i].name
        return form

    def clean(self):
        super().clean()
        if any(
            form["value"].html_name not in self.data for form in self.forms
        ):
            raise forms.ValidationError(
                tdt(
                    "Dataset columns have changed. Reload the page and try again."
                )
            )


def CitationBreadcrumbs(review, label, citation=None):
    items = [
        bc.BreadcrumbItem(
            label=tdt("Dataset"),
            href=reverse("citation_dataset_detail", args=[review.pk]),
        ),
        bc.BreadcrumbItem(label=label),
    ]
    if citation is not None:
        items.insert(
            1,
            bc.BreadcrumbItem(
                label=f'{tdt("Citation")} #{citation.pk}',
                href=reverse("citation_detail", args=[review.pk, citation.pk]),
            ),
        )
    return bc.BreadcrumbTrailForReview(review)[items]


class CitationDetailPage(BasePageTemplate):
    def title(self):
        return tdt("Citation")

    def content(self):
        review = self.context["review"]
        citation = self.context["object"]
        args = [review.pk, citation.pk]
        values = [
            (tdt("Title"), citation.display_title),
            (tdt("Abstract"), citation.abstract),
            (tdt("DOI"), citation.doi),
            *[
                (column.name, citation.data.get(column.name))
                for column in citation.dataset.columns.order_by("pk")
            ],
        ]
        return [
            CitationBreadcrumbs(review, self.title()),
            h.h1[self.title()],
            h.div(".d-flex.gap-2.mb-3")[
                h.a(
                    ".btn.btn-primary",
                    href=reverse("edit_citation", args=args),
                )[tdt("Edit citation")],
                h.button(
                    ".btn.btn-outline-danger",
                    type="button",
                    hx_get=reverse("delete_citation", args=args),
                    hx_target="#modal-slot",
                    hx_swap="innerHTML",
                )[tdt("Delete citation")],
            ],
            h.dl[
                [
                    h.fragment[
                        h.dt[label],
                        h.dd[str(value) if value is not None else ""],
                    ]
                    for label, value in values
                ]
            ],
        ]


class CitationFormPage(BasePageTemplate):
    def title(self):
        if self.context["citation"].pk is None:
            return tdt("Manually add citation")
        return f'{tdt("Edit citation")} #{self.context["citation"].pk}'

    def content(self):
        review = self.context["review"]
        citation = self.context["citation"]
        formset = self.context["column_formset"]
        if citation.pk is None:
            parent_citation = None
            cancel_url = reverse("citation_dataset_detail", args=[review.pk])
        else:
            parent_citation = citation
            cancel_url = reverse(
                "citation_detail", args=[review.pk, citation.pk]
            )

        return [
            CitationBreadcrumbs(review, self.title(), parent_citation),
            h.h1[self.title()],
            h.form(method="post")[
                GenericForm(self.context["form"]),
                Markup(str(formset.management_form)),
                (
                    h.ul(".text-danger")[
                        [h.li[error] for error in formset.non_form_errors()]
                    ]
                    if formset.non_form_errors()
                    else None
                ),
                [GenericForm(form, include_csrf=False) for form in formset],
                h.div(".d-flex.gap-2.justify-content-end")[
                    h.a(".btn.btn-outline-secondary", href=cancel_url)[
                        tdt("Cancel")
                    ],
                    h.button(".btn.btn-primary", type="submit")[
                        tdt("Save citation")
                    ],
                ],
            ],
        ]


class DatasetCitationMixin(MustAccessReviewMixin):
    @cached_property
    def dataset(self):
        return get_object_or_404(CitationDataset, review=self.review)

    @cached_property
    def citation(self):
        rows = self.dataset.rows.all()
        if self.request.method == "POST":
            rows = rows.select_for_update()
        return get_object_or_404(rows, pk=self.kwargs["citation_id"])


@route(
    "reviews/<int:review_id>/dataset/citations/<int:citation_id>/",
    name="citation_detail",
)
class CitationDetailView(DatasetCitationMixin, DetailView, HtpyTemplateMixin):
    template_component = CitationDetailPage

    def get_object(self, queryset=None):
        return self.citation


class CitationFormView(DatasetCitationMixin, FormView, HtpyTemplateMixin):
    form_class = CitationForm
    template_component = CitationFormPage

    @cached_property
    def column_formset(self):
        columns = list(self.dataset.columns.order_by("pk"))
        count = len(columns)
        formset_class = forms.formset_factory(
            CitationColumnForm,
            formset=CitationColumnFormSet,
            extra=0,
            min_num=count,
            max_num=count,
            absolute_max=count,
            validate_min=True,
            validate_max=True,
        )
        return formset_class(
            self.request.POST if self.request.method == "POST" else None,
            columns=columns,
            initial=[
                {"value": self.citation.data.get(column.name)}
                for column in columns
            ],
            prefix="columns",
        )

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "instance": self.citation}

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            citation=self.citation,
            column_formset=self.column_formset,
            **kwargs,
        )

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        self.dataset = get_object_or_404(
            CitationDataset.objects.select_for_update(), review=self.review
        )
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        if not self.column_formset.is_valid():
            return self.form_invalid(form)

        citation = form.save(commit=False)
        if citation.pk is None:
            citation.order = (
                self.dataset.rows.aggregate(Max("order"))["order__max"] or 0
            ) + 1

        citation.data = {
            **citation.data,
            **{
                column.name: column_form.cleaned_data["value"]
                for column, column_form in zip(
                    self.column_formset.columns,
                    self.column_formset.forms,
                    strict=True,
                )
                if column_form.has_changed()
            },
        }
        citation.save()
        return redirect("citation_detail", self.review.pk, citation.pk)


@route("reviews/<int:review_id>/dataset/citations/add/", name="add_citation")
class AddCitationView(CitationFormView):
    @cached_property
    def citation(self):
        return Citation(dataset=self.dataset)


@route(
    "reviews/<int:review_id>/dataset/citations/<int:citation_id>/edit/",
    name="edit_citation",
)
class EditCitationView(CitationFormView):
    pass


class DeleteCitationForm(forms.Form):
    confirm = forms.BooleanField(
        label=tdt("I confirm that I want to delete this citation.")
    )


@route(
    "reviews/<int:review_id>/dataset/citations/<int:citation_id>/delete/",
    name="delete_citation",
)
class DeleteCitationView(DatasetCitationMixin, FormView):
    form_class = DeleteCitationForm
    form_id = "delete-citation-form"

    def get(self, request, *args, **kwargs):
        return self.render_modal(self.get_form())

    def form_invalid(self, form):
        return self.render_modal(form)

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        self.citation.delete()
        messages.success(self.request, tdt("Citation deleted."))
        url = reverse("citation_dataset_detail", args=[self.review.pk])
        if self.request.headers.get("HX-Request") == "true":
            return HttpResponseClientRedirect(url)
        return redirect(url)

    def render_modal(self, form):
        citation = self.citation
        url = reverse("delete_citation", args=[self.review.pk, citation.pk])
        return HttpResponse(
            ModalComponent(
                title=tdt("Delete citation"),
                modal_id="delete-citation-modal",
                footer=h.fragment[
                    h.button(
                        ".btn.btn-secondary",
                        type="button",
                        data_modal_close=True,
                    )[tdt("Cancel")],
                    h.button(
                        ".btn.btn-danger", type="submit", form=self.form_id
                    )[tdt("Delete citation")],
                ],
            )[
                h.p[citation.display_title],
                h.form(
                    id=self.form_id,
                    method="post",
                    action=url,
                    hx_post=url,
                    hx_target="#modal-slot",
                    hx_swap="innerHTML",
                )[GenericForm(form)],
            ]
        )

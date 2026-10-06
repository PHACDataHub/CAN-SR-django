from django import forms
from django.db.models import Q
from django.utils.functional import cached_property

import htpy as h
from autocomplete import AutocompleteWidget

from proj.form_util import FormControlMixin, SelectMixin
from proj.htpy.generic_form import GenericForm
from proj.text import tdt

from my_app.autocompletes import (
    CitationHumanStatusAutocomplete,
    CitationStatusAutocomplete,
)


class ScreeningFilterForm(FormControlMixin, SelectMixin, forms.Form):
    review = forms.MultipleChoiceField(
        label=tdt("Human review status"),
        required=False,
        choices=CitationHumanStatusAutocomplete.choice_dict.items(),
        widget=AutocompleteWidget(
            ac_class=CitationHumanStatusAutocomplete,
            options={
                "multiselect": True,
                "placeholder": tdt("Select statuses"),
            },
        ),
    )
    screening = forms.MultipleChoiceField(
        label=tdt("Screening status"),
        required=False,
        choices=CitationStatusAutocomplete.choice_dict.items(),
        widget=AutocompleteWidget(
            ac_class=CitationStatusAutocomplete,
            options={
                "multiselect": True,
                "placeholder": tdt("Select statuses"),
            },
        ),
    )
    search = forms.CharField(
        label=tdt("Title or abstract"),
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": tdt("Search by text"),
            }
        ),
    )

    def filter_queryset(self, citations, stage):
        self.is_valid()
        review = self.cleaned_data.get("review")
        if review:
            citations = getattr(citations, f"add_{stage}_human_status")()
            citations = citations.filter(
                **{f"{stage}_human_status__in": review}
            )

        screening = self.cleaned_data.get("screening")
        if screening:
            citations = getattr(citations, f"add_{stage}_overall_status")()
            citations = citations.filter(
                **{f"{stage}_overall_status__in": screening}
            )

        search = self.cleaned_data.get("search")
        if search:
            citations = citations.filter(
                Q(title__icontains=search) | Q(abstract__icontains=search)
            )
        return citations


class ScreeningFilterMixin:
    screening_stage = None

    @cached_property
    def filter_form(self):
        return ScreeningFilterForm(self.request.GET)

    def get_queryset(self):
        return self.filter_form.filter_queryset(
            super().get_queryset(), self.screening_stage
        )

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            "filter_form": self.filter_form,
        }


def ScreeningFilters(form, action):
    form.is_valid()
    filters_active = any(
        form.cleaned_data.get(name)
        for name in ("review", "screening", "search")
    )
    return h.details(".border.rounded.p-3.mb-4", open=filters_active)[
        h.summary[tdt("Filters")],
        h.form(method="get", action=action)[
            GenericForm(form, include_csrf=False),
            h.button(".btn.btn-primary", type="submit")[tdt("Filter")],
        ],
    ]

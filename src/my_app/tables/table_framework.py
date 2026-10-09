"""Reusable queryset tables; project-specific querying belongs in TableDef subclasses."""

from dataclasses import dataclass

from django import forms
from django.core.exceptions import ObjectDoesNotExist
from django.utils.functional import cached_property
from django.views.generic import ListView

import htpy as h

from proj.form_util import StandardFormMixin
from proj.htpy.generic_form import GenericForm
from proj.htpy.util import HtpyComponent
from proj.text import tdt


@dataclass
class Column:
    key: str
    header: object
    sort_field: str = None
    exportable: bool = True
    disableable: bool = True
    default_enabled: bool = True
    filter_form_class: type = None

    def get_filter_form_class(self):
        return self.filter_form_class

    @property
    def sortable(self):
        return self.sort_field is not None

    def render_header(self):
        return self.header

    def get_cell_css_class(self, record):
        return None

    def render_cell(self, record):
        raise NotImplementedError

    def render_plaintext_header(self):
        return self.render_header()

    def render_plaintext_cell(self, record):
        return self.render_cell(record)

    def get_filter_form(self, data=None):
        form_filter_class = self.get_filter_form_class()
        if form_filter_class is None:
            return None
        return form_filter_class(data, prefix=f"filter_form_{self.key}")

    def render_filter_form(self, form):
        return GenericForm(form, include_csrf=False)

    def filter_queryset(self, queryset, cleaned_data):
        return queryset


@dataclass
class AttributeColumn(Column):
    attribute: str = None
    null_fallback: str = ""

    def get_cell_css_class(self, record):
        if not self.get_value(record):
            return "text-secondary"

        return super().get_cell_css_class(record)

    def get_value(self, record):
        value = record
        for part in (self.attribute or self.key).split("."):
            try:
                value = getattr(value, part, None)
            except ObjectDoesNotExist:
                value = None
            if value is None:
                return None
        return value

    def render_cell(self, record):
        value = self.get_value(record)
        if value is None:
            return self.null_fallback

        return str(value)


@dataclass
class ChoiceAttributeColumn(AttributeColumn):
    choices: type = None

    def render_cell(self, record):
        value = self.get_value(record)
        if value is None:
            return self.null_fallback
        return self.choices(value).label


@dataclass
class NumericAttributeColumn(AttributeColumn):
    # truncates to 2 decimal points
    def render_cell(self, record):
        value = self.get_value(record)
        if value is None:
            return self.null_fallback
        return f"{value:.2f}"


class DateTimeAttributeColumn(AttributeColumn):
    def render_cell(self, record):
        value = self.get_value(record)
        if value is None:
            return self.null_fallback
        return value.strftime("%Y-%m-%d %H:%M:%S")


def abbreviate_middle(value, edge_length=50):
    if len(value) > 2 * edge_length:
        return f"{value[:edge_length]}…{value[-edge_length:]}"
    return value


class AbbreviatedAttributeColumn(AttributeColumn):
    def render_cell(self, record):
        return abbreviate_middle(super().render_cell(record))

    def render_plaintext_cell(self, record):
        return super().render_cell(record)


class ColumnSelectionForm(StandardFormMixin, forms.Form):
    submitted = forms.BooleanField(widget=forms.HiddenInput, initial=True)
    columns = forms.MultipleChoiceField(
        label=tdt("Visible columns"),
        required=False,
        widget=forms.CheckboxSelectMultiple(
            attrs={"class": "table-column-checkboxes"}
        ),
    )

    def __init__(self, *args, columns, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["columns"].choices = [
            (column.key, column.render_plaintext_header())
            for column in columns
            if column.disableable
        ]
        self.initial["columns"] = [
            column.key for column in columns if column.default_enabled
        ]


class SortForm(StandardFormMixin, forms.Form):
    column = forms.ChoiceField(label=tdt("Sort by"), required=False)
    direction = forms.ChoiceField(
        label=tdt("Direction"),
        choices=[("asc", tdt("Ascending")), ("desc", tdt("Descending"))],
        required=False,
        initial="asc",
    )

    def __init__(self, *args, columns, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["column"].choices = [
            ("", tdt("Default order")),
            *[
                (column.key, column.render_plaintext_header())
                for column in columns
                if column.sortable
            ],
        ]


class TableDef:
    columns = ()
    default_ordering = ("pk",)

    def __init__(self, *, data=None, **kwargs):
        self.data = data
        self.columns = list(self.get_columns())
        keys = [column.key for column in self.columns]
        if len(keys) != len(set(keys)):
            raise ValueError("Table column keys must be unique")

    def get_columns(self):
        return self.columns

    def form_data(self, prefix):
        if self.data is not None and any(
            key.startswith(f"{prefix}-") for key in self.data
        ):
            return self.data
        return None

    @cached_property
    def column_selection_form(self):
        return ColumnSelectionForm(
            self.form_data("column_selection_form"),
            columns=self.columns,
            prefix="column_selection_form",
        )

    @cached_property
    def enabled_columns(self):
        form = self.column_selection_form
        selected = form.initial["columns"]
        if form.is_bound and form.is_valid():
            selected = form.cleaned_data["columns"]
        return [
            column
            for column in self.columns
            if not column.disableable or column.key in selected
        ]

    @cached_property
    def filter_forms(self):
        forms = {}
        for column in self.enabled_columns:
            form = column.get_filter_form(
                self.form_data(f"filter_form_{column.key}")
            )
            if form:
                forms[column.key] = form
        return forms

    @cached_property
    def sort_form(self):
        return SortForm(
            self.form_data("sort_form"),
            columns=self.enabled_columns,
            prefix="sort_form",
        )

    @property
    def export_columns(self):
        return [column for column in self.enabled_columns if column.exportable]

    def get_base_queryset(self):
        raise NotImplementedError

    def annotate_queryset(self, queryset):
        return queryset

    def filter_queryset(self, queryset):
        for column in self.enabled_columns:
            form = self.filter_forms.get(column.key)
            if form is not None and form.is_bound and form.is_valid():
                queryset = column.filter_queryset(queryset, form.cleaned_data)
        return queryset

    def order_queryset(self, queryset):
        form = self.sort_form
        if form.is_bound and form.is_valid() and form.cleaned_data["column"]:
            column = next(
                column
                for column in self.enabled_columns
                if column.key == form.cleaned_data["column"]
            )
            field = column.sort_field
            if form.cleaned_data["direction"] == "desc":
                field = f"-{field}"
            return queryset.order_by(field, *self.default_ordering)
        return queryset.order_by(*self.default_ordering)

    def get_queryset(self):
        queryset = self.annotate_queryset(self.get_base_queryset())
        return self.order_queryset(self.filter_queryset(queryset))

    def prepare_page(self, records):
        """Hook for batching related records or priming request datafetchers."""


class TableView(ListView):
    table_def_class = None
    paginate_by = 25

    def get_table_def_kwargs(self):
        return {"data": self.request.GET}

    @cached_property
    def table_def(self):
        return self.table_def_class(**self.get_table_def_kwargs())

    def get_queryset(self):
        return self.table_def.get_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        page = context["page_obj"]
        page.object_list = list(page.object_list)
        self.table_def.prepare_page(page.object_list)
        context.update(
            table_def=self.table_def,
            columns=self.table_def.enabled_columns,
            column_selection_form=self.table_def.column_selection_form,
            filter_forms=self.table_def.filter_forms,
            sort_form=self.table_def.sort_form,
        )
        return context


class TableComponent(HtpyComponent):
    def __init__(
        self,
        *,
        page_obj,
        columns,
        column_selection_form,
        filter_forms,
        sort_form,
        request,
        title,
    ):
        self.page_obj = page_obj
        self.columns = columns
        self.column_selection_form = column_selection_form
        self.filter_forms = filter_forms
        self.sort_form = sort_form
        self.request = request
        self.title = title

    def render_column_selection(self):
        return h.fieldset[
            h.legend(".h5")[tdt("Columns")],
            GenericForm(self.column_selection_form, include_csrf=False),
        ]

    def render_filter_form(self, column, form):
        return h.div(".col-12.col-lg-6.col-xl-4.table-filter-control")[
            column.render_filter_form(form),
        ]

    def render_sort_form(self):
        return h.fieldset(".table-sort-controls")[
            h.legend(".h5")[tdt("Sorting")],
            GenericForm(self.sort_form, include_csrf=False),
        ]

    def render_table(self):
        rows = [
            h.tr[[h.td[column.render_cell(record)] for column in self.columns]]
            for record in self.page_obj.object_list
        ]
        if not rows:
            rows = [
                h.tr[h.td(colspan=len(self.columns))[tdt("No records found.")]]
            ]
        return h.div(
            ".table-responsive.stickyheader-table-container",
            tabindex="0",
            role="region",
            aria_label=self.title,
        )[
            h.table(".table.table-striped.table-bordered")[
                h.caption(".visually-hidden")[self.title],
                h.thead[
                    h.tr[
                        [
                            h.th(scope="col")[column.render_header()]
                            for column in self.columns
                        ]
                    ]
                ],
                h.tbody[rows],
            ]
        ]

    def page_url(self, number):
        params = self.request.GET.copy()
        params["page"] = number
        return f"{self.request.path}?{params.urlencode()}"

    def render_pagination(self):
        page = self.page_obj
        previous = None
        following = None
        if page.has_previous():
            previous = h.a(
                ".btn.btn-outline-secondary",
                href=self.page_url(page.previous_page_number()),
            )[tdt("Previous")]
        if page.has_next():
            following = h.a(
                ".btn.btn-outline-secondary",
                href=self.page_url(page.next_page_number()),
            )[tdt("Next")]
        return h.nav(
            ".row.align-items-center.g-3.my-3",
            aria_label=tdt("Table pagination"),
        )[
            h.div(".col-auto")[previous],
            h.div(".col-auto")[
                tdt("Page"), f" {page.number} / {page.paginator.num_pages}"
            ],
            h.div(".col-auto")[following],
        ]

    def render(self):
        return h.div[
            h.form(method="get", action=self.request.path)[
                self.render_column_selection(),
                h.div(".row.gx-4")[
                    [
                        self.render_filter_form(
                            column, self.filter_forms[column.key]
                        )
                        for column in self.columns
                        if column.key in self.filter_forms
                    ]
                ],
                self.render_sort_form(),
                h.button(".btn.btn-primary.mb-3", type="submit")[
                    tdt("Update")
                ],
            ],
            self.render_table(),
            self.render_pagination(),
        ]

import json
from datetime import timedelta

from django import forms
from django.db.models import Count, F, Q
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.functional import cached_property
from django.utils.timezone import now, template_localtime
from django.views.generic import ListView, TemplateView

import htpy as h
from autocomplete import AutocompleteWidget
from django_tasks_db.compat import TaskResultStatus
from django_tasks_db.models import DBTaskResult

from proj.form_util import FormControlMixin, SelectMixin
from proj.htpy.base_page import BasePageTemplate
from proj.htpy.generic_form import GenericForm
from proj.text import tdt

from my_app.autocompletes import TaskNameAutocomplete, short_task_name
from my_app.router import route
from my_app.views.view_utils import url_with_same_params
from shortcuts import HtpyTemplateMixin, MustPassRuleMixin

QUEUED = TaskResultStatus.READY
ACTIVE = TaskResultStatus.RUNNING
SUCCESSFUL = TaskResultStatus.SUCCESSFUL
FAILED = TaskResultStatus.FAILED


def current_tasks():
    return DBTaskResult.objects.filter(
        Q(status__in=(QUEUED, ACTIVE))
        | Q(
            status__in=(SUCCESSFUL, FAILED),
            finished_at__gte=now() - timedelta(minutes=5),
        )
    )


class TaskFilterForm(FormControlMixin, SelectMixin, forms.Form):
    task_name = forms.Field(
        label=tdt("Task names"),
        required=False,
        widget=AutocompleteWidget(
            ac_class=TaskNameAutocomplete,
            options={
                "multiselect": True,
                "placeholder": tdt("Select task names"),
            },
        ),
    )
    status = forms.ChoiceField(
        label=tdt("Status"),
        required=False,
        choices=[("", tdt("All statuses")), *TaskResultStatus.choices],
    )
    include_history = forms.BooleanField(
        label=tdt("Include tasks terminated more than 5 minutes ago"),
        required=False,
    )
    queued_after = forms.DateTimeField(
        label=tdt("Queued at or after"),
        required=False,
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M:%S",
            attrs={"type": "datetime-local", "step": "1"},
        ),
    )
    queued_before = forms.DateTimeField(
        label=tdt("Queued at or before"),
        required=False,
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M:%S",
            attrs={"type": "datetime-local", "step": "1"},
        ),
    )
    min_queue_to_completion = forms.DecimalField(
        label=tdt("Queue to completion exceeds (seconds)"),
        required=False,
        min_value=0,
        max_digits=8,
        decimal_places=2,
    )


TASK_COLUMNS = {
    "task_path": tdt("Task name"),
    "status": tdt("Status"),
    "enqueued_at": tdt("Queued at"),
    "started_at": tdt("Started at"),
    "finished_at": tdt("Finished at"),
    "duration": tdt("Duration"),
    "queue_to_start": tdt("Queue to start"),
}


def format_timestamp(value):
    if value is None:
        return "—"
    return date_format(template_localtime(value), "Y-m-d H:i:s T")


def format_elapsed(value):
    if value is None:
        return "—"
    return str(value)


class TaskListPage(BasePageTemplate):
    def head_title(self):
        return tdt("Background tasks")

    def sort_header(self, field, label):
        sort = self.context["sort"]
        attrs = {"scope": "col"}
        next_sort = field
        if sort == field:
            attrs["aria_sort"] = "ascending"
            next_sort = f"-{field}"
        elif sort == f"-{field}":
            attrs["aria_sort"] = "descending"
        return h.th(attrs)[
            h.a(
                href=url_with_same_params(
                    self.request, sort=next_sort, page=None
                )
            )[label]
        ]

    def task_row(self, task):
        name = short_task_name(task.task_path)
        if self.context["can_view_task_admin"]:
            name = h.a(
                href=reverse(
                    "admin:django_tasks_database_dbtaskresult_change",
                    args=[task.pk],
                )
            )[name]
        return h.tr[
            h.th(".text-break", scope="row")[name],
            h.td[task.get_status_display()],
            h.td[format_timestamp(task.enqueued_at)],
            h.td[format_timestamp(task.started_at)],
            h.td[format_timestamp(task.finished_at)],
            h.td[format_elapsed(task.duration)],
            h.td[format_elapsed(task.queue_to_start)],
            h.td[
                h.code(".text-break")[
                    json.dumps(task.args_kwargs, ensure_ascii=False)
                ]
            ],
        ]

    def pagination(self):
        page = self.context["page_obj"]
        previous = None
        following = None
        if page.has_previous():
            previous = h.a(
                ".btn.btn-outline-primary",
                href=url_with_same_params(
                    self.request, page=page.previous_page_number()
                ),
            )[tdt("Previous")]
        if page.has_next():
            following = h.a(
                ".btn.btn-outline-primary",
                href=url_with_same_params(
                    self.request, page=page.next_page_number()
                ),
            )[tdt("Next")]
        return h.nav(
            ".d-flex.gap-2.align-items-center", aria_label=tdt("Task pages")
        )[
            tdt("Page {page} of {total}").format(
                page=page.number, total=page.paginator.num_pages
            ),
            previous,
            following,
        ]

    def content(self):
        tasks = list(self.context["object_list"])
        table = h.p[tdt("No tasks match these filters.")]
        if tasks:
            table = h.div(".table-responsive.mt-3")[
                h.table(".table.table-striped")[
                    h.thead[
                        h.tr[
                            [
                                self.sort_header(*column)
                                for column in TASK_COLUMNS.items()
                            ],
                            h.th(scope="col")[tdt("JSON arguments")],
                        ]
                    ],
                    h.tbody[[self.task_row(task) for task in tasks]],
                ]
            ]
        return [
            h.h1[self.head_title()],
            h.p[h.a(href=reverse("task_summary"))[tdt("Task summary")]],
            h.p[
                tdt(
                    "Shows queued and running tasks and tasks that ended in the last 5 minutes."
                )
            ],
            h.form(method="get")[
                GenericForm(self.context["filter_form"], include_csrf=False),
                h.input(
                    type="hidden", name="sort", value=self.context["sort"]
                ),
                h.button(".btn.btn-primary.me-2", type="submit")[
                    tdt("Apply filters")
                ],
                h.a(href=reverse("task_list"))[tdt("Reset")],
            ],
            table,
            self.pagination() if self.context["is_paginated"] else None,
        ]


@route("tasks/", name="task_list")
class TaskListView(MustPassRuleMixin, HtpyTemplateMixin, ListView):
    rule_name = "is_admin"
    template_component = TaskListPage
    paginate_by = 50

    @cached_property
    def filter_form(self):
        form = TaskFilterForm(self.request.GET)
        form.is_valid()
        return form

    @cached_property
    def sort(self):
        sort = self.request.GET.get("sort", "-enqueued_at")
        if sort.removeprefix("-") in TASK_COLUMNS:
            return sort
        return "-enqueued_at"

    def get_queryset(self):
        filters = self.filter_form.cleaned_data
        tasks = current_tasks()
        if filters.get("include_history"):
            tasks = DBTaskResult.objects.all()
        task_names = [name for name in filters["task_name"] if name]
        if task_names:
            tasks = tasks.filter(task_path__in=task_names)
        if status := filters.get("status"):
            tasks = tasks.filter(status=status)
        if queued_after := filters.get("queued_after"):
            tasks = tasks.filter(enqueued_at__gte=queued_after)
        if queued_before := filters.get("queued_before"):
            tasks = tasks.filter(enqueued_at__lte=queued_before)
        min_seconds = filters.get("min_queue_to_completion")
        if min_seconds is not None:
            threshold = timedelta(milliseconds=int(min_seconds * 1_000))
            tasks = tasks.alias(
                queue_to_completion=F("finished_at") - F("enqueued_at"),
            ).filter(queue_to_completion__gt=threshold)

        sort_field = F(self.sort.removeprefix("-"))
        if self.sort.startswith("-"):
            order = sort_field.desc(nulls_last=True)
        else:
            order = sort_field.asc(nulls_last=True)

        return (
            tasks.only(
                "task_path",
                "status",
                "args_kwargs",
                "enqueued_at",
                "started_at",
                "finished_at",
            )
            .annotate(
                duration=F("finished_at") - F("started_at"),
                queue_to_start=F("started_at") - F("enqueued_at"),
            )
            .order_by(order, "pk")
        )

    def get_context_data(self, **kwargs):
        user = self.request.user
        return super().get_context_data(
            filter_form=self.filter_form,
            sort=self.sort,
            can_view_task_admin=user.is_staff
            and user.has_perm("django_tasks_database.view_dbtaskresult"),
            **kwargs,
        )


SUMMARY_COLUMNS = {
    QUEUED: tdt("Queued"),
    ACTIVE: tdt("Running"),
    SUCCESSFUL: tdt("Successful"),
    FAILED: tdt("Failed"),
}


class TaskSummaryPage(BasePageTemplate):
    def head_title(self):
        return tdt("Task summary")

    def count_row(self, label, counts):
        return h.tr[
            h.th(".text-break", scope="row")[label],
            [h.td[str(counts.get(status, 0))] for status in SUMMARY_COLUMNS],
        ]

    def content(self):
        return [
            h.h1[self.head_title()],
            h.p[tdt("Queued counts include scheduled tasks.")],
            h.div(".table-responsive")[
                h.table(".table.table-striped")[
                    h.thead[
                        h.tr[
                            h.th(scope="col", rowspan=2)[tdt("Task name")],
                            h.th(scope="colgroup", colspan=2)[
                                tdt("Backlog and active")
                            ],
                            h.th(scope="colgroup", colspan=2)[
                                tdt("Ended in the last 5 minutes")
                            ],
                        ],
                        h.tr[
                            [
                                h.th(scope="col")[label]
                                for label in SUMMARY_COLUMNS.values()
                            ]
                        ],
                    ],
                    h.tbody[
                        [
                            self.count_row(short_task_name(task_path), counts)
                            for task_path, counts in self.context[
                                "task_counts"
                            ].items()
                        ]
                    ],
                    h.tfoot[
                        self.count_row(tdt("Total"), self.context["totals"])
                    ],
                ]
            ],
        ]


@route("tasks/summary/", name="task_summary")
class TaskSummaryView(HtpyTemplateMixin, TemplateView):
    template_component = TaskSummaryPage

    def get_context_data(self, **kwargs):
        totals = dict.fromkeys(SUMMARY_COLUMNS, 0)
        task_counts = {}
        rows = (
            current_tasks()
            .values("task_path", "status")
            .annotate(count=Count("pk"))
            .order_by("task_path", "status")
        )
        for row in rows:
            status = row["status"]
            totals[status] += row["count"]
            task_counts.setdefault(row["task_path"], {})[status] = row["count"]
        return super().get_context_data(
            task_counts=task_counts, totals=totals, **kwargs
        )

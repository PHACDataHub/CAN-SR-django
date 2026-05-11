from django.conf import settings
from django.middleware.csrf import get_token
from django.urls import reverse

import htpy as h

from proj.htpy.base_page import BasePageTemplate
from proj.text import tdt


def _render_table(rows, empty_text, headers, row_renderer):
    if not rows:
        return h.p(".text-muted")[empty_text]

    return h.table(".table.table-sm.align-middle")[
        h.thead[h.tr[[h.th[header] for header in headers]],],
        h.tbody[[row_renderer(row) for row in rows]],
    ]


class BackgroundTasksPage(BasePageTemplate):
    def title(self):
        return tdt("Background tasks")

    def content(self):
        queued_tasks = self.context["queued_tasks"]
        task_runs = self.context["task_runs"]

        return [
            h.h1[tdt("Background tasks")],
            h.p(".text-muted")[
                tdt("See also"),
                # admin link to django_database_task models
                h.a(
                    ".ms-1",
                    href=reverse(
                        "admin:django_database_task_databasetask_changelist"
                    ),
                )[tdt("Django admin view")],
            ],
            h.p()[
                tdt(
                    "This demo is intended for use with the django_database_task.backends.DatabaseTaskBackend"
                    f"currently, the app is using the {settings.TASKS['default']['BACKEND']} backend"
                )
            ],
            h.div(".d-flex.gap-2.flex-wrap.mb-4")[
                self._enqueue_form(
                    action="enqueue_sync_demo_task",
                    label=tdt("Enqueue sync demo task"),
                    btn_cls=".btn.btn-primary",
                ),
                self._enqueue_form(
                    action="enqueue_async_demo_task",
                    label=tdt("Enqueue async demo task"),
                    btn_cls=".btn.btn-outline-primary",
                ),
            ],
            h.div(".alert.alert-info")[
                tdt(
                    "Run this in a separate worker process; it will keep polling for new work:"
                ),
                h.br,
                h.code[
                    "python src/manage.py run_database_tasks --continuous --interval 1"
                ],
                h.br,
                tdt(
                    "Use --max-tasks 1 for a single drain, or Ctrl-C to stop the continuous worker."
                ),
            ],
            h.h2[tdt("Queued tasks")],
            _render_table(
                queued_tasks,
                tdt("No queued tasks yet."),
                [
                    tdt("Task result ID"),
                    tdt("Task"),
                    tdt("Queue"),
                    tdt("Backend"),
                    tdt("Status"),
                    tdt("Priority"),
                    tdt("Label"),
                    tdt("Return value"),
                ],
                self._render_queued_task_row,
            ),
            h.h2(".mt-4")[tdt("Demo task runs")],
            _render_table(
                task_runs,
                tdt("No demo task has been executed yet."),
                [
                    tdt("Task result ID"),
                    tdt("Kind"),
                    tdt("Label"),
                    tdt("SR count"),
                    tdt("Attempt"),
                    tdt("Completed at"),
                ],
                self._render_task_run_row,
            ),
        ]

    def _enqueue_form(self, action, label, btn_cls):
        return h.form(method="post", novalidate=True)[
            h.input(
                type="hidden",
                name="csrfmiddlewaretoken",
                value=get_token(self.request),
            ),
            h.input(type="hidden", name="task_kind", value=action),
            h.button(btn_cls, type="submit")[label],
        ]

    def _render_queued_task_row(self, task):
        return h.tr[
            h.td[str(task.id)],
            h.td[str(task.task_path)],
            h.td[str(task.queue_name)],
            h.td[str(task.backend_name)],
            h.td[str(task.status)],
            h.td[str(task.priority)],
            h.td[str(task.kwargs_json.get("label", ""))],
            h.td[str(task.return_value_json or "")],
        ]

    def _render_task_run_row(self, task_run):
        return h.tr[
            h.td[str(task_run.task_result_id)],
            h.td[str(task_run.kind)],
            h.td[str(task_run.label)],
            h.td[str(task_run.record_count)],
            h.td[str(task_run.attempt)],
            h.td[str(task_run.completed_at)],
        ]

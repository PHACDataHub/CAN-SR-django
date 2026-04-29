from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from django_database_task.models import DatabaseTask

from proj.htpy.util import HtpyTemplateMixin
from proj.text import tdt

from my_app.htpy.background_tasks import BackgroundTasksPage
from my_app.models import DemoTaskRun, Project
from my_app.router import route
from my_app.tasks.example_tasks import (
    record_project_snapshot,
    record_project_snapshot_async,
)


@route("background-tasks/", name="background_tasks_demo")
class BackgroundTasksDemo(TemplateView, HtpyTemplateMixin):
    template_component = BackgroundTasksPage

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["queued_tasks"] = list(
            DatabaseTask.objects.order_by("-priority", "-enqueued_at", "-id")[
                :10
            ]
        )
        context["task_runs"] = list(
            DemoTaskRun.objects.order_by("-completed_at", "-id")[:10]
        )
        return context

    def post(self, request, *args, **kwargs):
        label = timezone.now().isoformat(timespec="seconds")
        task_kind = request.POST.get("task_kind")
        project_count = Project.objects.count()

        if task_kind == "enqueue_async_demo_task":
            record_project_snapshot_async.enqueue(
                label=label, project_count=project_count
            )
            messages.success(request, tdt("Async demo task queued."))
        else:
            record_project_snapshot.enqueue(label=label)
            messages.success(request, tdt("Sync demo task queued."))

        return redirect(reverse("background_tasks_demo"))
